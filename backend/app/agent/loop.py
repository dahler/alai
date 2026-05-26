"""
ReAct Agent Loop - Reasoning, Acting, and Observing.

Implements the ReAct pattern for autonomous task execution:
1. Reason about the current state and what to do next
2. Act by calling a tool
3. Observe the result
4. Repeat until task is complete
"""

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

from app.agent.tools import tool_registry, Tool
from app.agent.executor import ToolExecutor, ToolResult, ExecutionStatus
from app.agent.prompts import get_agent_system_prompt, get_react_format_instructions


class AgentState(str, Enum):
    """Current state of the agent."""
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    COMPLETE = "complete"
    ERROR = "error"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


@dataclass
class AgentStep:
    """A single step in the agent's execution."""
    step_number: int
    state: AgentState
    thought: Optional[str] = None
    action: Optional[str] = None
    action_input: Optional[Dict[str, Any]] = None
    observation: Optional[str] = None
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "state": self.state.value,
            "thought": self.thought,
            "action": self.action,
            "action_input": self.action_input,
            "observation": self.observation,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class AgentTrace:
    """Complete trace of agent execution."""
    task: str
    steps: List[AgentStep] = field(default_factory=list)
    final_answer: Optional[str] = None
    sources: List[str] = field(default_factory=list)
    total_time: float = 0.0
    total_tokens: int = 0
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "final_answer": self.final_answer,
            "sources": self.sources,
            "total_time": self.total_time,
            "total_tokens": self.total_tokens,
            "success": self.success,
        }


class AgentLoop:
    """
    ReAct Agent Loop for autonomous task execution.

    Uses the ReAct pattern:
    - Thought: Reason about what to do next
    - Action: Choose a tool to use
    - Observation: See the result
    - Repeat until task is complete

    Example:
        agent = AgentLoop(ai_service, db_session, user_id)
        async for event in agent.run("What is the weather in Tokyo?"):
            print(event)
    """

    def __init__(
        self,
        ai_service,
        db_session=None,
        user_id: Optional[int] = None,
        max_steps: int = 10,
        verbose: bool = True,
    ):
        self.ai_service = ai_service
        self.db_session = db_session
        self.user_id = user_id
        self.max_steps = max_steps
        self.verbose = verbose

        self.executor = ToolExecutor(
            db_session=db_session,
            user_id=user_id,
            timeout=30.0,
        )

        self.state = AgentState.IDLE
        self.trace: Optional[AgentTrace] = None

    def _log(self, message: str):
        if self.verbose:
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] [AGENT] {message}", flush=True)

    async def _detect_required_tool(self, task: str) -> Optional[List[Tuple[str, Dict[str, Any]]]]:
        """
        Use LLM to detect which tool(s) are required for the task.
        Returns list of (tool_name, parameters) tuples, or None for direct answer queries.
        Supports multi-tool detection in a single LLM call.
        """
        self._log("Using LLM for multi-tool detection...")

        tool_detection_prompt = f"""You are a tool selector. Analyze the user's request and decide which tool(s) to use. You may select MULTIPLE tools when the query needs combined data.

Available tools:
1. rag_search - Search uploaded documents, files, PDFs, company SOPs, knowledge base, manuals
2. web_search - Search the internet for current news, weather, prices, latest information, real-time data
3. yahoo_finance - Get stock/currency data (prices, history, financials, exchange rates). Use symbol=IDR=X for USD/IDR, symbol=^JKSE for IHSG index
4. calculator - Perform mathematical calculations
5. get_current_time - Get current time/date
6. read_url - Read content from a specific URL

When to use multiple tools:
- Currency/forex queries needing current rate AND news/analysis → yahoo_finance + web_search
- Stock market overview needing index data AND news → yahoo_finance + web_search
- Research needing both uploaded docs AND web context → rag_search + web_search

User request: "{task}"

Respond with ONLY a JSON object (no markdown, no explanation):
{{"tools": [{{"tool": "<name>", "params": {{...}}}}], "reason": "<brief reason>"}}

If no tool needed: {{"tools": [], "reason": "general knowledge"}}

Examples:
- "Kurs rupiah terbaru dan beritanya?" → {{"tools": [{{"tool": "yahoo_finance", "params": {{"symbol": "IDR=X", "action": "quote"}}}}, {{"tool": "web_search", "params": {{"query": "kurs rupiah terbaru berita", "num_results": 5}}}}], "reason": "currency rate and news"}}
- "IHSG performance this week?" → {{"tools": [{{"tool": "yahoo_finance", "params": {{"symbol": "^JKSE", "action": "history", "period": "5d"}}}}, {{"tool": "web_search", "params": {{"query": "IHSG performance this week", "num_results": 5}}}}], "reason": "index data and news"}}
- "What's AAPL stock price?" → {{"tools": [{{"tool": "yahoo_finance", "params": {{"symbol": "AAPL", "action": "quote"}}}}], "reason": "single stock price"}}
- "What's in my company SOP about leave?" → {{"tools": [{{"tool": "rag_search", "params": {{"query": "leave policy", "top_k": 5}}}}], "reason": "document search"}}
- "Latest AI news?" → {{"tools": [{{"tool": "web_search", "params": {{"query": "latest AI news", "num_results": 5}}}}], "reason": "current information"}}
- "Calculate 15% of 250" → {{"tools": [{{"tool": "calculator", "params": {{"expression": "0.15 * 250"}}}}], "reason": "math"}}
- "What is Python?" → {{"tools": [], "reason": "general knowledge"}}

JSON:"""

        try:
            messages = [{"role": "user", "content": tool_detection_prompt}]
            response = await self.ai_service.generate_response(messages, use_agent_model=True)

            cleaned = response.strip()
            self._log(f"LLM tool detection raw response: {cleaned[:300]}")

            # Extract JSON — use greedy dotall to capture nested objects
            json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())

                # New multi-tool format: {"tools": [...], "reason": "..."}
                if "tools" in parsed:
                    tools_list = parsed.get("tools", [])
                    reason = parsed.get("reason", "")
                    self._log(f"LLM detected {len(tools_list)} tool(s) | Reason: {reason}")

                    if not tools_list:
                        return None

                    result = []
                    for entry in tools_list:
                        tool_name = entry.get("tool", "").lower().strip()
                        params = entry.get("params", {})
                        if not tool_name or tool_name == "none":
                            continue
                        if not tool_registry.get(tool_name):
                            self._log(f"Unknown tool '{tool_name}', skipping")
                            continue
                        params = self._ensure_tool_params(tool_name, params, task)
                        result.append((tool_name, params))

                    return result if result else None

                # Legacy single-tool format: {"tool": "...", "params": {...}}
                tool_name = parsed.get("tool", "none").lower().strip()
                params = parsed.get("params", {})
                reason = parsed.get("reason", "")
                self._log(f"LLM detected tool: {tool_name} | Reason: {reason}")

                if tool_name == "none":
                    return None

                if not tool_registry.get(tool_name):
                    self._log(f"Unknown tool '{tool_name}', falling back to web_search")
                    return [("web_search", {"query": task, "num_results": 5})]

                params = self._ensure_tool_params(tool_name, params, task)
                return [(tool_name, params)]

        except Exception as e:
            self._log(f"✗ LLM tool detection EXCEPTION: {e}")

        fallback = self._fallback_detect_tool(task)
        self._log(f"Fallback tool detection result: {fallback}")
        return fallback

    def _ensure_tool_params(self, tool_name: str, params: Dict[str, Any], task: str) -> Dict[str, Any]:
        """Fill in missing required parameters for a tool."""
        if tool_name == "rag_search" and "query" not in params:
            params["query"] = task
            params.setdefault("top_k", 5)
        elif tool_name == "web_search" and "query" not in params:
            params["query"] = task
            params.setdefault("num_results", 5)
        elif tool_name == "yahoo_finance" and "symbol" not in params:
            symbol_match = re.search(r'\b([A-Z]{1,5}(?:\.[A-Z]{2})?)\b', task.upper())
            if symbol_match:
                params["symbol"] = symbol_match.group(1)
            params.setdefault("action", "quote")
        elif tool_name == "calculator" and "expression" not in params:
            expr_match = re.search(r'[\d\+\-\*\/\(\)\^\.\s%]+', task)
            params["expression"] = expr_match.group().strip() if expr_match else task
        return params

    def _fallback_detect_tool(self, task: str) -> Optional[List[Tuple[str, Dict[str, Any]]]]:
        """Fallback keyword-based tool detection if LLM detection fails."""
        task_lower = task.lower()

        # Currency patterns - need both exchange rate AND web context
        currency_keywords = [
            "rupiah", "idr", "dollar", "usd", "kurs", "nilai tukar", "exchange rate",
            "mata uang", "currency", "forex", "valas"
        ]
        info_keywords = [
            "news", "berita", "terbaru", "latest", "update", "analisa", "analysis",
            "harga", "berapa", "saat ini", "hari ini", "sekarang", "current", "today", "now", "price", "rate"
        ]

        if any(ck in task_lower for ck in currency_keywords) and any(ik in task_lower for ik in info_keywords):
            return [
                ("yahoo_finance", {"symbol": "IDR=X", "action": "quote"}),
                ("web_search", {"query": task, "num_results": 5}),
            ]

        # Indonesian stock market patterns - need both IHSG data AND web analysis
        indo_stock_keywords = [
            "ihsg", "idx", "bursa indonesia", "pasar indonesia", "saham indonesia",
            "stock indonesia", "bei", "bursa efek", "indonesian stock", "indonesian market"
        ]
        stock_action_keywords = [
            "terbaik", "best", "top", "teratas", "naik", "turun", "gain", "loss",
            "minggu", "week", "bulan", "month", "hari", "day", "performance", "performa"
        ]

        if any(ik in task_lower for ik in indo_stock_keywords) and any(sk in task_lower for sk in stock_action_keywords):
            return [
                ("yahoo_finance", {"symbol": "^JKSE", "action": "history", "period": "1mo"}),
                ("web_search", {"query": task, "num_results": 5}),
            ]

        # RAG patterns (English + Indonesian)
        rag_keywords = [
            "document", "pdf", "file", "uploaded", "sop", "company", "my files", "knowledge base", "manual", "handbook",
            "dokumen", "berkas", "file saya", "perusahaan", "panduan", "buku pegangan"
        ]
        if any(kw in task_lower for kw in rag_keywords):
            return [("rag_search", {"query": task, "top_k": 5})]

        # Yahoo Finance patterns (stock-specific queries)
        # Check for stock symbols (uppercase letters, optionally with .JK, .HK, etc.)
        stock_symbol_match = re.search(r'\b([A-Z]{1,5}(?:\.[A-Z]{2})?)\b', task.upper())
        stock_keywords = [
            "stock price", "share price", "stock quote", "ticker", "market cap",
            "pe ratio", "dividend", "financials", "earnings",
            "harga saham", "ihsg", "idx", "bursa"
        ]
        if stock_symbol_match and any(kw in task_lower for kw in stock_keywords):
            symbol = stock_symbol_match.group(1)
            # Determine action based on keywords
            action = "quote"
            if any(kw in task_lower for kw in ["history", "historical", "chart", "grafik", "historis"]):
                action = "history"
            elif any(kw in task_lower for kw in ["info", "about", "company", "tentang"]):
                action = "info"
            elif any(kw in task_lower for kw in ["financial", "revenue", "income", "keuangan", "pendapatan"]):
                action = "financials"
            elif any(kw in task_lower for kw in ["news", "berita"]):
                action = "news"
            return [("yahoo_finance", {"symbol": symbol, "action": action})]

        # Web search patterns (English + Indonesian)
        web_keywords = [
            "search", "latest", "news", "current", "today", "weather", "price",
            "cari", "terbaru", "berita", "sekarang", "hari ini", "cuaca", "harga",
            "lihat web", "temukan", "cek", "update"
        ]
        if any(kw in task_lower for kw in web_keywords):
            return [("web_search", {"query": task, "num_results": 5})]

        # Time patterns (English + Indonesian)
        if any(word in task_lower for word in ["time", "what time", "current time", "jam berapa", "waktu sekarang"]):
            return [("get_current_time", {"timezone": "Asia/Jakarta"})]

        return None

    # =========================================================================
    # File Generation Helpers
    # =========================================================================

    _FILE_FORMAT_KEYWORDS: Dict[str, List[str]] = {
        "xlsx": ["excel", "xlsx", "spreadsheet", "xls"],
        "csv": ["csv", "comma separated", "comma-separated"],
        "docx": ["word document", "docx", "ms word", "word file"],
        "pptx": ["powerpoint", "pptx", "presentation", "slide deck", "slides"],
        "pdf": ["pdf"],
    }

    _GENERATION_KEYWORDS = [
        "create", "generate", "make", "build", "produce", "export", "write",
        "download", "save as", "give me a", "give me an",
        # Indonesian
        "buat", "buat laporan", "buat file", "buat dokumen", "buat presentasi",
        "ekspor", "simpan sebagai", "unduh", "cetak", "generate", "hasilkan",
    ]

    _RAG_SIGNALS = [
        "document", "my file", "uploaded", "from my", "based on my",
        "knowledge base", "report from", "extract from", "from the",
        "dokumen", "file saya", "berdasarkan", "dari dokumen", "dari file",
    ]

    def _detect_file_request(self, task: str) -> Tuple[Optional[str], str]:
        """Return (format, filename) if this is a file-generation request, else (None, '')."""
        tl = task.lower()
        has_gen_intent = any(kw in tl for kw in self._GENERATION_KEYWORDS)
        if not has_gen_intent:
            return None, ""
        for fmt, keywords in self._FILE_FORMAT_KEYWORDS.items():
            if any(kw in tl for kw in keywords):
                return fmt, self._derive_filename(task, fmt)
        # "report" alone with generation intent → default to xlsx
        if any(w in tl for w in ["report", "laporan", "table", "tabel"]):
            return "xlsx", self._derive_filename(task, "xlsx")
        return None, ""

    def _derive_filename(self, task: str, fmt: str) -> str:
        """Derive a sensible filename from the task description."""
        stopwords = {
            "create", "generate", "make", "build", "an", "a", "the", "me",
            "give", "export", "download", "please", "buat", "buat", "tolong",
            "excel", "xlsx", "csv", "pdf", "word", "docx", "pptx",
            "powerpoint", "spreadsheet", "presentation", "document", "report",
            "laporan", "dokumen", "presentasi",
        }
        words = [w for w in task.lower().split() if w not in stopwords and w.isalnum()]
        base = "_".join(words[:5]) if words else "document"
        return f"{base}.{fmt}"

    async def _llm_build_file_content(
        self, task: str, fmt: str, observations: List[str]
    ) -> Dict[str, Any]:
        """Ask the LLM to construct a file content JSON from retrieved data."""
        obs_block = ("\n\nRetrieved data to use:\n" + "\n\n".join(observations)) if observations else ""

        fmt_hint = {
            "xlsx": 'use "sheets": [{"name":"Sheet1","headers":[...],"rows":[[...]]}]',
            "csv":  'use "sheets": [{"name":"Sheet1","headers":[...],"rows":[[...]]}]',
            "docx": 'use "sections": [{"heading":"...","level":1,"content":"...","table":{...}}]',
            "pdf":  'use "sections": [{"heading":"...","level":1,"content":"...","bullets":["..."],"table":{...}}]',
            "pptx": 'use "slides": [{"title":"...","bullets":["..."],"table":{...}}]',
        }.get(fmt, 'use "sections"')

        prompt = f"""Build a content JSON for a {fmt.upper()} file.

User request: {task}{obs_block}

Output ONLY valid JSON matching this schema:
{{
  "title": "...",
  "{('sheets' if fmt in ('xlsx','csv') else 'slides' if fmt == 'pptx' else 'sections')}": [...]
}}

Schema hint for {fmt}: {fmt_hint}

Rules:
- Fill in REAL data from the retrieved information above (if any).
- If no data was retrieved, create a realistic example based on the user's request.
- Every table must have "headers" and "rows".
- Keep row values as plain strings or numbers.
- Output ONLY the JSON object, no markdown, no explanation.

JSON:"""

        messages = [{"role": "user", "content": prompt}]
        try:
            response = await self.ai_service.generate_response(messages, use_agent_model=True)
            self._log(f"LLM file content raw: {response[:200]}...")
            json_match = re.search(r'\{.*\}', response.strip(), re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            self._log(f"LLM file content error: {e}")

        # Fallback skeleton
        return {"title": task[:60], "sections": [{"heading": "Content", "content": task}]}

    async def _handle_file_generation(
        self,
        task: str,
        fmt: str,
        filename: str,
        context: Optional[List[Dict[str, str]]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Dedicated handler for file-generation requests."""
        observations: List[str] = []

        # Step 1 — optionally pull data from the knowledge base
        needs_rag = any(kw in task.lower() for kw in self._RAG_SIGNALS)
        if needs_rag:
            yield {"type": "thought", "content": "Searching documents to populate the file…"}
            yield {"type": "action", "tool": "rag_search", "input": {"query": task, "top_k": 10}}
            rag_result = await self.executor.execute("rag_search", {"query": task, "top_k": 10})
            obs = rag_result.to_observation()
            observations.append(obs)
            yield {"type": "observation", "result": obs, "status": rag_result.status.value}

        # Step 2 — ask LLM to structure the content JSON
        yield {"type": "thought", "content": f"Building {fmt.upper()} content structure…"}
        content = await self._llm_build_file_content(task, fmt, observations)

        # Step 3 — call generate_file
        gen_params = {
            "format": fmt,
            "filename": filename.rsplit(".", 1)[0],
            "content": json.dumps(content, ensure_ascii=False),
        }
        yield {"type": "thought", "content": f"Generating {fmt.upper()} file…"}
        yield {"type": "action", "tool": "generate_file", "input": gen_params}
        file_result = await self.executor.execute("generate_file", gen_params)
        yield {"type": "observation", "result": file_result.to_observation(), "status": file_result.status.value}

        # Step 4 — compose final answer
        if file_result.status == ExecutionStatus.SUCCESS and isinstance(file_result.result, dict):
            r = file_result.result
            dl_url = r.get("download_url", "")
            dl_name = r.get("filename", filename)
            answer = (
                f"Your {fmt.upper()} file is ready!\n\n"
                f"[{dl_name}]({dl_url})\n\n"
                f"Click the link above to download."
            )
        else:
            err = file_result.error or "unknown error"
            answer = f"Sorry, I could not generate the file: {err}"

        self.trace.final_answer = answer
        self.trace.success = file_result.status == ExecutionStatus.SUCCESS
        yield {"type": "final_answer", "content": answer, "sources": []}

    async def run(
        self,
        task: str,
        context: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the agent loop for a given task.

        Yields events as the agent progresses:
        - {"type": "thought", "content": "..."}
        - {"type": "action", "tool": "...", "input": {...}}
        - {"type": "observation", "result": "..."}
        - {"type": "final_answer", "content": "...", "sources": [...]}
        - {"type": "error", "message": "..."}

        Args:
            task: The task/question to solve
            context: Optional conversation context

        Yields:
            Event dictionaries as the agent progresses
        """
        start_time = time.time()
        self.trace = AgentTrace(task=task)
        self.state = AgentState.THINKING

        self._log("=" * 60)
        self._log("AGENT RUN STARTED")
        self._log(f"TASK: {task[:120]}")
        self._log("=" * 60)

        # File generation fast path — runs before the normal tool detection
        file_fmt, file_name = self._detect_file_request(task)
        if file_fmt:
            self._log(f"FILE GENERATION REQUEST: format={file_fmt} filename={file_name}")
            async for event in self._handle_file_generation(task, file_fmt, file_name, context):
                yield event
            await self.executor.close()
            self.trace.total_time = time.time() - start_time
            self._log(f"File generation done in {self.trace.total_time:.2f}s")
            return

        # FORCED TOOL CALL: Use LLM to detect if we should auto-execute tool(s) first
        forced_tools = await self._detect_required_tool(task)
        initial_observations = []

        if not forced_tools:
            self._log("⚠ NO TOOLS DETECTED — falling back to ReAct loop")

        if forced_tools:
            tool_names = [t[0] for t in forced_tools]
            self._log("=" * 50)
            self._log(f"TOOLS DETECTED : {len(forced_tools)}")
            for i, (tn, _) in enumerate(forced_tools, 1):
                self._log(f"  [{i}] {tn}")
            self._log("=" * 50)

            if len(forced_tools) > 1:
                yield {"type": "thought", "content": f"I need to use multiple tools ({', '.join(tool_names)}) to get comprehensive information for this task."}
            else:
                yield {"type": "thought", "content": f"I need to use {tool_names[0]} to get current information for this task."}

            # Execute all tools
            for idx, (tool_name, tool_params) in enumerate(forced_tools):
                self._log(f"RUNNING TOOL [{idx+1}/{len(forced_tools)}]: {tool_name}")

                # Yield action
                yield {"type": "action", "tool": tool_name, "input": tool_params}

                # Execute the tool
                result = await self.executor.execute(tool_name, tool_params)
                observation = result.to_observation()
                initial_observations.append(f"[{tool_name}]\n{observation}")

                self._log(f"TOOL [{idx+1}] DONE: status={result.status.value}")
                yield {"type": "observation", "result": observation, "status": result.status.value}

                # Track sources as structured dicts for citation rendering
                if result.status == ExecutionStatus.SUCCESS:
                    if tool_name == "web_search" and isinstance(result.result, dict):
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
                    elif tool_name == "rag_search" and isinstance(result.result, dict):
                        for r in result.result.get("results", []):
                            if r.get("source") and not any(
                                isinstance(s, dict) and s.get("name") == r["source"]
                                for s in self.trace.sources
                            ):
                                self.trace.sources.append({
                                    "type": "doc",
                                    "name": r["source"],
                                })

                # Record the step
                step = AgentStep(
                    step_number=idx + 1,
                    state=AgentState.OBSERVING,
                    thought=f"Using {tool_name} to get information",
                    action=tool_name,
                    action_input=tool_params,
                    observation=observation,
                )
                self.trace.steps.append(step)

        # Combine all observations
        initial_observation = "\n\n".join(initial_observations) if initial_observations else None

        # Build messages for LLM
        system_prompt = """You are ALAI, a helpful AI assistant. You have access to real-time information through tools.

When given search results or tool outputs, summarize the information clearly and helpfully.
Always cite your sources when providing information from search results.
Be concise but thorough in your responses.

IMPORTANT: Always respond in the SAME LANGUAGE as the user's question. If the user asks in Bahasa Indonesia, respond in Bahasa Indonesia. If the user asks in English, respond in English."""

        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation context if provided
        if context:
            for msg in context[-10:]:
                messages.append(msg)

        # Build the task message with tool results if we have them
        if initial_observation:
            # Build numbered reference list so the LLM can use inline citations
            citation_lines = []
            for i, src in enumerate(self.trace.sources, 1):
                if isinstance(src, dict):
                    if src["type"] == "web":
                        citation_lines.append(f"[{i}] {src['title']} — {src['url']}")
                    else:
                        citation_lines.append(f"[{i}] Document: {src['name']}")
                else:
                    citation_lines.append(f"[{i}] {src}")

            citations_block = (
                "\n\nSources (use [1], [2], etc. inline):\n" + "\n".join(citation_lines)
                if citation_lines else ""
            )

            task_message = f"""User's question: {task}

Retrieved information:
{initial_observation}{citations_block}

Instructions:
- Answer the user's question using ONLY the retrieved information above.
- When you state a fact, add an inline citation like [1] or [2] referencing the source number above.
- Respond in the same language as the user's question."""
        else:
            # No forced tool - use original ReAct approach
            format_instructions = get_react_format_instructions()
            task_message = f"""{format_instructions}

**Task:** {task}

Begin!"""

        messages.append({"role": "user", "content": task_message})

        # If we already did a forced tool call, just get the LLM to summarize
        if initial_observation:
            self._log("Getting LLM to summarize tool results...")
            try:
                response = await self._get_ai_response(messages)
                self._log(f"Summary response: {response[:200]}...")

                self.state = AgentState.COMPLETE
                self.trace.final_answer = response
                self.trace.success = True

                yield {
                    "type": "final_answer",
                    "content": response,
                    "sources": self.trace.sources,
                }

                # Cleanup
                await self.executor.close()
                self.trace.total_time = time.time() - start_time
                self._log(f"Task completed in {self.trace.total_time:.2f}s")
                return

            except Exception as e:
                self._log(f"Error getting summary: {e}")
                yield {"type": "error", "message": str(e)}
                await self.executor.close()
                return

        # No forced tool - fall back to ReAct loop
        step_number = 0
        tools_used = 0

        while step_number < self.max_steps:
            step_number += 1
            self._log(f"Step {step_number}/{self.max_steps}")

            step = AgentStep(step_number=step_number, state=AgentState.THINKING)
            self.trace.steps.append(step)

            # Get AI response
            try:
                response = await self._get_ai_response(messages)
                self._log(f"Raw response: {response[:300]}...")
            except Exception as e:
                self._log(f"Error getting AI response: {e}")
                step.state = AgentState.ERROR
                step.error = str(e)
                yield {"type": "error", "message": str(e)}
                break

            # Parse the response
            thought, action, action_input, final_answer = self._parse_response(response)

            step.thought = thought

            # Yield thought
            if thought:
                self._log(f"Thought: {thought[:100]}...")
                yield {"type": "thought", "content": thought}

            # Check for final answer - BUT only allow if at least one tool was used
            if final_answer:
                if tools_used == 0:
                    # Model is trying to answer without using tools - force it to use a tool
                    self._log("Model tried to answer without using tools - forcing tool use")
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": """STOP! You MUST use a tool before answering. You cannot provide a Final Answer without first using a tool to get real information.

For this task, you MUST use web_search to get current information. Do NOT answer from memory.

Respond with:
Thought: I need to search for current information.
Action: web_search
Action Input: {"query": "your search query here"}""",
                    })
                    continue

                self._log(f"Final Answer: {final_answer[:100]}...")
                step.state = AgentState.COMPLETE
                self.state = AgentState.COMPLETE
                self.trace.final_answer = final_answer
                self.trace.success = True

                yield {
                    "type": "final_answer",
                    "content": final_answer,
                    "sources": self.trace.sources,
                }
                break

            # Execute action
            if action:
                # Validate that the action is a known tool
                if not tool_registry.get(action):
                    self._log(f"Unknown tool: {action}")
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": f"Error: '{action}' is not a valid tool. Available tools: web_search, rag_search, calculator, read_url, get_current_time. Please use a valid tool.",
                    })
                    continue

                step.action = action
                step.action_input = action_input
                step.state = AgentState.ACTING
                tools_used += 1

                self._log(f"RUNNING TOOL: {action}")
                yield {"type": "action", "tool": action, "input": action_input}

                # Execute the tool
                result = await self.executor.execute(action, action_input or {})

                step.state = AgentState.OBSERVING
                observation = result.to_observation()
                step.observation = observation

                self._log(f"TOOL DONE: status={result.status.value}")
                yield {"type": "observation", "result": observation, "status": result.status.value}

                # Track sources
                if result.status == ExecutionStatus.SUCCESS:
                    if action == "rag_search" and isinstance(result.result, dict):
                        for r in result.result.get("results", []):
                            if r.get("source") and not any(
                                isinstance(s, dict) and s.get("name") == r["source"]
                                for s in self.trace.sources
                            ):
                                self.trace.sources.append({"type": "doc", "name": r["source"]})
                    elif action == "web_search" and isinstance(result.result, dict):
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

                # Add to messages for next iteration
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": f"Observation: {observation}\n\nBased on this real information, continue with your reasoning. If you have enough information, provide your Final Answer.",
                })
            else:
                # No action and no final answer - model isn't following format
                self._log("No action or final answer - forcing tool use")
                messages.append({"role": "assistant", "content": response})

                # Determine what tool to suggest based on the task
                suggested_tool = "web_search"
                if any(word in task.lower() for word in ["document", "file", "pdf", "knowledge"]):
                    suggested_tool = "rag_search"
                elif any(word in task.lower() for word in ["calculate", "math", "compute"]):
                    suggested_tool = "calculator"
                elif any(word in task.lower() for word in ["time", "date", "clock"]):
                    suggested_tool = "get_current_time"

                messages.append({
                    "role": "user",
                    "content": f"""You did not follow the required format. You MUST respond with:

Thought: [your reasoning]
Action: {suggested_tool}
Action Input: {{"query": "relevant search query"}}

Try again with the correct format.""",
                })

        # Check if we hit max steps
        if step_number >= self.max_steps and self.state != AgentState.COMPLETE:
            self._log("Max steps reached without completion")
            self.state = AgentState.ERROR
            yield {
                "type": "error",
                "message": f"Agent reached maximum steps ({self.max_steps}) without completing the task.",
            }

        # Cleanup
        await self.executor.close()

        self.trace.total_time = time.time() - start_time
        self._log(f"Task completed in {self.trace.total_time:.2f}s")

    async def _get_ai_response(self, messages: List[Dict[str, str]]) -> str:
        """Get response from AI service using the agent model for complex reasoning."""
        # Use non-streaming for agent loop (need full response to parse)
        # Use agent model (qwen2.5:14b) for better reasoning capabilities
        response = await self.ai_service.generate_response(messages, use_agent_model=True)
        return response

    def _parse_response(
        self,
        response: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]], Optional[str]]:
        """
        Parse AI response to extract thought, action, and final answer.

        Expected format:
        Thought: <reasoning>
        Action: <tool_name>
        Action Input: <json parameters>

        OR

        Thought: <reasoning>
        Final Answer: <answer>

        Returns:
            Tuple of (thought, action, action_input, final_answer)
        """
        thought = None
        action = None
        action_input = None
        final_answer = None

        # Extract thought
        thought_match = re.search(
            r"Thought:\s*(.+?)(?=Action:|Final Answer:|$)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            thought = thought_match.group(1).strip()

        # Check for final answer first
        final_match = re.search(
            r"Final Answer:\s*(.+?)$",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if final_match:
            final_answer = final_match.group(1).strip()
            return thought, None, None, final_answer

        # Extract action
        action_match = re.search(
            r"Action:\s*(\w+)",
            response,
            re.IGNORECASE,
        )
        if action_match:
            action = action_match.group(1).strip()

        # Extract action input
        input_match = re.search(
            r"Action Input:\s*(.+?)(?=Observation:|Thought:|$)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if input_match:
            input_str = input_match.group(1).strip()
            try:
                # Try to parse as JSON
                action_input = json.loads(input_str)
            except json.JSONDecodeError:
                # Try to extract JSON from the string
                json_match = re.search(r"\{.*\}", input_str, re.DOTALL)
                if json_match:
                    try:
                        action_input = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        # Fall back to simple key-value extraction
                        action_input = {"input": input_str}
                else:
                    action_input = {"input": input_str}

        return thought, action, action_input, final_answer

    async def run_streaming(
        self,
        task: str,
        context: Optional[List[Dict[str, str]]] = None,
        show_steps: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        Run agent with streaming output for real-time display.

        Args:
            task: The task/question to solve
            context: Optional conversation context
            show_steps: If True, show thinking/tool steps. If False, only show final answer.

        Yields formatted strings suitable for SSE streaming.
        """
        async for event in self.run(task, context):
            event_type = event.get("type")

            if event_type == "thought" and show_steps:
                yield f"🤔 **Thinking:** {event['content']}\n\n"

            elif event_type == "action" and show_steps:
                tool = event.get("tool")
                tool_input = event.get("input", {})
                yield f"🔧 **Using tool:** `{tool}`\n"
                if tool_input:
                    yield f"```json\n{json.dumps(tool_input, indent=2)}\n```\n\n"

            elif event_type == "observation" and show_steps:
                result = event.get("result", "")
                status = event.get("status", "")
                if status == "success":
                    yield f"📋 **Result:**\n```\n{result[:1000]}\n```\n\n"
                else:
                    yield f"⚠️ **{status}:** {result}\n\n"

            elif event_type == "final_answer":
                content = event.get("content", "")
                sources = event.get("sources", [])
                yield content
                if sources:
                    yield "\n\n---\n\n**Sources:**\n"
                    for i, src in enumerate(sources[:10], 1):
                        if isinstance(src, dict):
                            if src["type"] == "web":
                                title = src.get("title") or src["url"]
                                yield f"[{i}] [{title}]({src['url']})\n"
                            else:
                                yield f"[{i}] 📄 {src['name']}\n"
                        elif str(src).startswith("http"):
                            yield f"[{i}] {src}\n"
                        else:
                            yield f"[{i}] 📄 {src}\n"

            elif event_type == "error":
                yield f"\n❌ **Error:** {event.get('message')}\n"
