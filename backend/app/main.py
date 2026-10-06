import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager
import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import create_tables
# Import models to register them with Base.metadata before create_tables()
from app.models import (  # noqa: F401
    User, Conversation, Message, OAuthAccount, Attachment,
    DocumentChunk, DocumentSection, DocumentSummary,
    Entity, EntityRelationship, DocumentEntity,
    ReportTemplate, DocumentFolder,
)
from app.routers import (
    auth_router, conversations_router, messages_router, uploads_router,
    documents_router, graph_router, agent_router, ai_router, files_router,
    templates_router, folders_router, rag_router,
)
from app.services.ai import AIService
from app.services.embedding import EmbeddingService
from app.router.service import RouterService


class _SuppressHealthCheck(logging.Filter):
    """Drop uvicorn access-log lines for the /health readiness probe (fires
    every ~10s) so they don't drown out real request logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "GET /health " not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_SuppressHealthCheck())


def _mem_mb() -> int:
    try:
        import psutil, os
        return psutil.Process(os.getpid()).memory_info().rss // (1024 * 1024)
    except Exception:
        return -1


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    _INSECURE_DEFAULT = "your-secret-key-change-in-production"
    if not settings.DEBUG and settings.JWT_SECRET_KEY == _INSECURE_DEFAULT:
        raise RuntimeError(
            "JWT_SECRET_KEY is still the insecure default value. "
            "Set a strong secret in your environment before running in production."
        )

    print(f"[STARTUP] MEM at import: {_mem_mb()} MB")
    await create_tables()
    print(f"[STARTUP] MEM after create_tables: {_mem_mb()} MB")

    # Check Ollama health
    ai_service = AIService()
    if await ai_service.check_health():
        print(f"Connected to Ollama at {settings.OLLAMA_BASE_URL}")
    else:
        print(f"Warning: Could not connect to Ollama at {settings.OLLAMA_BASE_URL}")
    print(f"[STARTUP] MEM after ollama health: {_mem_mb()} MB")

    # Check Router model health
    router_service = RouterService()
    router_label = router_service._llm.provider_label
    if await router_service.health_check():
        print(f"Router provider ({router_label}) available")
    else:
        print(f"Warning: Router provider ({router_label}) not available - using fallback")
    print(f"[STARTUP] MEM after router health: {_mem_mb()} MB")

    # Check Embedding model health and warm it up (loads bge-m3 into VRAM now
    # so the first document upload doesn't wait for model cold-start).
    embedding_service = EmbeddingService()
    print(f"Loading embedding model {settings.OLLAMA_EMBEDDING_MODEL} (may take 1-3 min on cold start)...")
    if await embedding_service.health_check():
        print(f"Embedding model ({settings.OLLAMA_EMBEDDING_MODEL}) loaded and ready for RAG")
    else:
        print(f"Warning: Embedding model ({settings.OLLAMA_EMBEDDING_MODEL}) not available")
        print(f"         Pull it with: ollama pull {settings.OLLAMA_EMBEDDING_MODEL}")
    print(f"[STARTUP] MEM after embedding warmup: {_mem_mb()} MB")

    yield

    # Shutdown
    pass


from app.limiter import limiter  # noqa: E402 (after sys.path setup)

app = FastAPI(
    title=settings.APP_NAME,
    description="AI Chatbot API powered by Ollama",
    version="1.0.0",
    lifespan=lifespan,
)

# Attach limiter so @limiter.limit() decorators on routers can find it.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security headers — applied to every response from FastAPI.
# nginx adds its own copy for nginx-generated errors (4xx/5xx from the proxy
# layer itself); the two sets complement each other.
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; img-src 'self'; frame-ancestors 'none'"
    )
    if not settings.DEBUG:
        # Only send HSTS over a confirmed HTTPS connection.
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# Global exception handler to log errors
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_trace = traceback.format_exc()
    print(f"\n{'='*50}")
    print(f"ERROR in {request.method} {request.url}")
    print(f"{'='*50}")
    print(error_trace)
    print(f"{'='*50}\n")
    body: dict = {"detail": "Internal server error"}
    if settings.DEBUG:
        body["traceback"] = error_trace
    return JSONResponse(status_code=500, content=body)

# Include routers
app.include_router(auth_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(messages_router, prefix="/api")
app.include_router(uploads_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(graph_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(folders_router, prefix="/api")
app.include_router(rag_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Dependency-aware readiness probe.

    Gates on Postgres only: returns 503 when the database is unreachable so k8s
    readiness pulls the pod out of rotation. Ollama is reported for visibility but
    is NOT gated — it is a separately-warming service the app tolerates being down
    at startup, and flapping readiness on it would churn the pod.
    """
    import time

    from sqlalchemy import text

    from app.database import async_session_maker

    start = time.perf_counter()
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as exc:  # noqa: BLE001 — any failure means unhealthy
        db_status = f"unhealthy: {exc}"
    db_duration = f"{round((time.perf_counter() - start) * 1000, 2)}ms"

    try:
        ollama_healthy = await AIService().check_health()
    except Exception:  # noqa: BLE001 — informational only, never gates readiness
        ollama_healthy = False

    healthy = db_status == "healthy"
    payload = {
        "status": "healthy" if healthy else "unhealthy",
        "db": {"status": db_status, "duration": db_duration},
        "ollama": "connected" if ollama_healthy else "disconnected",
    }
    return JSONResponse(status_code=200 if healthy else 503, content=payload)


if settings.DEBUG:
    @app.get("/debug/db")
    async def debug_db():
        from app.database import async_session_maker
        from sqlalchemy import text
        try:
            async with async_session_maker() as session:
                await session.execute(text("SELECT 1"))
                tables_result = await session.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
                tables = [row[0] for row in tables_result.fetchall()]
                return {"database": "connected", "tables": tables}
        except Exception as e:
            return {"database": "error", "detail": str(e)}

    @app.get("/debug/pdf/{attachment_id}")
    async def debug_pdf_extraction(attachment_id: int):
        from app.database import async_session_maker
        from sqlalchemy import select
        from app.models.attachment import Attachment
        from app.services.document import DocumentService
        from pathlib import Path
        result_info: dict = {
            "attachment_id": attachment_id,
            "pymupdf_installed": False,
            "pypdf_installed": False,
        }
        try:
            import fitz
            result_info["pymupdf_installed"] = True
            result_info["pymupdf_version"] = fitz.version
        except ImportError as e:
            result_info["pymupdf_error"] = str(e)
        try:
            from pypdf import PdfReader  # noqa: F401
            result_info["pypdf_installed"] = True
        except ImportError:
            pass
        try:
            async with async_session_maker() as session:
                db_result = await session.execute(select(Attachment).where(Attachment.id == attachment_id))
                attachment = db_result.scalar_one_or_none()
                if attachment:
                    path = Path(attachment.file_path)
                    result_info.update({
                        "attachment_found": True,
                        "content_type": attachment.content_type,
                        "original_filename": attachment.original_filename,
                        "file_exists": path.exists(),
                    })
                    if path.exists():
                        result_info["file_size_on_disk"] = path.stat().st_size
                        text = await DocumentService().extract_text(attachment.file_path)
                        result_info["extraction_result"] = (
                            f"SUCCESS: {len(text)} characters" if text else "FAILED: No text extracted"
                        )
                else:
                    result_info["error"] = "Attachment not found"
        except Exception as e:
            result_info["error"] = str(e)
        return result_info

    @app.get("/debug/attachments")
    async def debug_list_attachments():
        from app.database import async_session_maker
        from sqlalchemy import select
        from app.models.attachment import Attachment
        from pathlib import Path
        try:
            async with async_session_maker() as session:
                db_result = await session.execute(select(Attachment).order_by(Attachment.created_at.desc()))
                attachments = db_result.scalars().all()
                return [
                    {
                        "id": att.id,
                        "original_filename": att.original_filename,
                        "content_type": att.content_type,
                        "file_exists": Path(att.file_path).exists(),
                        "message_id": att.message_id,
                    }
                    for att in attachments
                ]
        except Exception as e:
            return {"error": str(e)}
