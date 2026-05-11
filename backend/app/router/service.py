import json
import re
import time
import logging
from typing import Optional
import httpx

from app.config import settings
from app.router.constants import (
    RouterAction,
    RouterResult,
    CONFIDENCE_THRESHOLD_HIGH,
    CONFIDENCE_THRESHOLD_LOW,
    DEFAULT_FALLBACK_ACTION,
    ACTION_KEYWORDS,
)

logger = logging.getLogger(__name__)


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [ROUTER] {message}")


# Optimized router prompt - minimal tokens, maximum clarity
ROUTER_PROMPT = """You are a request classifier. Classify the user request into ONE action.

Actions:
- direct_answer: General knowledge questions, explanations, coding help, historical facts
- rag_search: Questions about uploaded documents/files, summarization requests
- vision_analysis: Questions about images, charts, diagrams, visual content
- memory_lookup: References to previous conversation, "you said", "we discussed"
- agentic: ANYTHING needing current/real-time data: news, weather, prices, web search, latest info

Rules:
1. Output ONLY valid JSON
2. No markdown, no explanation
3. Format: {"action":"<action>","confidence":<0.0-1.0>}
4. IMPORTANT: Use "agentic" for ANY query about current events, prices, weather, news, or "latest"

User request: {query}
Has attachments: {has_attachments}
Has images: {has_images}

JSON:"""


class RouterService:
    """
    AI Router/Orchestrator that classifies requests before main model processing.
    Uses a small, fast model (gemma3:1b) for low-latency classification.
    """

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.OLLAMA_ROUTER_MODEL
        self.timeout = 30.0  # Fast timeout for router

    async def classify(
        self,
        query: str,
        has_attachments: bool = False,
        has_images: bool = False,
    ) -> RouterResult:
        """
        Classify a user request into an action type.

        Args:
            query: The user's input text
            has_attachments: Whether the request includes file attachments
            has_images: Whether the request includes image attachments

        Returns:
            RouterResult with action and confidence score
        """
        start_time = time.time()
        log("=" * 50)
        log("CLASSIFYING REQUEST")
        log("=" * 50)
        log(f"Query: {query[:80]}{'...' if len(query) > 80 else ''}")
        log(f"Has attachments: {has_attachments}")
        log(f"Has images: {has_images}")

        # Fast path: Check for obvious patterns first (no LLM call needed)
        quick_result = self._quick_classify(query, has_attachments, has_images)
        if quick_result and quick_result.confidence >= CONFIDENCE_THRESHOLD_HIGH:
            elapsed = time.time() - start_time
            log(f"⚡ QUICK CLASSIFY (no LLM needed)")
            log(f"   Action: {quick_result.action.value}")
            log(f"   Confidence: {quick_result.confidence:.0%}")
            log(f"   Reason: {quick_result.reason}")
            log(f"   Time: {elapsed*1000:.0f}ms")
            log("=" * 50)
            return quick_result

        # LLM-based classification
        try:
            log(f"Calling LLM router model: {self.model}...")
            result = await self._llm_classify(query, has_attachments, has_images)
            elapsed = time.time() - start_time
            log(f"🤖 LLM CLASSIFY")
            log(f"   Action: {result.action.value}")
            log(f"   Confidence: {result.confidence:.0%}")
            log(f"   Reason: {result.reason or 'llm_response'}")
            log(f"   Time: {elapsed*1000:.0f}ms")

            # If LLM confidence is low, use quick classify as fallback
            if result.confidence < CONFIDENCE_THRESHOLD_LOW and quick_result:
                log(f"⚠ Low confidence, using quick classify fallback")
                result = quick_result

            log("=" * 50)
            return result

        except Exception as e:
            elapsed = time.time() - start_time
            log(f"✗ Classification error: {e}")
            log(f"   Time: {elapsed*1000:.0f}ms")
            # Fallback to quick classify or default
            if quick_result:
                log(f"   Using quick classify fallback: {quick_result.action.value}")
                log("=" * 50)
                return quick_result
            log(f"   Using default fallback: {DEFAULT_FALLBACK_ACTION.value}")
            log("=" * 50)
            return RouterResult(
                action=DEFAULT_FALLBACK_ACTION,
                confidence=0.5,
                reason="fallback_error"
            )

    def _quick_classify(
        self,
        query: str,
        has_attachments: bool,
        has_images: bool,
    ) -> Optional[RouterResult]:
        """
        Quick rule-based classification without LLM.
        Returns high confidence results for obvious patterns.
        """
        query_lower = query.lower()

        # Image present = vision analysis
        if has_images:
            return RouterResult(
                action=RouterAction.VISION_ANALYSIS,
                confidence=0.95,
                reason="image_attached"
            )

        # Check RAG_SEARCH keywords FIRST (document/knowledge base queries)
        # These take priority over AGENTIC for queries about uploaded docs
        rag_keywords = ACTION_KEYWORDS.get(RouterAction.RAG_SEARCH, [])
        rag_matches = sum(1 for kw in rag_keywords if kw in query_lower)
        if rag_matches >= 1:
            log(f"Quick classify: RAG_SEARCH (matched {rag_matches} keyword(s))")
            return RouterResult(
                action=RouterAction.RAG_SEARCH,
                confidence=min(0.85 + (rag_matches * 0.03), 0.95),
                reason=f"rag_keyword_match_{rag_matches}"
            )

        # Check for AGENTIC keywords (web search, current info)
        agentic_keywords = ACTION_KEYWORDS.get(RouterAction.AGENTIC, [])
        agentic_matches = sum(1 for kw in agentic_keywords if kw in query_lower)
        if agentic_matches >= 1:
            log(f"Quick classify: AGENTIC (matched {agentic_matches} keyword(s))")
            return RouterResult(
                action=RouterAction.AGENTIC,
                confidence=min(0.8 + (agentic_matches * 0.05), 0.95),
                reason=f"agentic_keyword_match_{agentic_matches}"
            )

        # Check other keyword patterns (need 2+ matches)
        for action, keywords in ACTION_KEYWORDS.items():
            if action in [RouterAction.AGENTIC, RouterAction.RAG_SEARCH]:
                continue  # Already handled above
            matches = sum(1 for kw in keywords if kw in query_lower)
            if matches >= 2:
                return RouterResult(
                    action=action,
                    confidence=min(0.7 + (matches * 0.1), 0.95),
                    reason=f"keyword_match_{matches}"
                )

        # Attachment without image = likely RAG
        if has_attachments:
            return RouterResult(
                action=RouterAction.RAG_SEARCH,
                confidence=0.8,
                reason="attachment_present"
            )

        return None

    async def _llm_classify(
        self,
        query: str,
        has_attachments: bool,
        has_images: bool,
    ) -> RouterResult:
        """
        Use LLM for classification when quick classify is uncertain.
        """
        prompt = ROUTER_PROMPT.format(
            query=query[:500],  # Truncate long queries
            has_attachments=str(has_attachments).lower(),
            has_images=str(has_images).lower(),
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temp for deterministic output
                        "num_predict": 50,   # Short response
                        "top_p": 0.9,
                    }
                },
            )
            response.raise_for_status()
            data = response.json()
            raw_output = data.get("response", "")

        return self._parse_response(raw_output)

    def _parse_response(self, raw_output: str) -> RouterResult:
        """
        Parse LLM output to RouterResult with malformed JSON recovery.
        """
        # Clean the output
        cleaned = raw_output.strip()

        # Try direct JSON parse
        try:
            parsed = json.loads(cleaned)
            return self._validate_parsed(parsed)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from text
        json_match = re.search(r'\{[^{}]*\}', cleaned)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return self._validate_parsed(parsed)
            except json.JSONDecodeError:
                pass

        # Try to extract action from malformed output
        action = self._extract_action_from_text(cleaned)
        if action:
            return RouterResult(
                action=action,
                confidence=0.6,
                reason="extracted_from_text"
            )

        # Final fallback
        log(f"⚠ Failed to parse LLM output: {cleaned[:100]}")
        return RouterResult(
            action=DEFAULT_FALLBACK_ACTION,
            confidence=0.5,
            reason="parse_failed"
        )

    def _validate_parsed(self, parsed: dict) -> RouterResult:
        """Validate and convert parsed JSON to RouterResult."""
        action_str = parsed.get("action", "").lower().strip()
        confidence = parsed.get("confidence", 0.8)

        # Validate action
        try:
            action = RouterAction(action_str)
        except ValueError:
            # Try to match partial action name
            for valid_action in RouterAction:
                if valid_action.value in action_str or action_str in valid_action.value:
                    action = valid_action
                    break
            else:
                action = DEFAULT_FALLBACK_ACTION
                confidence = 0.5

        # Redirect external_api to agentic (external_api is not implemented)
        if action == RouterAction.EXTERNAL_API:
            action = RouterAction.AGENTIC
            log("Redirecting EXTERNAL_API -> AGENTIC")

        # Validate confidence
        try:
            confidence = float(confidence)
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            confidence = 0.7

        return RouterResult(action=action, confidence=confidence)

    def _extract_action_from_text(self, text: str) -> Optional[RouterAction]:
        """Try to extract action type from malformed text output."""
        text_lower = text.lower()
        for action in RouterAction:
            if action.value in text_lower:
                return action
        return None

    async def health_check(self) -> bool:
        """Check if the router model is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    return any(m.get("name", "").startswith(self.model.split(":")[0]) for m in models)
        except Exception:
            pass
        return False
