"""
Summarization service.

Generates document-level and section-level summaries using the
configured Ollama LLM.
"""

from typing import Optional

import httpx

from app.config import settings


def log(message: str) -> None:
    pass


_DOCUMENT_PROMPT = """\
Summarize the following document in 3-5 sentences.
Cover: (1) Purpose, (2) Scope, (3) Main topics.
Reply with plain text only — no bullet points, no markdown.

Document title: {title}

Content:
{content}
"""

_SECTION_PROMPT = """\
Summarize the following document section in 1-3 sentences.
Reply with plain text only.

Document: {doc_title}
Section: {section_title}

Content:
{content}
"""


class SummarizationService:
    """LLM-based summary generation via Ollama."""

    def __init__(self) -> None:
        self.base_url = settings.OLLAMA_BASE_URL
        # Prefer the router/small model for summaries to keep it fast
        self.model = settings.OLLAMA_ROUTER_MODEL or settings.OLLAMA_TEXT_MODEL

    async def summarize_document(
        self,
        title: str,
        content: str,
        max_content_chars: int = 6000,
    ) -> Optional[str]:
        """Generate a document-level summary (purpose, scope, topics)."""
        snippet = content[:max_content_chars]
        prompt = _DOCUMENT_PROMPT.format(title=title, content=snippet)
        return await self._generate(prompt)

    async def summarize_section(
        self,
        doc_title: str,
        section_title: str,
        content: str,
        max_content_chars: int = 2000,
    ) -> Optional[str]:
        """Generate a one-to-three sentence section summary."""
        if not content.strip():
            return None
        snippet = content[:max_content_chars]
        prompt = _SECTION_PROMPT.format(
            doc_title=doc_title,
            section_title=section_title,
            content=snippet,
        )
        return await self._generate(prompt)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _generate(self, prompt: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 256},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = (data.get("response") or "").strip()
                return text if text else None
        except Exception as exc:
            log(f"✗ Generation error: {exc}")
            return None
