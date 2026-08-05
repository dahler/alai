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

_PROMPT = """\
You are a request router. Pick exactly one action for the user request.

━━━ ACTIONS ━━━
direct_answer   Answer using general world knowledge only. No company docs needed.
rag_search      Search the user's internal company knowledge base (SOPs, policies,
                procedures, roles, org structure, approval thresholds, workflows).
agentic         Use tools: live data (prices/rates/weather/news), file generation
                (Excel/Word/PDF/PowerPoint), or email operations.

━━━ INPUT ━━━
Request: {query}
Has file attachments : {has_attachments}
Has image attachments: {has_images}
User has a knowledge base: {has_knowledge_base}

━━━ DECISION STEPS — follow in order ━━━
Step 1. Is this a greeting or small talk? (hi, thanks, oke, selamat pagi…)
        YES → action = direct_answer

Step 2. Does the request EXPLICITLY ask to generate/create/download a file,
        OR ask for live data that requires an external source RIGHT NOW?
        File generation: user says buat/create/generate/buatkan/download +
          (laporan/Excel/Word/PDF/PowerPoint/rekap/tabel/dokumen)
        Live external data: user asks for TODAY'S/CURRENT/TERBARU price,
          exchange rate, stock quote, weather, or news — data that changes
          daily and cannot be known without fetching it right now.
        Email: read inbox / send email / reply to email
        YES → action = agentic
        ⚠ NOT agentic: math problems that GIVE you the prices/numbers
          (e.g. "pensil seharga Rp2.000" — the price is given, not fetched).
          NOT agentic: calculations, unit conversions, word problems with
          numbers already stated in the question → these are direct_answer.

Step 3. Is "User has a knowledge base: true" and the question about a
        company-specific rule, person, threshold, SOP, or process that
        cannot be answered correctly from general world knowledge alone?
        (e.g. who approves, what is the limit, what is the SOP, who is PIC,
         bagaimana prosedur, siapa yang berwenang, berapa batas pengadaan)
        YES → action = rag_search

Step 4. Is "Has file attachments: true" and the query asks to analyse,
        summarise, review, or extract from the attachment itself?
        YES → action = direct_answer

Step 5. All other questions answerable from general world knowledge
        → action = direct_answer

Write your reasoning FIRST, then the action. The action must be consistent
with your reasoning. Format:

{{"reasoning": "<one sentence explaining which step matched and why>", "action": "<action>", "confidence": <0.0-1.0>}}

JSON:"""


class RouterService:
    """
    Classifies user requests using SmartLLM.
    Provider cascade: Claude -> OpenAI -> Ollama -> safe default.
    """

    def __init__(self) -> None:
        # Routing, intent, and language detection are lightweight JSON tasks —
        # run them on the small, fast router model (gemma3:1b) rather than the
        # heavier agent model reserved for planning/content generation.
        self._llm = SmartLLM(
            ollama_model=settings.OLLAMA_ROUTER_MODEL, timeout=30.0
        )

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

        # Hard-coded bypass: pure conversational / greeting messages
        _GREETINGS = {
            "hi", "hello", "hey", "halo", "hai", "hei",
            "thanks", "thank you", "terima kasih", "makasih", "thx",
            "ok", "okay", "oke", "oks", "got it", "noted",
            "good morning", "good afternoon", "good evening",
            "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
            "bye", "goodbye", "sampai jumpa", "dadah",
        }
        if query.strip().lower().rstrip("!.,") in _GREETINGS:
            log("DIRECT (greeting bypass)")
            log("=" * 50)
            return RouterResult(
                action=RouterAction.DIRECT_ANSWER,
                confidence=0.99,
                reason="greeting_bypass",
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

            # Safety override: attachment present and model chose rag_search
            # with low confidence. Small models default to rag_search when a
            # KB exists even when the query is about the attachment itself.
            # Require ≥0.88 confidence to actually run RAG with an attachment;
            # below that, trust the attachment and answer directly.
            if (
                has_attachments
                and not has_images
                and result.action == RouterAction.RAG_SEARCH
                and result.confidence < 0.88
            ):
                log(
                    f"Override: rag_search({result.confidence:.0%}) → "
                    "direct_answer (attachment present, confidence < 0.88)"
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
        # reasoning comes before action in the JSON so the model
        # commits to its logic before picking the label
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
