"""
ALAI MCP Server — exposes the RAG knowledge base as a Claude.ai tool.

Transport: SSE (required for Claude.ai remote MCP integrations)
  GET  /sse       — Claude.ai connects here
  POST /messages/ — session message exchange

Public URL: https://mcp-alai.antaragpt.com/sse

Environment variables:
  RAG_URL     — REST endpoint (default: http://backend:8000/api/rag/query)
  RAG_API_KEY — shared secret, must match the backend's RAG_API_KEY
  PORT        — listen port (default: 8001)
"""

import asyncio
import os

import httpx
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

RAG_URL = os.getenv("RAG_URL", "http://backend:8000/api/rag/query")
RAG_API_KEY = os.getenv("RAG_API_KEY", "")
PORT = int(os.getenv("PORT", "8001"))

mcp = MCPServer("alai-rag")


@mcp.custom_route("/", methods=["GET"])
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "alai-mcp"})


@mcp.tool()
async def search_documents(
    query: str,
    top_k: int = 5,
    source_filter: str | None = None,
) -> str:
    """Search the company knowledge base for relevant information.

    Returns ranked document chunks with source, section heading, and page
    references. Use this whenever the user asks about company policies,
    regulations, procedures, or any topic covered in internal documents.

    Args:
        query: Natural-language search query.
        top_k: Number of results to return (1-20, default 5).
        source_filter: Optional filename substring to restrict results.
    """
    payload: dict = {"query": query, "top_k": min(top_k, 20)}
    if source_filter:
        payload["source_filter"] = source_filter

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                RAG_URL,
                headers={
                    "Authorization": f"Bearer {RAG_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return (
            f"RAG error {e.response.status_code}: {e.response.text}"
        )
    except Exception as e:
        return f"RAG error: {e}"

    results = data.get("results", [])
    if not results:
        return "No relevant documents found."

    parts: list[str] = []
    for r in results:
        header = f"[{r['rank']}] {r['document']}"
        if r.get("heading"):
            header += f" — {r['heading']}"
        if r.get("pages"):
            header += f" (p. {r['pages']})"
        header += f"  [relevance: {r.get('relevance_score', 0):.0%}]"
        parts.append(f"{header}\n{r['content']}")

    return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    asyncio.run(mcp.run_sse_async(
        host="0.0.0.0",
        port=PORT,
        sse_path="/sse",
        message_path="/messages/",
    ))
