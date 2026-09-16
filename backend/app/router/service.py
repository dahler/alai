"""
RouterService: classifies every user message before it enters the pipeline.

Uses SmartLLM (Claude -> OpenAI -> Ollama) for ALL routing decisions.
Recent conversation history is injected into the prompt so the LLM can
detect intent continuity (e.g. ongoing editing session) and topic switches
(e.g. user switches from editing to asking an SOP question).

Only hard-coded bypasses:
  - has_images=True        -> VISION_ANALYSIS  (certain)
  - clear edit prefix      -> DIRECT_ANSWER    (certain, saves latency)
  - one-word greetings     -> DIRECT_ANSWER    (certain, saves latency)
"""

import json
import re
import time
import logging

from app.config import settings
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

# Unambiguous edit prefixes — bypass LLM for speed
_EDIT_PREFIXES = (
    "fix ", "fix:", "correct ", "proofread ", "improve ",
    "rewrite ", "rephrase ", "translate ", "paraphrase ",
    "paraphrase:", "summarise ", "summarize ", "shorten ",
    "lengthen ", "make this ", "make it ", "check grammar",
    "perbaiki ", "terjemahkan ", "ringkas ", "ubah ke ",
    "tolong perbaiki", "in english please", "please translate",
    "please fix", "please correct", "please improve",
)

_PROMPT = """\
You are a request router. Pick exactly one action for the user request.

--- ACTIONS ---
direct_answer   General world knowledge, text editing/fixing/translation,
                or a continuation of an ongoing editing session.
rag_search      Search the internal company knowledge base (SOPs, policies,
                procedures, roles, approval thresholds, org structure).
agentic         Requires tools: live data (prices/rates/news/weather),
                file generation (Excel/Word/PDF/PPT), or email operations.

{context_block}\
--- CURRENT REQUEST ---
{query}

Has file attachments : {has_attachments}
Has image attachments: {has_images}
User has a knowledge base: {has_knowledge_base}

--- DECISION STEPS (follow in order) ---
1. Greeting or small talk? (hi, thanks, oke, selamat pagi...)
   YES -> direct_answer

2. Text-editing task, OR continuation of an editing session visible above?
   Editing keywords: fix, correct, proofread, improve, rewrite, rephrase,
     translate, summarise, paraphrase, perbaiki, terjemahkan, ringkas, etc.
   Continuation: if the recent conversation shows an editing session AND
     the current message is plain text with no new question or topic,
     treat it as more text to edit -> direct_answer.
   IMPORTANT: a new SOP/policy question, even after many editing turns,
     overrides editing context -> go to step 4.
   YES -> direct_answer

3. Explicit file generation or live external data needed right now?
   (buat laporan, create Excel, current USD rate, today's news, send email)
   YES -> agentic

4. Company-specific question that general knowledge cannot answer?
   (who approves, what is the SOP, berapa batas pengadaan, siapa PIC,
    bagaimana prosedur, what is the policy) — requires kb=true.
   YES -> rag_search

5. Everything else -> direct_answer

Reasoning first, then JSON:
{{"reasoning": "<one sentence>", \
"action": "<action>", "confidence": <0.0-1.0>}}
JSON:"""


def _build_context_block(recent_messages: list[dict] | None) -> str:
    """Format the last 4 messages into a readable context block."""
    if not recent_messages:
        return ""
    turns = []
    for m in recent_messages[-4:]:
        role = m.get("role", "")
        content = m.get("content", "")[:150].replace("\n", " ").strip()
        if role in ("user", "assistant") and content:
            label = "User" if role == "user" else "Assistant"
            turns.append(f"{label}: {content}")
    if not turns:
        return ""
    return "--- RECENT CONVERSATION ---\n" + "\n".join(turns) + "\n\n"


class RouterService:
    """
    Classifies user requests using SmartLLM.
    Provider cascade: Claude -> OpenAI -> Ollama -> safe default.
    """

    def __init__(self) -> None:
        self._llm = SmartLLM(
            ollama_model=settings.OLLAMA_ROUTER_MODEL, timeout=30.0
        )

    async def classify(
        self,
        query: str,
        has_attachments: bool = False,
        has_images: bool = False,
        has_knowledge_base: bool = False,
        recent_messages: list[dict] | None = None,
    ) -> RouterResult:
        start = time.time()
        log("=" * 50)
        log(f"CLASSIFYING  [{self._llm.provider_label}]")
        log(f"Query: {query[:100]}{'...' if len(query) > 100 else ''}")
        log(
            f"attachments={has_attachments} "
            f"images={has_images} "
            f"kb={has_knowledge_base} "
            f"ctx={len(recent_messages) if recent_messages else 0}msgs"
        )

        # Bypass 1: image -> vision (certain)
        if has_images:
            log("VISION (image attached)")
            log("=" * 50)
            return RouterResult(
                action=RouterAction.VISION_ANALYSIS,
                confidence=0.99,
                reason="image_attached",
            )

        # Bypass 2: unambiguous edit prefix -> direct, no LLM needed
        q_lower = query.strip().lower()
        if any(q_lower.startswith(p) for p in _EDIT_PREFIXES):
            log("DIRECT (text-editing bypass)")
            log("=" * 50)
            return RouterResult(
                action=RouterAction.DIRECT_ANSWER,
                confidence=0.99,
                reason="text_editing_bypass",
            )

        # Bypass 3: one-word greeting -> direct (certain)
        _GREETINGS = {
            "hi", "hello", "hey", "halo", "hai", "hei",
            "thanks", "thank you", "terima kasih", "makasih", "thx",
            "ok", "okay", "oke", "oks", "got it", "noted",
            "good morning", "good afternoon", "good evening",
            "selamat pagi", "selamat siang", "selamat sore",
            "selamat malam", "bye", "goodbye", "sampai jumpa", "dadah",
        }
        if q_lower.rstrip("!.,") in _GREETINGS:
            log("DIRECT (greeting bypass)")
            log("=" * 50)
            return RouterResult(
                action=RouterAction.DIRECT_ANSWER,
                confidence=0.99,
                reason="greeting_bypass",
            )

        # LLM classification with conversation context
        context_block = _build_context_block(recent_messages)
        prompt = _PROMPT.format(
            context_block=context_block,
            query=query[:500],
            has_attachments=str(has_attachments).lower(),
            has_images=str(has_images).lower(),
            has_knowledge_base=str(has_knowledge_base).lower(),
        )

        try:
            raw = await self._llm.complete(prompt, _SYSTEM)
            result = self._parse(raw)

            # Safety: KB present + low-confidence agentic -> rag_search
            if (
                has_knowledge_base
                and result.action == RouterAction.AGENTIC
                and result.confidence < 0.85
            ):
                log(
                    f"Override: agentic({result.confidence:.0%}) -> "
                    "rag_search (kb present, low confidence)"
                )
                result = RouterResult(
                    action=RouterAction.RAG_SEARCH,
                    confidence=result.confidence,
                    reason="kb_safety_override",
                )

            # Safety: attachment + low-confidence rag -> direct
            if (
                has_attachments
                and not has_images
                and result.action == RouterAction.RAG_SEARCH
                and result.confidence < 0.88
            ):
                log(
                    f"Override: rag_search({result.confidence:.0%}) -> "
                    "direct_answer (attachment, low confidence)"
                )
                result = RouterResult(
                    action=RouterAction.DIRECT_ANSWER,
                    confidence=result.confidence,
                    reason="attachment_low_confidence_override",
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
            log(f"Classification error ({exc}) -- defaulting to direct_answer")
            log(f"Time: {elapsed:.0f}ms")
            log("=" * 50)
            return RouterResult(
                action=RouterAction.DIRECT_ANSWER,
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
        reason = str(d.get("reasoning", d.get("reason", "")))

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
        return RouterResult(
            action=action, confidence=confidence, reason=reason
        )

    async def detect_and_translate(self, query: str) -> tuple[str, str]:
        """Detect language and return (lang_code, query_for_routing)."""
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

        if self._llm.provider in ("claude", "openai"):
            return "id", query

        prompt = (
            "Translate this to English. "
            "Output only the English translation, nothing else."
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
                r = await client.get(f"{self._llm._ollama_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
