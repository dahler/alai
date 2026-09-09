#!/usr/bin/env python3
"""
Interactive Claude + RAG test script.

Runs a conversation where Claude can call your local RAG endpoint as a tool.

Setup:
  1. Start the backend: cd backend && venv/Scripts/python -m uvicorn app.main:app --reload
  2. Set env vars:
       $env:ANTHROPIC_API_KEY = "sk-ant-..."
       $env:RAG_API_KEY       = "your-rag-key"   # must match RAG_API_KEY in .env
  3. Run: backend/venv/Scripts/python test_rag_claude.py

Optional env vars:
  RAG_URL   — defaults to http://localhost:8000/api/rag/query
  RAG_TOP_K — default number of chunks to fetch (default 5)
  MODEL     — Claude model to use (default claude-sonnet-4-6)
"""

import os
import sys

import httpx
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

RAG_URL    = os.getenv("RAG_URL",    "http://localhost:8000/api/rag/query")
RAG_API_KEY = os.getenv("RAG_API_KEY", "")
RAG_TOP_K  = int(os.getenv("RAG_TOP_K", "5"))
MODEL      = os.getenv("MODEL",      "claude-sonnet-4-6")

# ── Tool definition ───────────────────────────────────────────────────────────

SEARCH_TOOL = {
    "name": "search_documents",
    "description": (
        "Search the company knowledge base for relevant information. "
        "Use this whenever the user asks about company policies, regulations, "
        "procedures, or any topic that may be covered in internal documents."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query",
            },
            "top_k": {
                "type": "integer",
                "description": f"Number of results to return (1–20, default {RAG_TOP_K})",
            },
            "source_filter": {
                "type": "string",
                "description": "Optional: restrict results to documents whose filename contains this string",
            },
        },
        "required": ["query"],
    },
}

# ── RAG caller ────────────────────────────────────────────────────────────────

def call_rag(query: str, top_k: int = RAG_TOP_K, source_filter: str | None = None) -> str:
    """Call the local RAG endpoint and return formatted plain-text results."""
    payload: dict = {"query": query, "top_k": top_k}
    if source_filter:
        payload["source_filter"] = source_filter

    try:
        resp = httpx.post(
            RAG_URL,
            headers={
                "Authorization": f"Bearer {RAG_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        return f"RAG error {e.response.status_code}: {e.response.text}"
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
        score = r.get("relevance_score", 0)
        header += f"  [score: {score:.0%}]"
        parts.append(f"{header}\n{r['content']}")

    return "\n\n---\n\n".join(parts)

# ── Claude tool-use loop ───────────────────────────────────────────────────────

def run_turn(client: anthropic.Anthropic, messages: list) -> str:
    """
    Send messages to Claude, handle any tool calls, and return the final reply.
    Loops until stop_reason == 'end_turn'.
    """
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            tools=[SEARCH_TOOL],
            messages=messages,
        )

        text_blocks = [b for b in response.content if b.type == "text"]
        tool_blocks = [b for b in response.content if b.type == "tool_use"]

        if response.stop_reason == "end_turn" or not tool_blocks:
            return "".join(b.text for b in text_blocks)

        # Append Claude's response (may include text + tool_use blocks)
        messages.append({"role": "assistant", "content": response.content})

        # Execute each tool call and collect results
        tool_results = []
        for tc in tool_blocks:
            args = tc.input
            query = args.get("query", "")
            top_k = args.get("top_k", RAG_TOP_K)
            source_filter = args.get("source_filter")

            print(f"\n  [tool] search_documents(query={query!r}, top_k={top_k})", flush=True)
            result_text = call_rag(query=query, top_k=top_k, source_filter=source_filter)
            chunk_count = result_text.count("\n\n---\n\n") + 1 if result_text else 0
            print(f"  [tool] → {chunk_count} chunk(s) returned", flush=True)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_results})

# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)
    if not RAG_API_KEY:
        print("Warning: RAG_API_KEY not set — the endpoint will return 503.")

    client = anthropic.Anthropic(api_key=api_key)
    messages: list = []

    print(f"Claude RAG test")
    print(f"  Model      : {MODEL}")
    print(f"  RAG URL    : {RAG_URL}")
    print(f"  Default K  : {RAG_TOP_K}")
    print("Type your question, or 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break

        messages.append({"role": "user", "content": user_input})

        try:
            answer = run_turn(client, messages)
        except anthropic.APIError as e:
            print(f"Anthropic API error: {e}")
            messages.pop()  # remove the user message so the loop stays consistent
            continue

        messages.append({"role": "assistant", "content": answer})
        print(f"\nClaude: {answer}\n")


if __name__ == "__main__":
    main()
