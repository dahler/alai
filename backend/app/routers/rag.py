"""
Public RAG query endpoint for tool-use integration (Claude API, MCP, etc.).

Authentication: Bearer token — configure RAG_API_KEY in the environment.
Only company-scoped documents are searched; no user session is required.

Tool definition to pass to the Claude API:
  {
    "name": "search_documents",
    "description": "Search the company knowledge base for relevant information.",
    "input_schema": {
      "type": "object",
      "properties": {
        "query":       {"type": "string",  "description": "Natural-language search query"},
        "top_k":       {"type": "integer", "description": "Results to return (1-20, default 5)"},
        "source_filter": {"type": "string", "description": "Optional filename substring filter"}
      },
      "required": ["query"]
    }
  }

Call: POST https://<host>/api/rag/query
      Authorization: Bearer <RAG_API_KEY>
      Content-Type: application/json
      {"query": "...", "top_k": 5}
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services.rag import RAGService

router = APIRouter(prefix="/rag", tags=["rag"])

_bearer = HTTPBearer(auto_error=False)


async def _require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    if not settings.RAG_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG_API_KEY is not configured on this server",
        )
    if not credentials or credentials.credentials != settings.RAG_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Request / Response schemas ────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., description="Natural-language search query")
    top_k: int = Field(5, ge=1, le=20, description="Number of results to return (1–20)")
    source_filter: Optional[str] = Field(
        None,
        description="Restrict to documents whose filename contains this string",
    )


class ResultItem(BaseModel):
    rank: int
    document: str
    heading: Optional[str] = None
    pages: Optional[str] = None
    content: str
    relevance_score: float


class QueryResponse(BaseModel):
    query: str
    total: int
    results: list[ResultItem]


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/query",
    response_model=QueryResponse,
    dependencies=[Depends(_require_api_key)],
    summary="Search the company knowledge base",
    description=(
        "Returns the top-K most relevant document chunks for a natural-language query. "
        "Only company-scoped documents are searched. "
        "Authenticate with `Authorization: Bearer <RAG_API_KEY>`."
    ),
)
async def query_rag(
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    rag = RAGService(db)
    # user_id=None → company-only access (no user-private documents)
    raw = await rag.search(
        query=body.query,
        user_id=None,
        top_k=body.top_k,
        source_filter=body.source_filter,
    )

    results: list[ResultItem] = []
    for i, chunk in enumerate(raw, start=1):
        page_start = chunk.get("page_start")
        page_end = chunk.get("page_end")
        if page_start is not None and page_end is not None:
            pages = (
                f"{page_start}–{page_end}"
                if page_start != page_end
                else str(page_start)
            )
        elif page_start is not None:
            pages = str(page_start)
        else:
            pages = None

        results.append(ResultItem(
            rank=i,
            document=chunk.get("filename", "Unknown"),
            heading=chunk.get("heading_context") or None,
            pages=pages,
            content=chunk.get("chunk_text", ""),
            relevance_score=chunk.get("similarity", 0.0),
        ))

    return QueryResponse(query=body.query, total=len(results), results=results)
