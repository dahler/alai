from contextlib import asynccontextmanager
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import create_tables
# Import models to register them with Base.metadata before create_tables()
from app.models import User, Conversation, Message, OAuthAccount, Attachment, DocumentChunk, Entity, EntityRelationship, DocumentEntity  # noqa: F401
from app.routers import auth_router, conversations_router, messages_router, uploads_router, documents_router, graph_router, agent_router, ai_router
from app.services.ai import AIService
from app.services.embedding import EmbeddingService
from app.router.service import RouterService


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await create_tables()

    # Check Ollama health
    ai_service = AIService()
    if await ai_service.check_health():
        print(f"Connected to Ollama at {settings.OLLAMA_BASE_URL}")
    else:
        print(f"Warning: Could not connect to Ollama at {settings.OLLAMA_BASE_URL}")

    # Check Router model health
    router_service = RouterService()
    if await router_service.health_check():
        print(f"Router model ({router_service.model}) available")
    else:
        print(f"Warning: Router model ({router_service.model}) not available - using fallback")

    # Check Embedding model health
    embedding_service = EmbeddingService()
    if await embedding_service.health_check():
        print(f"Embedding model ({settings.OLLAMA_EMBEDDING_MODEL}) available for RAG")
    else:
        print(f"Warning: Embedding model ({settings.OLLAMA_EMBEDDING_MODEL}) not available")
        print(f"         Pull it with: ollama pull {settings.OLLAMA_EMBEDDING_MODEL}")

    yield

    # Shutdown
    pass


app = FastAPI(
    title=settings.APP_NAME,
    description="AI Chatbot API powered by Ollama",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler to log errors
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_trace = traceback.format_exc()
    print(f"\n{'='*50}")
    print(f"ERROR in {request.method} {request.url}")
    print(f"{'='*50}")
    print(error_trace)
    print(f"{'='*50}\n")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "traceback": error_trace}
    )

# Include routers
app.include_router(auth_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(messages_router, prefix="/api")
app.include_router(uploads_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(graph_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(ai_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    ai_service = AIService()
    ollama_healthy = await ai_service.check_health()

    return {
        "status": "healthy",
        "ollama": "connected" if ollama_healthy else "disconnected",
    }


@app.get("/debug/db")
async def debug_db():
    """Debug endpoint to test database connectivity"""
    from app.database import async_session_maker
    from sqlalchemy import text

    try:
        async with async_session_maker() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar()

            # Check if tables exist
            tables_result = await session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            tables = [row[0] for row in tables_result.fetchall()]

            return {"database": "connected", "tables": tables}
    except Exception as e:
        import traceback
        return {"database": "error", "detail": str(e), "traceback": traceback.format_exc()}


@app.get("/debug/pdf/{attachment_id}")
async def debug_pdf_extraction(attachment_id: int):
    """Debug endpoint to test PDF extraction for a specific attachment"""
    from app.database import async_session_maker
    from sqlalchemy import select
    from app.models.attachment import Attachment
    from app.services.document import DocumentService
    from pathlib import Path

    result_info = {
        "attachment_id": attachment_id,
        "pymupdf_installed": False,
        "pypdf_installed": False,
        "attachment_found": False,
        "file_exists": False,
        "file_path": None,
        "content_type": None,
        "extraction_result": None,
        "error": None,
    }

    # Check if PyMuPDF is installed
    try:
        import fitz
        result_info["pymupdf_installed"] = True
        result_info["pymupdf_version"] = fitz.version
    except ImportError as e:
        result_info["pymupdf_error"] = str(e)

    # Check if pypdf is installed
    try:
        from pypdf import PdfReader
        result_info["pypdf_installed"] = True
    except ImportError:
        pass

    # Get attachment from database
    try:
        async with async_session_maker() as session:
            query = select(Attachment).where(Attachment.id == attachment_id)
            db_result = await session.execute(query)
            attachment = db_result.scalar_one_or_none()

            if attachment:
                result_info["attachment_found"] = True
                result_info["file_path"] = attachment.file_path
                result_info["content_type"] = attachment.content_type
                result_info["original_filename"] = attachment.original_filename

                # Check if file exists
                path = Path(attachment.file_path)
                result_info["file_exists"] = path.exists()
                result_info["path_absolute"] = str(path.absolute())

                if path.exists():
                    result_info["file_size_on_disk"] = path.stat().st_size

                    # Try extraction
                    doc_service = DocumentService()
                    text = await doc_service.extract_text(attachment.file_path)
                    if text:
                        result_info["extraction_result"] = f"SUCCESS: {len(text)} characters extracted"
                        result_info["preview"] = text[:500] + "..." if len(text) > 500 else text
                    else:
                        result_info["extraction_result"] = "FAILED: No text extracted"
            else:
                result_info["error"] = "Attachment not found in database"

    except Exception as e:
        import traceback
        result_info["error"] = str(e)
        result_info["traceback"] = traceback.format_exc()

    return result_info


@app.get("/debug/attachments")
async def debug_list_attachments():
    """List all attachments for debugging"""
    from app.database import async_session_maker
    from sqlalchemy import select
    from app.models.attachment import Attachment
    from pathlib import Path

    try:
        async with async_session_maker() as session:
            query = select(Attachment).order_by(Attachment.created_at.desc())
            db_result = await session.execute(query)
            attachments = db_result.scalars().all()

            return [
                {
                    "id": att.id,
                    "original_filename": att.original_filename,
                    "content_type": att.content_type,
                    "file_path": att.file_path,
                    "file_exists": Path(att.file_path).exists(),
                    "message_id": att.message_id,
                }
                for att in attachments
            ]
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
