"""
RouterService: classifies every user message before it enters the pipeline.

Uses SmartLLM (Claude -> OpenAI -> Ollama) for ALL routing decisions.
No keyword lists, no regex heuristics — pure language-model understanding.

Only hard-coded bypass: has_images=True -> VISION_ANALYSIS (100% certain).
"""

import json
import re
import time
import logging

from app.router.constants import RouterAction, RouterResult
from app.services.smart_llm import SmartLLM

logger = logging.getLogger(__name__)


def log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [ROUTER] {message}")


_SYSTEM = (
    "You are a request router for an enterprise AI assistant. "
    "Respond ONLY with a valid JSON object — no markdown, no explanation."
)

_PROMPT = """\
Classify the user request into exactly one action.

Actions:
  direct_answer   - factual question, definition, explanation, coding help;
                    general knowledge only, no live or external data needed
  rag_search      - question about internal company matters: SOPs, policies,
                    procedures, roles, responsibilities, workflows, products,
                    or any topic likely covered in the user's uploaded documents
  agentic         - ONLY when the request explicitly requires one of:
                    * live/current external data (prices, exchange rates,
                      weather, stock quotes, news, economic indicators)
                    * creating/generating a file to download (Excel, Word,
                      PDF, PowerPoint, laporan, dokumen, presentasi)
                    * email tasks (read inbox, send email, reply to email)
                    * any output the user wants to save or download
  vision_analysis - user attached an image and wants it analysed

Key rules (follow exactly):
1. "generate/create/make/buat + report/Excel/Word/PDF/PowerPoint"
   -> ALWAYS agentic
2. "latest/current/today/terbaru/sekarang + rate/price/news/kurs"
   -> ALWAYS agentic
3. If "User has a knowledge base: true":
   - WHO is responsible / siapa yang bertanggung jawab -> rag_search
   - HOW does process X work / bagaimana proses X -> rag_search
   - WHAT is the SOP / procedure / policy -> rag_search
   - Any question about an internal company, its website, its products,
     its teams, or its operations -> rag_search
   - Mentioning a company name or website URL is NOT a reason for agentic
4. If "User has a knowledge base: true" and unsure -> prefer rag_search
5. If "User has a knowledge base: false" and unsure -> prefer agentic
6. "what is X / explain Y / how does Z work" with no live-data need
   AND knowledge base is false -> direct_answer

Request: {query}
Has file attachments : {has_attachments}
Has image attachments: {has_images}
User has a knowledge base: {has_knowledge_base}

Return JSON:
{{"action": "<action>", "confidence": <0.0-1.0>, "reason": "<one sentence>"}}

JSON:"""


class RouterService:
    """
    Classifies user requests using SmartLLM.
    Provider cascade: Claude -> OpenAI -> Ollama -> safe default.
    """

    def __init__(self) -> None:
        self._llm = SmartLLM(timeout=30.0)

    async def classify(
        self,
        query: str,
        has_attachments: bool = False,
        has_images: bool = False,
        has_knowledge_base: bool = False,
    ) -> RouterResult:
        start = time.time()
        log("=" * 50)
        log(f"CLASSIFYING  [{self._llm.provider_label}]")
        log(f"Query: {query[:100]}{'...' if len(query) > 100 else ''}")
        log(
            f"attachments={has_attachments} "
            f"images={has_images} "
            f"kb={has_knowledge_base}"
        )

        # Only hard-coded rule: image attached -> vision (always certain)
        if has_images:
            log("VISION (image attached)")
            log("=" * 50)
            return RouterResult(
                action=RouterAction.VISION_ANALYSIS,
                confidence=0.99,
                reason="image_attached",
            )

        # LLM classification
        prompt = _PROMPT.format(
            query=query[:600],
            has_attachments=str(has_attachments).lower(),
            has_images=str(has_images).lower(),
            has_knowledge_base=str(has_knowledge_base).lower(),
        )

        try:
            raw = await self._llm.complete(prompt, _SYSTEM)
            result = self._parse(raw)

            # Safety override: when user has a knowledge base, only allow
            # agentic if the model is very confident (≥0.85). Otherwise
            # prefer rag_search — it's safer to search internal docs than
            # accidentally hitting the web for an internal policy question.
            if (
                has_knowledge_base
                and result.action == RouterAction.AGENTIC
                and result.confidence < 0.85
            ):
                log(
                    f"Override: agentic({result.confidence:.0%}) → "
                    "rag_search (kb present, low confidence)"
                )
                result = RouterResult(
                    action=RouterAction.RAG_SEARCH,
                    confidence=result.confidence,
                    reason="kb_safety_override",
                )

            elapsed = (time.time() - start) * 1000
            log(
                f"action={result.action.value} "
                f"confidence={result.confidence:.0%} "
                f"reason={result.reason}"
            )
            log(f"Time: {elapsed:.0f}ms")
            log("=" * 50)
            return result

        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            log(f"Classification error ({exc}) -- defaulting to rag_search")
            log(f"Time: {elapsed:.0f}ms")
            log("=" * 50)
            # When knowledge base exists, default to rag_search not agentic
            return RouterResult(
                action=(
                    RouterAction.RAG_SEARCH
                    if has_knowledge_base
                    else RouterAction.AGENTIC
                ),
                confidence=0.5,
                reason="classification_error_fallback",
            )

    def _parse(self, raw: str) -> RouterResult:
        cleaned = raw.strip()

        try:
            return self._from_dict(json.loads(cleaned))
        except (json.JSONDecodeError, ValueError):
            pass

        m = re.search(r'\{[^{}]+\}', cleaned, re.DOTALL)
        if m:
            try:
                return self._from_dict(json.loads(m.group()))
            except (json.JSONDecodeError, ValueError):
                pass

        lower = cleaned.lower()
        for action in RouterAction:
            if action.value in lower:
                return RouterResult(
                    action=action,
                    confidence=0.55,
                    reason="text_extracted",
                )

        log(f"Could not parse LLM response: {cleaned[:80]}")
        return RouterResult(
            action=RouterAction.AGENTIC,
            confidence=0.5,
            reason="parse_failed_fallback",
        )

    def _from_dict(self, d: dict) -> RouterResult:
        action_str = str(d.get("action", "")).lower().strip()
        try:
            action = RouterAction(action_str)
        except ValueError:
            action = next(
                (
                    a for a in RouterAction
                    if a.value in action_str or action_str in a.value
                ),
                RouterAction.AGENTIC,
            )

        if action == RouterAction.EXTERNAL_API:
            action = RouterAction.AGENTIC

        confidence = float(d.get("confidence", 0.8))
        confidence = max(0.0, min(1.0, confidence))
        reason = str(d.get("reason", ""))
        return RouterResult(
            action=action,
            confidence=confidence,
            reason=reason,
        )

    async def detect_and_translate(self, query: str) -> tuple[str, str]:
        """
        Detect language and return (lang_code, query_for_routing).

        Claude/OpenAI understand multilingual natively, so we pass the
        original text unchanged to classify().  For Ollama we still
        translate so the smaller model routes correctly.
        """
        # Rule-based detection (fast, no LLM)
        _ID_MARKERS = {
            "yang", "dan", "di", "ke", "dari", "dengan", "untuk", "pada",
            "ini", "itu", "saya", "anda", "kamu", "ada", "tidak", "bisa",
            "akan", "sudah", "harga", "cari", "apa", "bagaimana", "berapa",
            "apakah", "adalah", "atau", "jika", "saat", "sekarang",
            "terbaru", "berita", "kurs",
        }
        words = set(query.lower().split())
        is_indonesian = len(words & _ID_MARKERS) >= 2

        if not is_indonesian:
            return "en", query

        # Cloud LLMs understand Indonesian natively — no translation needed
        if self._llm.provider in ("claude", "openai"):
            return "id", query

        # Ollama fallback: translate so smaller model routes correctly
        prompt = (
            f"Translate this to English. "
            f"Output only the English translation, nothing else."
            f"\n\n{query[:300]}"
        )
        try:
            translated = await self._llm.complete(prompt)
            translated = translated.strip()
            if translated:
                log(f"Translated [id] -> en: {translated[:80]}")
                return "id", translated
        except Exception as exc:
            log(f"Translation failed ({exc}), using original")

        return "id", query

    async def health_check(self) -> bool:
        if self._llm.provider in ("claude", "openai"):
            return True
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{self._llm._ollama_url}/api/tags"
                )
                return r.status_code == 200
        except Exception:
            return False
