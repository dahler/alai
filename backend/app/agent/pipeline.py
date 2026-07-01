"""
Structured Agent Pipeline
=========================
Replaces the monolithic ReAct loop with a clean 10-stage flow:

  User Message
      │
  ┌───▼────────────┐
  │ Language Detect │  rule-based, instant
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Intent Analysis │  SmartLLM (Claude / OpenAI / Ollama)
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Planner Agent  │  SmartLLM — returns structured tool plan
  └───┬────────────┘
      │
  ┌───▼────────────────────────────────────────┐
  │ Tool Execution  (parallel where possible)  │
  │  · RAG Search    · Yahoo Finance            │
  │  · Web Search    · Email Read/Send          │
  │  · Calculator    · File Generate            │
  └───┬────────────────────────────────────────┘
      │
  ┌───▼────────────┐
  │ Evidence Merge │  rank by freshness & relevance
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Reflection     │  confidence check → retry if needed
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Output Decide  │  text | report_file | email_draft
  └───┬────────────┘
      │
  ┌───▼────────────┐
  │ Language Render │  respond in detected language
  └───┬────────────┘
      │
  User Response
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.agent.executor import ExecutionStatus
from app.agent.loop import AgentLoop, AgentTrace, _email_draft_cache
from app.config import settings
from app.services.smart_llm import SmartLLM


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

class IntentType(str, Enum):
    DIRECT_ANSWER = "direct_answer"
    RAG_SEARCH = "rag_search"
    WEB_RESEARCH = "web_research"
    FINANCE_DATA = "finance_data"
    EMAIL_READ = "email_read"
    EMAIL_COMPOSE = "email_compose"
    REPORT_GENERATE = "report_generate"
    MULTI_TOOL = "multi_tool"
    CONVERSATION = "conversation"


class OutputType(str, Enum):
    TEXT = "text"
    REPORT_FILE = "report_file"
    EMAIL_DRAFT = "email_draft"


@dataclass
class IntentResult:
    intent: IntentType
    output_type: OutputType
    output_format: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    language: str = "en"
    confidence: float = 0.8
    reason: str = ""


@dataclass
class ToolStep:
    tool: str
    params: Dict[str, Any]
    purpose: str
    parallel: bool = True
    step_id: str = ""


@dataclass
class ExecutionPlan:
    steps: List[ToolStep]
    output_type: OutputType
    output_format: Optional[str] = None
    reasoning: str = ""


@dataclass
class Evidence:
    source_type: str
    tool_name: str
    content: str
    relevance: float = 1.0
    freshness: str = "unknown"


@dataclass
class ReflectionResult:
    sufficient: bool
    confidence: float
    missing: List[str]
    extra_steps: List[ToolStep] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────

class AgentPipeline(AgentLoop):
    """
    Structured pipeline. Subclasses AgentLoop so all specialized handlers
    (file generation, email, template matching, Yahoo Finance helpers) are
    inherited. Only run() is replaced with the new multi-stage flow.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Agent model (qwen2.5:7b): planning + reflection.
        self._smart = SmartLLM()
        # Router model (gemma3:1b): fast intent classification.
        self._router = SmartLLM(ollama_model=settings.OLLAMA_ROUTER_MODEL)

    # ── Stage 2: Language Detection ───────────────────────────────────────────

    _INDO_MARKERS: set = {
        "apa", "apakah", "bagaimana", "tolong", "mohon", "saya", "kamu", "anda",
        "bisa", "kenapa", "mengapa", "jelaskan", "buat", "cari", "berapa",
        "yang", "dan", "atau", "untuk", "dengan", "ini", "itu", "tidak", "ada",
        "adalah", "akan", "sudah", "jika", "kalau", "tapi", "tetapi", "namun",
        "karena", "seperti", "dari", "pada", "buatkan", "hasilkan",
        "laporan", "analisis", "terbaru", "sekarang", "hari", "minggu",
        "berita", "harga", "kurs", "nilai", "saham", "pasar",
    }

    def detect_language(self, text: str) -> str:
        words = re.findall(r'\b\w+\b', text.lower())
        hits = sum(1 for w in words if w in self._INDO_MARKERS)
        return "id" if hits >= 2 else "en"

    # ── Stage 3: Intent Analysis ──────────────────────────────────────────────

    _INTENT_SYSTEM = "You are an intent classifier for an enterprise AI assistant. Always respond with valid JSON only."

    _INTENT_PROMPT = """\
Classify the user's request into one intent category.

User request: {task}
Prior conversation turns: {ctx_len}

Return ONLY a JSON object (no markdown):
{{
  "intent": "<direct_answer|rag_search|web_research|finance_data|email_read|email_compose|report_generate|multi_tool|conversation>",
  "output_type": "<text|report_file|email_draft>",
  "output_format": "<xlsx|docx|pdf|pptx|null>",
  "topics": ["<topic1>"],
  "confidence": <0.0-1.0>,
  "reason": "<one sentence>"
}}

Intent definitions:
- direct_answer   : factual Q&A, definitions, explanations — no live data needed
- rag_search      : user mentions "my documents", "SOP", "company policy", "uploaded files"
- web_research    : needs current news, events, prices from the internet
- finance_data    : stocks, forex (rupiah, dollar, euro, etc.), crypto, market indices
- email_read      : read, list, or search Outlook emails
- email_compose   : write, reply, or draft an email
- report_generate : explicitly asks to CREATE a file (report, excel, word, pdf, presentation, laporan)
- multi_tool      : needs ≥2 data sources combined (e.g. finance + web + docs)
- conversation    : follow-up questions, small talk, clarification

Output format:
- report_file → always set output_format (default xlsx if not specified)
- text/email_draft → output_format = null

JSON:"""

    async def _analyze_intent(
        self,
        task: str,
        language: str,
        context: Optional[List[Dict]] = None,
    ) -> IntentResult:
        ctx_len = len(context) if context else 0
        prompt = self._INTENT_PROMPT.format(task=task, ctx_len=ctx_len)
        try:
            raw = await self._router.complete(prompt, self._INTENT_SYSTEM)
            m = re.search(r'\{.*\}', raw.strip(), re.DOTALL)
            if m:
                d = json.loads(m.group())
                fmt = d.get("output_format") or None
                if fmt and fmt.lower() == "null":
                    fmt = None
                return IntentResult(
                    intent=IntentType(d.get("intent", "multi_tool")),
                    output_type=OutputType(d.get("output_type", "text")),
                    output_format=fmt,
                    topics=d.get("topics", []),
                    language=language,
                    confidence=float(d.get("confidence", 0.8)),
                    reason=d.get("reason", ""),
                )
        except Exception as e:
            self._log(f"Intent analysis error: {e}")
        return IntentResult(
            intent=IntentType.MULTI_TOOL,
            output_type=OutputType.TEXT,
            language=language,
        )

    # ── Stage 4: Execution Planning ───────────────────────────────────────────

    _PLAN_SYSTEM = "You are a tool-use planner for an AI assistant. Return only valid JSON."

    _PLAN_PROMPT = """\
Create an execution plan to answer the user's request.

User request: {task}
Intent: {intent}
Topics: {topics}
Language: {language}

Available tools:
  web_search      params: query(str), num_results(int=5)
                  → search the internet (Tavily)
  yahoo_finance   params: symbol(str), action(quote|history|news|info|financials), period(1d|5d|1mo|3mo|6mo|1y)
                  → live stock/forex/index data
                  Common symbols: IDR=X (USD/IDR rupiah), SGD=X, EUR=X, GBP=X, JPY=X,
                    MYR=X, ^JKSE (IHSG), ^GSPC (S&P500), ^IXIC (NASDAQ), ^DJI (Dow)
  rag_search      params: query(str), top_k(int=8)
                  → search uploaded company documents
  email_read      params: action(list|read|search), query(str), top(int), message_id(str)
                  → read Outlook emails
  calculator      params: expression(str)
                  → evaluate math expression
  get_current_time params: timezone(str="Asia/Jakarta")
                  → current date/time

Rules:
1. parallel=true means the step can run concurrently with other parallel steps
2. parallel=false means it must wait for all previous steps to finish
3. For finance topics: include quote + history(3mo) + web_search for news
4. For report_generate intent: gather data only — the system creates the file automatically
5. For direct_answer/conversation with no live data needed: return empty steps list
6. Maximum 6 steps total

Return ONLY JSON:
{{
  "steps": [
    {{"tool": "tool_name", "params": {{}}, "purpose": "brief description", "parallel": true}}
  ],
  "reasoning": "one sentence explaining the plan"
}}

JSON:"""

    async def _plan_execution(
        self, task: str, intent: IntentResult, language: str
    ) -> ExecutionPlan:
        # Direct answer — no tools needed
        if intent.intent in (IntentType.DIRECT_ANSWER, IntentType.CONVERSATION):
            return ExecutionPlan(
                steps=[],
                output_type=intent.output_type,
                output_format=intent.output_format,
                reasoning="direct knowledge answer, no tools needed",
            )

        prompt = self._PLAN_PROMPT.format(
            task=task,
            intent=intent.intent.value,
            topics=", ".join(intent.topics) or "general",
            language=language,
        )
        steps: List[ToolStep] = []
        reasoning = ""
        try:
            raw = await self._smart.complete(prompt, self._PLAN_SYSTEM)
            m = re.search(r'\{.*\}', raw.strip(), re.DOTALL)
            if m:
                d = json.loads(m.group())
                for i, s in enumerate(d.get("steps", [])):
                    tool = s.get("tool", "none").lower().strip()
                    if tool in ("none", ""):
                        continue
                    params = s.get("params", {})
                    # Fill missing required params
                    params = self._ensure_tool_params(tool, params, task)
                    steps.append(ToolStep(
                        tool=tool,
                        params=params,
                        purpose=s.get("purpose", ""),
                        parallel=bool(s.get("parallel", True)),
                        step_id=f"step_{i}",
                    ))
                reasoning = d.get("reasoning", "")
        except Exception as e:
            self._log(f"Planning error: {e}")
            steps = self._fallback_plan(task, intent)

        return ExecutionPlan(
            steps=steps,
            output_type=intent.output_type,
            output_format=intent.output_format,
            reasoning=reasoning,
        )

    def _fallback_plan(self, task: str, intent: IntentResult) -> List[ToolStep]:
        """Rule-based fallback when LLM planning fails."""
        tl = task.lower()
        steps: List[ToolStep] = []
        if intent.intent == IntentType.RAG_SEARCH:
            steps.append(ToolStep("rag_search", {"query": task, "top_k": 8}, "search documents", True, "s0"))
        elif intent.intent in (IntentType.FINANCE_DATA, IntentType.MULTI_TOOL):
            for kws, sym, label in [
                (["rupiah", "idr"], "IDR=X", "USD/IDR"),
                (["sgd", "singapore dollar"], "SGD=X", "USD/SGD"),
                (["ihsg", "jkse", "bursa indonesia"], "^JKSE", "IHSG"),
                (["s&p", "sp500", "s&p500"], "^GSPC", "S&P500"),
            ]:
                if any(k in tl for k in kws):
                    steps.append(ToolStep("yahoo_finance", {"symbol": sym, "action": "quote"}, f"live {label}", True, f"s{len(steps)}"))
                    steps.append(ToolStep("yahoo_finance", {"symbol": sym, "action": "history", "period": "3mo"}, f"trend {label}", True, f"s{len(steps)}"))
            steps.append(ToolStep("web_search", {"query": task, "num_results": 5}, "web context", True, f"s{len(steps)}"))
        elif intent.intent == IntentType.EMAIL_READ:
            steps.append(ToolStep("email_read", {"action": "list", "folder": "inbox", "top": 10}, "read inbox", True, "s0"))
        elif intent.intent == IntentType.WEB_RESEARCH:
            steps.append(ToolStep("web_search", {"query": task, "num_results": 5}, "web search", True, "s0"))
        else:
            steps.append(ToolStep("web_search", {"query": task, "num_results": 5}, "general search", True, "s0"))
        return steps

    # ── Stage 5: Tool Execution ───────────────────────────────────────────────

    def _source_type(self, tool: str) -> str:
        return {
            "rag_search": "rag",
            "web_search": "web",
            "yahoo_finance": "finance",
            "email_read": "email",
            "calculator": "direct",
            "get_current_time": "direct",
        }.get(tool, "direct")

    def _freshness(self, tool: str) -> str:
        return {
            "yahoo_finance": "live",
            "web_search": "recent",
            "get_current_time": "live",
        }.get(tool, "static")

    async def _execute_plan(
        self,
        plan: ExecutionPlan,
        evidences: List[Evidence],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute all plan steps, yielding UI events.
        Parallel steps run concurrently via asyncio.gather.
        """
        # Partition into parallel groups and sequential singletons
        groups: List[List[ToolStep]] = []
        current_parallel: List[ToolStep] = []
        for step in plan.steps:
            if step.parallel:
                current_parallel.append(step)
            else:
                if current_parallel:
                    groups.append(current_parallel)
                    current_parallel = []
                groups.append([step])
        if current_parallel:
            groups.append(current_parallel)

        for group in groups:
            if len(group) == 1:
                async for event in self._run_single_step(group[0], evidences):
                    yield event
            else:
                # Run concurrently
                tool_names = ", ".join(s.tool for s in group)
                yield {"type": "thought", "content": f"Running tools in parallel: {tool_names}…"}
                results = await asyncio.gather(
                    *[self.executor.execute(s.tool, self._ensure_tool_params(s.tool, s.params.copy(), "")) for s in group],
                    return_exceptions=True,
                )
                for step, result in zip(group, results):
                    if isinstance(result, Exception):
                        obs = f"Tool {step.tool} failed: {result}"
                        yield {"type": "observation", "result": obs, "status": "error"}
                    else:
                        obs = result.to_observation()
                        yield {"type": "action",      "tool": step.tool, "input": step.params}
                        yield {"type": "observation", "result": obs, "status": result.status.value}
                        ev = Evidence(
                            source_type=self._source_type(step.tool),
                            tool_name=step.tool,
                            content=obs,
                            freshness=self._freshness(step.tool),
                        )
                        evidences.append(ev)
                        self._track_sources(step.tool, result)

    async def _run_single_step(
        self, step: ToolStep, evidences: List[Evidence]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        yield {"type": "thought", "content": f"{step.purpose}…"}
        params = self._ensure_tool_params(step.tool, step.params.copy(), "")
        yield {"type": "action", "tool": step.tool, "input": params}
        result = await self.executor.execute(step.tool, params)
        obs = result.to_observation()
        yield {"type": "observation", "result": obs, "status": result.status.value}
        ev = Evidence(
            source_type=self._source_type(step.tool),
            tool_name=step.tool,
            content=obs,
            freshness=self._freshness(step.tool),
        )
        evidences.append(ev)
        self._track_sources(step.tool, result)

    def _track_sources(self, tool: str, result: Any) -> None:
        if result.status != ExecutionStatus.SUCCESS:
            return
        if tool == "web_search" and isinstance(result.result, dict):
            for r in result.result.get("results", []):
                if r.get("url") and not any(
                    isinstance(s, dict) and s.get("url") == r["url"]
                    for s in self.trace.sources
                ):
                    self.trace.sources.append({
                        "type": "web",
                        "title": r.get("title") or r["url"],
                        "url": r["url"],
                    })
        elif tool == "rag_search" and isinstance(result.result, dict):
            for r in result.result.get("results", []):
                if r.get("source") and not any(
                    isinstance(s, dict) and s.get("name") == r["source"]
                    for s in self.trace.sources
                ):
                    self.trace.sources.append({"type": "doc", "name": r["source"]})

    # ── Stage 6: Evidence Merge ───────────────────────────────────────────────

    _FRESHNESS_ORDER = {"live": 0, "recent": 1, "static": 2, "stale": 3, "unknown": 4}

    def _merge_evidence(self, evidences: List[Evidence], task: str) -> str:
        if not evidences:
            return ""
        # Sort: live data first, then recent, then static
        sorted_ev = sorted(evidences, key=lambda e: self._FRESHNESS_ORDER.get(e.freshness, 4))
        parts = []
        for ev in sorted_ev:
            tag = f"[{ev.tool_name.replace('_', ' ').title()} — {ev.freshness}]"
            parts.append(f"{tag}\n{ev.content}")
        return "\n\n---\n\n".join(parts)

    # ── Stage 7: Reflection ───────────────────────────────────────────────────

    _REFLECT_PROMPT = """\
You are a quality checker. Assess whether the evidence is sufficient to answer the user's request.

User request: {task}

Evidence summary (first 2000 chars):
{evidence_preview}

Return ONLY JSON:
{{
  "sufficient": <true|false>,
  "confidence": <0.0-1.0>,
  "missing": ["<what is missing>"],
  "extra_queries": [
    {{"tool": "web_search", "params": {{"query": "..."}}, "purpose": "...", "parallel": true}}
  ]
}}

Rules:
- If finance data is present with actual numbers → likely sufficient
- If web search returned real articles → likely sufficient
- If evidence is empty or only error messages → not sufficient
- extra_queries: max 2 additional tool calls, only if truly needed

JSON:"""

    async def _reflect(
        self,
        task: str,
        evidences: List[Evidence],
        plan: ExecutionPlan,
    ) -> ReflectionResult:
        if not evidences:
            # No evidence at all — need at least a web search
            return ReflectionResult(
                sufficient=False,
                confidence=0.0,
                missing=["any information"],
                extra_steps=[ToolStep("web_search", {"query": task, "num_results": 5}, "fallback search", True, "reflect_0")],
            )

        evidence_preview = self._merge_evidence(evidences, task)[:2000]
        prompt = self._REFLECT_PROMPT.format(task=task, evidence_preview=evidence_preview)
        try:
            raw = await self._smart.complete(prompt)
            m = re.search(r'\{.*\}', raw.strip(), re.DOTALL)
            if m:
                d = json.loads(m.group())
                extra_steps = [
                    ToolStep(
                        tool=s.get("tool", "web_search"),
                        params=s.get("params", {"query": task}),
                        purpose=s.get("purpose", "additional search"),
                        parallel=bool(s.get("parallel", True)),
                        step_id=f"reflect_{i}",
                    )
                    for i, s in enumerate(d.get("extra_queries", []))
                ]
                return ReflectionResult(
                    sufficient=bool(d.get("sufficient", True)),
                    confidence=float(d.get("confidence", 0.7)),
                    missing=d.get("missing", []),
                    extra_steps=extra_steps,
                )
        except Exception as e:
            self._log(f"Reflection error: {e}")
        # Default: trust the evidence we have
        return ReflectionResult(sufficient=True, confidence=0.75, missing=[])

    # ── Stage 8/9: Output Generation ─────────────────────────────────────────

    _RESPONSE_SYSTEM = """\
You are ALAI, a professional AI assistant for enterprise use.
Always respond in the SAME LANGUAGE as the user's request.
When citing sources use inline [1], [2], etc.
Be concise, accurate, and professional."""

    _RESPONSE_PROMPT = """\
Answer the user's request using ONLY the evidence provided below.

User request: {task}
Respond in: {lang_name}

Evidence:
{evidence}

Citations available:
{citations}

Guidelines:
- Use exact numbers from [Yahoo Finance] and [Web Search] — never invent figures
- [Knowledge Base] content may be old — use only for context/definitions, not for rates or prices
- Cite sources inline as [1], [2], etc.
- Structure the answer clearly (use headers/bullets where it helps)
- If a piece of data is not in the evidence, say "data not available" rather than guessing

Answer:"""

    async def _generate_text_response(
        self,
        task: str,
        merged_evidence: str,
        language: str,
        context: Optional[List[Dict]],
        evidences: List[Evidence],
    ) -> str:
        lang_name = "Bahasa Indonesia" if language == "id" else "English"

        # Build numbered citations
        citation_lines: List[str] = []
        for i, src in enumerate(self.trace.sources, 1):
            if isinstance(src, dict):
                if src["type"] == "web":
                    citation_lines.append(f"[{i}] {src.get('title', src['url'])} — {src['url']}")
                else:
                    citation_lines.append(f"[{i}] Document: {src['name']}")
        citations_block = "\n".join(citation_lines) if citation_lines else "No external sources."

        # If no evidence collected (direct answer intent), generate from knowledge
        if not merged_evidence:
            prompt = (
                f"Answer this in {lang_name}, concisely and accurately:\n\n{task}"
            )
            messages = []
            if context:
                for msg in context[-6:]:
                    messages.append(msg)
            messages.append({"role": "user", "content": prompt})
            return await self.ai_service.generate_response(messages)

        prompt = self._RESPONSE_PROMPT.format(
            task=task,
            lang_name=lang_name,
            evidence=merged_evidence[:12000],
            citations=citations_block,
        )
        messages = [{"role": "system", "content": self._RESPONSE_SYSTEM}]
        if context:
            for msg in context[-4:]:
                messages.append(msg)
        messages.append({"role": "user", "content": prompt})

        try:
            return await self.ai_service.generate_response(messages, use_agent_model=True)
        except Exception as e:
            self._log(f"Response generation error: {e}")
            return f"I gathered information but encountered an error composing the response: {e}"

    # ─────────────────────────────────────────────────────────────────────────
    # Main pipeline entry point — overrides AgentLoop.run()
    # ─────────────────────────────────────────────────────────────────────────

    async def run(
        self,
        task: str,
        context: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        start_time = time.time()
        self.trace = AgentTrace(task=task)

        self._log("=" * 60)
        self._log(f"PIPELINE START: {task[:100]}")
        self._log("=" * 60)

        # ── Email send-confirmation shortcut ──────────────────────────────────
        draft_nums = self._detect_send_confirmation(task)
        if draft_nums is not None and self.user_id and _email_draft_cache.get(self.user_id):
            self._log("EMAIL SEND CONFIRMATION")
            async for event in self._handle_send_confirmation(task, draft_nums, context):
                yield event
            await self.executor.close()
            self.trace.total_time = time.time() - start_time
            return

        # ── Stage 2: Language detection ───────────────────────────────────────
        language = self.detect_language(task)
        self._log(f"Language: {language}")

        # ── Stage 3: Intent analysis ──────────────────────────────────────────
        yield {"type": "thought", "content": "Analysing your request…"}
        intent = await self._analyze_intent(task, language, context)
        self._log(f"Intent: {intent.intent.value} | Output: {intent.output_type.value} | Confidence: {intent.confidence:.2f} | Reason: {intent.reason}")

        # ── Fast paths for specialized workflows ──────────────────────────────

        # Email read-from-sender fast path
        sender_query = self._detect_read_email_from(task)
        if sender_query or intent.intent == IntentType.EMAIL_READ:
            if sender_query:
                self._log(f"EMAIL READ FROM: {sender_query}")
                async for event in self._handle_read_latest_email(task, sender_query, context):
                    yield event
            elif self._detect_email_workflow(task) or intent.intent == IntentType.EMAIL_COMPOSE:
                self._log("EMAIL WORKFLOW")
                async for event in self._handle_email_workflow(task, context):
                    yield event
            else:
                # Generic email read → use planner
                async for event in self._pipeline_text_flow(task, intent, language, context):
                    yield event
            await self.executor.close()
            self.trace.total_time = time.time() - start_time
            return

        # Email compose / reply fast path
        if intent.intent == IntentType.EMAIL_COMPOSE or self._detect_email_workflow(task):
            self._log("EMAIL COMPOSE WORKFLOW")
            async for event in self._handle_email_workflow(task, context):
                yield event
            await self.executor.close()
            self.trace.total_time = time.time() - start_time
            return

        # File / report generation fast path
        if intent.intent == IntentType.REPORT_GENERATE or intent.output_type == OutputType.REPORT_FILE:
            # Determine file format
            file_fmt, file_name = self._detect_file_request(task)
            if not file_fmt:
                file_fmt = intent.output_format or "xlsx"
                file_name = self._derive_filename(task, file_fmt)
            self._log(f"REPORT GENERATE: fmt={file_fmt} file={file_name}")
            yield {"type": "thought", "content": f"Preparing to generate your {file_fmt.upper()} report…"}
            async for event in self._handle_file_generation(task, file_fmt, file_name, context):
                yield event
            await self.executor.close()
            self.trace.total_time = time.time() - start_time
            return

        # ── Main text-response pipeline ───────────────────────────────────────
        async for event in self._pipeline_text_flow(task, intent, language, context):
            yield event

        await self.executor.close()
        self.trace.total_time = time.time() - start_time
        self._log(f"PIPELINE DONE in {self.trace.total_time:.2f}s")

    async def _pipeline_text_flow(
        self,
        task: str,
        intent: IntentResult,
        language: str,
        context: Optional[List[Dict]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stages 4-10 for text responses."""

        # ── Stage 4: Planning ─────────────────────────────────────────────────
        yield {"type": "thought", "content": f"Planning with {self._smart.provider_label}…"}
        plan = await self._plan_execution(task, intent, language)
        self._log(f"Plan: {len(plan.steps)} steps | {plan.reasoning}")

        if plan.steps:
            tool_list = " + ".join(s.tool for s in plan.steps)
            yield {"type": "thought", "content": f"Will use: {tool_list}"}

        # ── Stage 5: Tool execution ───────────────────────────────────────────
        evidences: List[Evidence] = []
        async for event in self._execute_plan(plan, evidences):
            yield event

        # ── Stage 6: Evidence merge ───────────────────────────────────────────
        merged = self._merge_evidence(evidences, task)

        # ── Stage 7: Reflection / confidence check ────────────────────────────
        reflection = await self._reflect(task, evidences, plan)
        self._log(f"Reflection: sufficient={reflection.sufficient} confidence={reflection.confidence:.2f}")

        if not reflection.sufficient and reflection.extra_steps:
            missing_desc = ", ".join(reflection.missing[:3]) if reflection.missing else "more context"
            yield {"type": "thought", "content": f"Need more information: {missing_desc}. Running additional searches…"}
            extra_plan = ExecutionPlan(
                steps=reflection.extra_steps,
                output_type=intent.output_type,
            )
            async for event in self._execute_plan(extra_plan, evidences):
                yield event
            merged = self._merge_evidence(evidences, task)

        # ── Stages 8/9/10: Output generation + language render ────────────────
        yield {"type": "thought", "content": "Composing your answer…"}
        response = await self._generate_text_response(task, merged, language, context, evidences)

        self.trace.final_answer = response
        self.trace.success = True
        yield {
            "type": "final_answer",
            "content": response,
            "sources": self.trace.sources,
        }

    # run_streaming stays compatible — inherited from AgentLoop, calls self.run()
