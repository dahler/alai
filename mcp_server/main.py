"""
ALAI MCP Server — exposes the RAG knowledge base as a Claude.ai tool.

Transport: SSE (required for Claude.ai remote MCP integrations)
  GET  /sse      — Claude.ai connects here
  POST /messages — session message exchange

Environment variables:
  RAG_URL     — REST endpoint (default: http://backend:8000/api/rag/query)
  RAG_API_KEY — shared secret, must match the backend's RAG_API_KEY
  PORT        — listen port (default: 8001)
"""

import os
import httpx
import uvicorn

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

RAG_URL = os.getenv("RAG_URL", "http://backend:8000/api/rag/query")
RAG_API_KEY = os.getenv("RAG_API_KEY", "")
PORT = int(os.getenv("PORT", "8001"))

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = Server("alai-rag")


@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_documents",
            description=(
                "Search the company knowledge base for relevant information. "
                "Returns ranked document chunks with source, section heading, "
                "and page references. Use this whenever the user asks about "
                "company policies, regulations, procedures, or internal docs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language search query",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": (
                            "Number of results to return (1-20, default 5)"
                        ),
                        "default": 5,
                    },
                    "source_filter": {
                        "type": "string",
                        "description": (
                            "Optional: restrict results to documents whose "
                            "filename contains this string"
                        ),
                    },
                },
                "required": ["query"],
            },
        )
    ]


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "search_documents":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    query = arguments.get("query", "")
    top_k = min(int(arguments.get("top_k", 5)), 20)
    source_filter = arguments.get("source_filter")

    payload: dict = {"query": query, "top_k": top_k}
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
        return [TextContent(
            type="text",
            text=f"RAG error {e.response.status_code}: {e.response.text}",
        )]
    except Exception as e:
        return [TextContent(type="text", text=f"RAG error: {e}")]

    results = data.get("results", [])
    if not results:
        return [TextContent(type="text", text="No relevant documents found.")]

    parts: list[str] = []
    for r in results:
        header = f"[{r['rank']}] {r['document']}"
        if r.get("heading"):
            header += f" — {r['heading']}"
        if r.get("pages"):
            header += f" (p. {r['pages']})"
        header += f"  [relevance: {r.get('relevance_score', 0):.0%}]"
        parts.append(f"{header}\n{r['content']}")

    return [TextContent(type="text", text="\n\n---\n\n".join(parts))]


# ── SSE transport (required for Claude.ai) ───────────────────────────────────

sse = SseServerTransport("/mcp/messages")


async def handle_sse(request: Request) -> None:
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp.run(
            streams[0], streams[1], mcp.create_initialization_options()
        )


async def handle_messages(request: Request) -> None:
    await sse.handle_post_message(
        request.scope, request.receive, request._send
    )


app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Route("/messages", endpoint=handle_messages, methods=["POST"]),
    ]
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
