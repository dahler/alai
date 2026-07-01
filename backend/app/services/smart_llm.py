"""
SmartLLM — provider-agnostic LLM client for planning/classification tasks.

Priority order (set in .env):
  1. Anthropic Claude  (ANTHROPIC_API_KEY=sk-ant-...)  ← best reasoning
  2. OpenAI GPT        (OPENAI_API_KEY=sk-...)
  3. Ollama agent model  (always available, free)

Usage:
    llm = SmartLLM()
    result = await llm.complete("Classify this request: ...")
"""

from __future__ import annotations

import httpx
from app.config import settings


class SmartLLM:
    """
    Standalone smart LLM client.  No dependency on AIService — works anywhere.
    """

    def __init__(
        self,
        ollama_model: str | None = None,
        timeout: float = 60.0,
    ):
        self._anthropic_key: str = getattr(settings, "ANTHROPIC_API_KEY", "")
        self._openai_key: str    = getattr(settings, "OPENAI_API_KEY", "")
        self._ollama_url: str    = settings.OLLAMA_BASE_URL
        self._ollama_model: str  = ollama_model or settings.OLLAMA_AGENT_MODEL
        self._timeout            = timeout

    @property
    def provider(self) -> str:
        if self._anthropic_key:
            return "claude"
        if self._openai_key:
            return "openai"
        return "ollama"

    @property
    def provider_label(self) -> str:
        return {"claude": "Claude", "openai": "OpenAI", "ollama": "Ollama"}[self.provider]

    async def complete(
        self, prompt: str, system: str = "", max_tokens: int = 2048
    ) -> str:
        """
        Send a prompt and return the text response.
        Automatically selects the best available provider.
        """
        if self._anthropic_key:
            return await self._anthropic(prompt, system, max_tokens)
        if self._openai_key:
            return await self._openai(prompt, system, max_tokens)
        return await self._ollama(prompt, system)

    # ── Providers ─────────────────────────────────────────────────────────────

    async def _anthropic(self, prompt: str, system: str, max_tokens: int = 2048) -> str:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self._anthropic_key)
            kwargs = {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system
            msg = await client.messages.create(**kwargs)
            return msg.content[0].text
        except Exception:
            return await self._ollama(prompt, system)

    async def _openai(self, prompt: str, system: str, max_tokens: int = 2048) -> str:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self._openai_key)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = await client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=messages,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception:
            return await self._ollama(prompt, system)

    async def _ollama(self, prompt: str, system: str) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._ollama_url}/api/chat",
                json={
                    "model": self._ollama_model,
                    "messages": messages,
                    "stream": False,
                    # Match ollama.py's 8k window so a model shared across
                    # code paths keeps one KV-cache size and isn't reloaded
                    # (fix #3). keep_alive omitted → OLLAMA_KEEP_ALIVE (#4).
                    "options": {"temperature": 0.1, "num_ctx": 8192},
                },
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
