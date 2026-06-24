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
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

from app.agent.tools import tool_registry, Tool
from app.agent.executor import ToolExecutor, ToolResult, ExecutionStatus
from app.agent.prompts import get_agent_system_prompt, get_react_format_instructions
from app.models.report_template import ReportTemplate
from app.services.smart_llm import SmartLLM

# In-memory store for email drafts pending user confirmation.
# Keyed by user_id so each user has an independent pending set.
_email_draft_cache: Dict[int, List[Dict[str, Any]]] = {}


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
7. email_read - Read, list, or search the user's Outlook email. Params: action (list/read/search), folder (inbox/sent/drafts), top (number), message_id, query
8. email_send - Send a new email. Params: to, subject, body, cc (optional)
9. email_reply - Reply to an email. Params: message_id, body, reply_all (optional bool)

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
- "What's in my company SOP about leave?" → {{"tools": [{{"tool": "rag_search", "params": {{"query": "leave policy", "top_k": 5, "source_filter": "SOP"}}}}], "reason": "SOP document search"}}
- "Steps to develop new product based on company SOP?" → {{"tools": [{{"tool": "rag_search", "params": {{"query": "new product development steps", "top_k": 8, "source_filter": "SOP"}}}}], "reason": "SOP document search"}}
- "Latest AI news?" → {{"tools": [{{"tool": "web_search", "params": {{"query": "latest AI news", "num_results": 5}}}}], "reason": "current information"}}
- "Calculate 15% of 250" → {{"tools": [{{"tool": "calculator", "params": {{"expression": "0.15 * 250"}}}}], "reason": "math"}}
- "Show me my inbox" → {{"tools": [{{"tool": "email_read", "params": {{"action": "list", "folder": "inbox", "top": 10}}}}], "reason": "read email inbox"}}
- "Search my emails about project alpha" → {{"tools": [{{"tool": "email_read", "params": {{"action": "search", "query": "project alpha"}}}}], "reason": "email search"}}
- "Send an email to john@example.com about the meeting" → {{"tools": [{{"tool": "email_send", "params": {{"to": "john@example.com", "subject": "Meeting", "body": "..."}}}}], "reason": "send email"}}
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

    # Keywords that indicate the user wants only SOP / policy documents
    _SOP_KEYWORDS = [
        "sop", "standard operating procedure", "prosedur", "kebijakan",
        "policy", "peraturan", "regulation", "company policy", "company sop",
        "company document", "company manual", "panduan perusahaan",
    ]

    def _infer_rag_source_filter(self, task: str) -> Optional[str]:
        """Return a filename source_filter if the task clearly targets a specific document type."""
        tl = task.lower()
        if any(kw in tl for kw in self._SOP_KEYWORDS):
            return "SOP"
        return None

    def _ensure_tool_params(self, tool_name: str, params: Dict[str, Any], task: str) -> Dict[str, Any]:
        """Fill in missing required parameters for a tool."""
        if tool_name == "rag_search":
            if "query" not in params:
                params["query"] = task
            params.setdefault("top_k", 5)
            # Auto-inject source_filter when the task targets a specific document type
            if "source_filter" not in params or not params["source_filter"]:
                sf = self._infer_rag_source_filter(task)
                if sf:
                    params["source_filter"] = sf
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
            rag_params: Dict[str, Any] = {"query": task, "top_k": 5}
            sf = self._infer_rag_source_filter(task)
            if sf:
                rag_params["source_filter"] = sf
            return [("rag_search", rag_params)]

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

        # Email patterns
        email_read_keywords = [
            "inbox", "my email", "my emails", "my mail", "read email",
            "check email", "show email", "list email", "email from",
            "email about", "search email", "find email", "unread",
        ]
        email_send_keywords = [
            "send email", "send an email", "compose email", "write email",
            "email to ", "draft email",
        ]
        email_reply_keywords = [
            "reply to email", "reply email", "respond to email",
            "reply to the email", "reply to this email",
        ]

        if any(kw in task_lower for kw in email_reply_keywords):
            return [("email_reply", {"message_id": "", "body": task})]
        if any(kw in task_lower for kw in email_send_keywords):
            return [("email_send", {"to": "", "subject": "", "body": ""})]
        if any(kw in task_lower for kw in email_read_keywords):
            action = "search" if "search" in task_lower or "find" in task_lower or "about" in task_lower else "list"
            return [("email_read", {"action": action, "folder": "inbox", "top": 10})]

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
        "download", "save as", "give me a", "give me an", "new", "prepare",
        # Indonesian
        "buat", "buat laporan", "buat file", "buat dokumen", "buat presentasi",
        "ekspor", "simpan sebagai", "unduh", "cetak", "hasilkan",
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
        self,
        task: str,
        fmt: str,
        observations: List[str],
        template_sections: Optional[List[Dict[str, Any]]] = None,
        template_file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ask the LLM to construct a file content JSON from retrieved data."""
        from datetime import date as _date_cls
        import re as _re

        # Extract live Yahoo Finance values and surface them as verified facts so
        # the LLM cannot substitute training-data numbers.
        verified_facts: List[str] = []
        for obs in observations:
            if "[Yahoo Finance" not in obs:
                continue
            # Current rate / quote
            rate_m = _re.search(r'"rate"\s*:\s*([\d.,]+)', obs)
            price_m = _re.search(r'"price"\s*:\s*([\d.,]+)', obs)
            sym_m = _re.search(r'"symbol"\s*:\s*"([^"]+)"', obs)
            desc_m = _re.search(r'"description"\s*:\s*"([^"]+)"', obs)
            if (rate_m or price_m) and sym_m:
                val = rate_m.group(1) if rate_m else price_m.group(1)
                desc = desc_m.group(1) if desc_m else sym_m.group(1)
                verified_facts.append(
                    f"- {desc}: {val} (as of {_date_cls.today().strftime('%d %B %Y')})"
                )
            # History close prices — grab the last entry
            closes = _re.findall(r'"close"\s*:\s*([\d.]+)', obs)
            dates_h = _re.findall(r'"date"\s*:\s*"([^"]+)"', obs)
            if closes and dates_h:
                verified_facts.append(
                    f"- Most recent close in history: {closes[-1]} on {dates_h[-1]}"
                )

        facts_block = ""
        if verified_facts:
            unique_facts = list(dict.fromkeys(verified_facts))  # deduplicate
            facts_block = (
                "\n\nVERIFIED LIVE DATA — use these exact numbers, do NOT substitute "
                "with training knowledge:\n" + "\n".join(unique_facts) +
                "\n\nCURRENCY INTERPRETATION RULE (critical): For all USD/XXX pairs "
                "(USD/IDR, USD/EUR, USD/SGD, etc.) a HIGHER rate means the USD strengthened "
                "and the local currency WEAKENED. A LOWER rate means the local currency "
                "STRENGTHENED. Example: USD/IDR rising from 16,000 to 17,000 means the "
                "rupiah WEAKENED, NOT strengthened. Always describe direction from the "
                "local currency's perspective."
            )

        obs_block = ("\n\nResearch data collected:\n" + "\n\n---\n\n".join(observations)) if observations else ""

        key = 'sheets' if fmt in ('xlsx', 'csv') else 'slides' if fmt == 'pptx' else 'sections'

        # Template path: pre-build the skeleton with EXACT headings so the LLM
        # can only fill content — headings are also enforced after parsing.
        if template_sections:
            skeleton: List[Dict[str, Any]] = []
            for s in template_sections:
                if fmt == 'pptx':
                    skeleton.append({"title": s.get("heading", ""), "bullets": []})
                else:
                    entry: Dict[str, Any] = {
                        "heading": s.get("heading", ""),
                        "level": s.get("level", 1),
                        "content": "",
                        "bullets": [],
                    }
                    if s.get("has_table"):
                        entry["table"] = {
                            "headers": s.get("table_headers", []),
                            "rows": [],
                        }
                    skeleton.append(entry)

            today_str = _date_cls.today().strftime("%d %B %Y")

            prompt = f"""You are a professional analyst writing a structured report.
Today's date: {today_str}{facts_block}

User request: {task}{obs_block}

Fill in the template skeleton below using ONLY content from the research data above.
The section headings are FIXED — do not rename, add, or remove any section.

Skeleton to fill:
{{
  "title": "Write a descriptive title here",
  "{key}": {json.dumps(skeleton, indent=2, ensure_ascii=False)}
}}

CRITICAL DATA RULES — violation is not acceptable:
1. SOURCE PRIORITY: [Yahoo Finance] and [Web Search] data is AUTHORITATIVE for all market rates,
   prices, exchange rates, and news. Use those numbers exactly as given.
2. KNOWLEDGE BASE WARNING: Any [Knowledge Base] content may be years old. NEVER quote rates,
   prices, or percentages from knowledge base sources — use them only for definitions or background.
3. NO HALLUCINATION: If a number is not in the research data above, write "data not available"
   rather than inventing or recalling a value.
4. RECENCY: Use ONLY the rates listed in "VERIFIED LIVE DATA" above. Your training data
   contains old historical rates that are WRONG for this report. Never use memorised rates.
5. CURRENCY DIRECTION: For USD/IDR, USD/EUR, USD/SGD and all other USD/XXX pairs — a HIGHER
   rate means the local currency WEAKENED (more units needed per USD). A LOWER rate means the
   local currency STRENGTHENED. Never describe a rising USD/IDR as "rupiah strengthening".
6. Every "heading" must stay EXACTLY as written — do not change a single word.
7. "content": write EXACTLY 2 full paragraphs (4-6 sentences each) with specific numbers,
   dates, and context from [Yahoo Finance]/[Web Search]. Do not write a single short paragraph.
8. "bullets": 4-6 concise points with exact figures sourced from live data.
9. table "rows": real data rows matching the column headers, from live sources only.
10. Output ONLY the completed JSON object — no markdown fences, no explanation.

JSON:"""

            # Convert PDF template to an image so the vision model can see the layout
            template_image_paths: List[str] = []
            if template_file_path and template_file_path.endswith(".pdf"):
                try:
                    import fitz  # PyMuPDF
                    import tempfile
                    pdf_doc = fitz.open(template_file_path)
                    for page_num in range(min(2, len(pdf_doc))):
                        page = pdf_doc[page_num]
                        mat = fitz.Matrix(2.0, 2.0)  # 2× zoom for clarity
                        pix = page.get_pixmap(matrix=mat)
                        tmp = tempfile.NamedTemporaryFile(
                            suffix=f"_tpl_p{page_num}.png",
                            delete=False,
                        )
                        tmp_path = tmp.name
                        tmp.close()  # close handle before fitz writes (required on Windows)
                        pix.save(tmp_path)
                        template_image_paths.append(tmp_path)
                    pdf_doc.close()
                    if template_image_paths:
                        prompt = (
                            "The following image(s) show the visual template that must be "
                            "used as a style reference — note the logo, color scheme, fonts, "
                            "header/footer layout, and section structure. Generate the report "
                            "content JSON so the report mirrors this visual style.\n\n"
                            + prompt
                        )
                        self._log(f"Sending {len(template_image_paths)} template page(s) to vision model")
                except Exception as e:
                    self._log(f"PDF→image conversion failed: {e}")

            messages = [{"role": "user", "content": prompt}]
            try:
                _content_llm = SmartLLM(timeout=120.0)
                response = await _content_llm.complete(prompt, max_tokens=8192)
                self._log(f"LLM file content raw: {response[:200]}...")
                json_match = re.search(r'\{.*\}', response.strip(), re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    # Hard-enforce headings and section count from template
                    sections = result.get(key, [])
                    for i, tpl_s in enumerate(template_sections):
                        if i < len(sections):
                            if fmt == 'pptx':
                                sections[i]["title"] = tpl_s.get("heading", "")
                            else:
                                sections[i]["heading"] = tpl_s.get("heading", "")
                                sections[i]["level"] = tpl_s.get("level", 1)
                        else:
                            # LLM produced fewer sections than the template — add empty ones
                            sections.append(skeleton[i])
                    result[key] = sections[:len(template_sections)]
                    return result
            except Exception as e:
                self._log(f"LLM file content error: {e}")
            finally:
                # Clean up temp PNG files created from PDF pages
                for p in template_image_paths:
                    try:
                        Path(p).unlink(missing_ok=True)
                    except OSError:
                        pass
            return {"title": task[:60], key: skeleton}

        # No template — default structure
        fmt_hint = {
            "xlsx": 'use "sheets": [{"name":"Sheet1","headers":[...],"rows":[[...]]}]',
            "csv":  'use "sheets": [{"name":"Sheet1","headers":[...],"rows":[[...]]}]',
            "docx": 'use "sections": [{"heading":"...","level":1,"content":"...","bullets":["..."],"table":{"headers":[...],"rows":[[...]]}}]',
            "pdf":  'use "sections": [{"heading":"...","level":1,"content":"...","bullets":["..."],"table":{"headers":[...],"rows":[[...]]}}]',
            "pptx": 'use "slides": [{"title":"...","bullets":["..."]}]',
        }.get(fmt, 'use "sections"')

        if fmt in ("pdf", "docx"):
            structure_hint = """
For an analysis report include these sections in order:
1. Executive Summary — 2-3 sentence overview of key findings
2. Current Market Data — table with latest rates/prices
3. Trend Analysis — analysis of the trend (direction, highs, lows, volatility)
4. Recent News & Market Sentiment — bullet list of key news headlines and implications
5. Outlook & Key Risks — forward-looking bullets
6. Conclusion — 1-2 sentence wrap-up

Extract exact numbers (prices, rates, percentages, dates) from the research data."""
        else:
            structure_hint = ""

        today_str = _date_cls.today().strftime("%d %B %Y")

        prompt = f"""You are a professional analyst. Build a detailed content JSON for a {fmt.upper()} report.
Today's date: {today_str}{facts_block}

User request: {task}{obs_block}
{structure_hint}

Output ONLY a valid JSON object with this top-level shape:
{{
  "title": "<descriptive report title>",
  "{key}": [...]
}}

Schema hint for {fmt}: {fmt_hint}

CRITICAL DATA RULES — violation is not acceptable:
- SOURCE PRIORITY: [Yahoo Finance] and [Web Search] data is AUTHORITATIVE for all market rates,
  prices, and news. Use those exact numbers.
- KNOWLEDGE BASE WARNING: [Knowledge Base] content may be years old. NEVER quote rates or prices
  from knowledge base sources. Use them only for definitions or background context.
- NO HALLUCINATION: If a number is not in the research data above, write "data not available".
  Do NOT recall or invent any rate, price, or statistic.
- RECENCY: Use ONLY the rates listed in "VERIFIED LIVE DATA" above. Your training data
  contains stale historical rates — never use memorised numbers for market data.
- CURRENCY DIRECTION: For USD/IDR, USD/EUR, USD/SGD and all USD/XXX pairs — a HIGHER rate
  means the local currency WEAKENED. A LOWER rate means it STRENGTHENED. Never describe a
  rising USD/IDR as "rupiah strengthening" or "positive performance for the rupiah".
- Every table must have "headers" (array of strings) and "rows" (array of arrays).
- "content" fields: plain paragraph text with specific numbers from live sources.
- "bullets" fields: short strings with exact figures from [Yahoo Finance] or [Web Search].
- Output ONLY the JSON object — no markdown fences, no explanation.

JSON:"""

        try:
            _content_llm = SmartLLM(timeout=120.0)
            response = await _content_llm.complete(prompt, max_tokens=8192)
            self._log(f"LLM file content raw: {response[:200]}...")
            json_match = re.search(r'\{.*\}', response.strip(), re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            self._log(f"LLM file content error: {e}")

        return {"title": task[:60], key: []}

    # Mapping of keyword → (yfinance symbol, human label)
    _FINANCE_SIGNALS: List[Tuple[List[str], str, str]] = [
        (["rupiah", " idr", "idr "],          "IDR=X",  "USD/IDR (Rupiah)"),
        (["sgd", "singapore dollar",
          "singapore dollar"],                 "SGD=X",  "USD/SGD (Singapore Dollar)"),
        (["euro", " eur", "eur "],             "EUR=X",  "USD/EUR (Euro)"),
        (["pound", " gbp", "gbp "],            "GBP=X",  "USD/GBP (British Pound)"),
        (["yen", " jpy", "jpy "],              "JPY=X",  "USD/JPY (Japanese Yen)"),
        (["ringgit", " myr", "myr "],          "MYR=X",  "USD/MYR (Malaysian Ringgit)"),
        (["baht", " thb", "thb "],             "THB=X",  "USD/THB (Thai Baht)"),
        (["yuan", "renminbi", " cny", "cny "], "CNY=X",  "USD/CNY (Chinese Yuan)"),
        (["ihsg", "jkse", "bursa indonesia"],  "^JKSE",  "IHSG (Jakarta Stock Exchange)"),
        (["s&p 500", "sp500", "s&p500"],       "^GSPC",  "S&P 500"),
        (["nasdaq"],                           "^IXIC",  "NASDAQ Composite"),
        (["dow jones", "djia"],                "^DJI",   "Dow Jones"),
    ]

    def _detect_finance_symbols(self, task: str) -> List[Tuple[str, str]]:
        """Return list of (symbol, label) to fetch for this task."""
        tl = " " + task.lower() + " "
        found = []
        seen = set()
        for keywords, symbol, label in self._FINANCE_SIGNALS:
            if symbol not in seen and any(kw in tl for kw in keywords):
                found.append((symbol, label))
                seen.add(symbol)
        return found

    # Targeted Tavily search queries per finance symbol
    _SYMBOL_SEARCH_QUERIES: Dict[str, str] = {
        "IDR=X":  "rupiah IDR USD exchange rate latest news analysis today",
        "SGD=X":  "SGD Singapore dollar USD exchange rate latest news analysis today",
        "EUR=X":  "euro EUR USD exchange rate latest news analysis today",
        "GBP=X":  "GBP pound sterling USD exchange rate news today",
        "JPY=X":  "yen JPY USD exchange rate latest news today",
        "MYR=X":  "ringgit MYR USD exchange rate news today",
        "THB=X":  "baht THB USD exchange rate news today",
        "CNY=X":  "yuan CNY USD exchange rate news today",
        "^JKSE":  "IHSG Jakarta Stock Exchange market news analysis today",
        "^GSPC":  "S&P 500 market news analysis today",
        "^IXIC":  "NASDAQ market news today",
        "^DJI":   "Dow Jones market news today",
    }

    def _derive_search_queries(self, task: str, finance_symbols: List[Tuple[str, str]]) -> List[str]:
        """Build targeted Tavily search queries for each detected finance symbol."""
        queries: List[str] = []
        seen: set = set()
        for symbol, _ in finance_symbols:
            q = self._SYMBOL_SEARCH_QUERIES.get(symbol)
            if q and q not in seen:
                queries.append(q)
                seen.add(q)
        # Add a combined comparison query when two or more symbols detected
        if len(finance_symbols) >= 2:
            short_labels = [label.split(" (")[0] for _, label in finance_symbols]
            comparison_q = f"{' vs '.join(short_labels)} currency comparison analysis"
            if comparison_q not in seen:
                queries.append(comparison_q)
        # Fallback when no finance symbols
        if not queries:
            queries.append(task[:200])
        return queries

    _PLAN_SECTION_SYSTEM = (
        "You are a financial data planner. "
        "Respond ONLY with a valid JSON object — no markdown, no explanation."
    )

    _PLAN_SECTION_PROMPT = """\
A report template has these sections that need to be filled with live data:

{headings}

Determine exactly what data to fetch for each section. Choose from:

Yahoo Finance symbols (use for market/price data):
  IDR=X   USD/IDR (Indonesian Rupiah)
  SGD=X   USD/SGD (Singapore Dollar)
  EUR=X   USD/EUR (Euro)
  GBP=X   USD/GBP (British Pound)
  JPY=X   USD/JPY (Japanese Yen)
  MYR=X   USD/MYR (Malaysian Ringgit)
  CNY=X   USD/CNY (Chinese Yuan)
  ^JKSE   IHSG (Jakarta Stock Exchange / Indonesia index)
  ^GSPC   S&P 500 (US market index)
  ^IXIC   NASDAQ Composite
  ^DJI    Dow Jones Industrial Average

Web search queries (use for data NOT in Yahoo Finance):
  Central bank rates, inflation figures, GDP data, government policy,
  economic news, Bank Indonesia decisions, bond yields, etc.

Rules:
- "Kurs Valuta Asing" / "Exchange Rate" / forex sections → IDR=X + SGD=X + EUR=X + GBP=X + JPY=X
- "Indeks Global" / "Global Index" / world markets → ^GSPC + ^IXIC + ^DJI
- "IHSG" / "Bursa" / Indonesia market → ^JKSE
- "Suku Bunga" / "Interest Rate" / "BI Rate" → web search (not in Yahoo Finance)
- "Inflasi" / "Inflation" / "CPI" → web search
- "GDP" / "Pertumbuhan Ekonomi" → web search
- Include a web search for each section topic for context/news
- Max 8 symbols total, max 6 web queries total
- Already fetched symbols to SKIP: {already_fetched}

Return JSON:
{{
  "symbols": [
    {{"symbol": "IDR=X", "label": "USD/IDR (Rupiah)"}},
    ...
  ],
  "web_queries": [
    "Bank Indonesia BI rate suku bunga terbaru June 2026",
    ...
  ]
}}

JSON:"""

    async def _plan_section_data(
        self,
        sections: List[Dict[str, Any]],
        already_fetched_symbols: set,
    ) -> Tuple[List[Tuple[str, str]], List[str]]:
        """
        Ask SmartLLM what Yahoo Finance symbols and web searches are needed
        to populate the given template sections.
        Returns (extra_symbols [(symbol, label), ...], extra_web_queries [...]).
        """
        headings = [s.get("heading", "").strip() for s in sections if s.get("heading", "").strip()]
        if not headings:
            return [], []

        prompt = self._PLAN_SECTION_PROMPT.format(
            headings="\n".join(f"- {h}" for h in headings),
            already_fetched=", ".join(sorted(already_fetched_symbols)) or "none",
        )

        llm = SmartLLM()
        try:
            raw = await llm.complete(prompt, self._PLAN_SECTION_SYSTEM)
            self._log(f"Section data plan raw: {raw[:300]}")
            m = re.search(r'\{.*\}', raw.strip(), re.DOTALL)
            if not m:
                self._log("Section data plan: no JSON found in response")
                return [], []
            d = json.loads(m.group())

            extra_symbols: List[Tuple[str, str]] = []
            for entry in d.get("symbols", []):
                sym = entry.get("symbol", "").strip()
                label = entry.get("label", sym)
                if sym and sym not in already_fetched_symbols:
                    extra_symbols.append((sym, label))
                    already_fetched_symbols.add(sym)

            extra_queries: List[str] = [
                q.strip() for q in d.get("web_queries", []) if q.strip()
            ]
            self._log(
                f"Section data plan: {len(extra_symbols)} symbols, "
                f"{len(extra_queries)} queries"
            )
            return extra_symbols, extra_queries

        except Exception as e:
            self._log(f"Section data planning error: {e}")
            return [], []

    async def _query_templates(
        self, fmt: Optional[str] = None
    ) -> List[Any]:
        """Return templates visible to this user, optionally filtered by format."""
        if not self.db_session or not self.user_id:
            return []
        from sqlalchemy import or_, select as sa_select
        q = sa_select(ReportTemplate).where(
            or_(
                ReportTemplate.owner_id == self.user_id,
                ReportTemplate.is_company_wide == True,  # noqa: E712
            )
        )
        if fmt:
            q = q.where(ReportTemplate.format == fmt)
        result = await self.db_session.execute(q)
        return list(result.scalars().all())

    def _score_template(self, tpl: Any, task_lower: str) -> int:
        """
        Score a template against the task.
        - Templates with keywords: score = number of keyword hits (0 means no match)
        - Templates with NO keywords: always match with score 1 (lower than any keyword hit)
        Keywords may be comma-separated or space-separated.
        """
        if not tpl.keywords:
            return 1  # no keywords → always applies, lowest priority
        # Support both comma-separated and space-separated keyword lists
        raw = tpl.keywords.replace(",", " ")
        kws = [k.strip().lower() for k in raw.split() if k.strip()]
        hits = sum(1 for kw in kws if kw in task_lower)
        return hits + 1 if hits > 0 else 0  # +1 so keyword matches beat no-keyword

    async def _select_template(
        self, task: str, fmt: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Look up the best matching user/company template for this task+format.
        Returns {"sections": [...], "file_path": str|None} or None if no match.
        """
        try:
            templates = await self._query_templates(fmt)
            if not templates:
                return None

            tl = task.lower()
            best: Optional[Any] = None
            best_score = 0
            for tpl in templates:
                score = self._score_template(tpl, tl)
                if score > best_score:
                    best_score = score
                    best = tpl

            if best:
                self._log(f"Matched template: '{best.name}' (score={best_score})")
                return {
                    "sections": json.loads(best.sections_json),
                    "file_path": best.template_file_path or None,
                    "format": best.format,
                }
        except Exception as e:
            self._log(f"Template lookup error: {e}")
        return None

    async def _infer_format_from_templates(self, task: str) -> Optional[str]:
        """
        When no file format is specified in the task, check if any saved template
        matches and return its format so we can trigger file generation.
        """
        try:
            templates = await self._query_templates()
            if not templates:
                return None
            tl = task.lower()
            best: Optional[Any] = None
            best_score = 0
            for tpl in templates:
                score = self._score_template(tpl, tl)
                if score > best_score:
                    best_score = score
                    best = tpl
            if best:
                self._log(f"Inferred format '{best.format}' from template '{best.name}'")
                return best.format
        except Exception as e:
            self._log(f"Format inference error: {e}")
        return None

    # =========================================================================
    # Email Workflow Helpers
    # =========================================================================

    _EMAIL_REPLY_SIGNALS = [
        "answer", "reply", "respond", "draft reply", "draft response",
        "balas", "jawab", "respond to", "write back",
    ]
    _EMAIL_SIGNALS = ["email", "mail", "inbox", "surel", "surat"]

    def _detect_read_email_from(self, task: str) -> Optional[str]:
        """
        Detect 'read email from X' / 'latest email from X' patterns.
        Returns the sender name/address to search for, or None.
        """
        tl = task.lower()
        for pattern in [
            r'(?:read|show|get|fetch|open)\s+(?:me\s+)?(?:the\s+)?(?:latest|last|recent|newest)?\s*email\s+from\s+(.+)',
            r'(?:latest|last|recent|newest)\s+email\s+from\s+(.+)',
            r'email\s+from\s+(.+?)\s*$',
        ]:
            m = re.search(pattern, tl)
            if m:
                return m.group(1).strip().rstrip('?.,!')
        return None

    async def _handle_read_latest_email(
        self,
        task: str,
        sender_query: str,
        context: Optional[List[Dict[str, str]]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Two-step handler: search emails from sender → read the first (latest) result in full.
        """
        yield {"type": "thought", "content": f"Searching for emails from {sender_query}…"}
        search_params: Dict[str, Any] = {"action": "search", "query": sender_query, "top": 5}
        yield {"type": "action", "tool": "email_read", "input": search_params}
        search_result = await self.executor.execute("email_read", search_params)
        yield {"type": "observation", "result": search_result.to_observation(), "status": search_result.status.value}

        if search_result.status != ExecutionStatus.SUCCESS or not isinstance(search_result.result, dict):
            answer = f"Could not search emails: {search_result.error or 'unknown error'}"
            self.trace.final_answer = answer
            yield {"type": "final_answer", "content": answer, "sources": []}
            return

        messages = search_result.result.get("messages", [])
        if not messages:
            answer = f"No emails found from **{sender_query}**."
            self.trace.final_answer = answer
            yield {"type": "final_answer", "content": answer, "sources": []}
            return

        # Read the latest (first) result in full
        latest = messages[0]
        msg_id = latest.get("id", "")
        subject = latest.get("subject", "(no subject)")

        yield {"type": "thought", "content": f"Reading: {subject[:70]}…"}
        read_params: Dict[str, Any] = {"action": "read", "message_id": msg_id}
        yield {"type": "action", "tool": "email_read", "input": read_params}
        read_result = await self.executor.execute("email_read", read_params)
        yield {"type": "observation", "result": read_result.to_observation(), "status": read_result.status.value}

        if read_result.status != ExecutionStatus.SUCCESS or not isinstance(read_result.result, dict):
            answer = f"Found the email but could not read it: {read_result.error or 'unknown error'}"
            self.trace.final_answer = answer
            yield {"type": "final_answer", "content": answer, "sources": []}
            return

        email = read_result.result.get("message", {})
        sender_name = email.get("from_name") or email.get("from", "")
        sender_addr = email.get("from", "")
        received = email.get("received", "")
        cc = email.get("cc", [])
        body_raw = email.get("body", email.get("preview", ""))
        body = re.sub(r'<[^>]+>', ' ', body_raw)  # strip HTML
        body = re.sub(r'\s{3,}', '\n\n', body).strip()

        lines = [
            f"**{email.get('subject', subject)}**",
            f"From: {sender_name} <{sender_addr}>",
        ]
        if received:
            lines.append(f"Received: {received}")
        if cc:
            lines.append(f"CC: {', '.join(cc)}")
        lines.append("")
        lines.append(body[:4000] + ("…" if len(body) > 4000 else ""))

        answer = "\n".join(lines)
        self.trace.final_answer = answer
        self.trace.success = True
        yield {"type": "final_answer", "content": answer, "sources": []}

    def _detect_email_workflow(self, task: str) -> bool:
        """True when the user wants the agent to read emails AND draft/send replies."""
        tl = task.lower()
        return (
            any(e in tl for e in self._EMAIL_SIGNALS)
            and any(r in tl for r in self._EMAIL_REPLY_SIGNALS)
        )

    def _detect_send_confirmation(self, task: str) -> Optional[List[int]]:
        """
        Detect 'send all' / 'send 1, 2' confirmation messages.
        Returns [] for 'send all', [1,2,...] for specific numbers, None if not a send command.
        """
        tl = task.lower().strip()
        if tl in ("send all", "send them all", "yes send all", "kirim semua", "send"):
            return []
        m = re.match(r'^send\s+([\d\s,]+)$', tl)
        if m:
            nums = [int(n) for n in re.findall(r'\d+', m.group(1))]
            return nums if nums else []
        return None

    def _extract_email_topic(self, task: str) -> Optional[str]:
        """Extract a search keyword from the task (e.g. 'emails about budget' → 'budget')."""
        tl = task.lower()
        for pattern in [
            r'emails?\s+about\s+([^\s,]+(?:\s+[^\s,]+){0,3})',
            r'emails?\s+from\s+([^\s,]+(?:\s+[^\s,]+){0,2})',
            r'email\s+(?:about|from|re:)\s+([^\s,]+(?:\s+[^\s,]+){0,3})',
        ]:
            m = re.search(pattern, tl)
            if m:
                return m.group(1).strip()
        return None

    async def _llm_draft_reply(self, task: str, email: Dict[str, Any]) -> str:
        """Use the LLM to draft a reply to a single email."""
        subject = email.get("subject", "(no subject)")
        sender = email.get("from_name") or email.get("from", "")
        body = email.get("body", email.get("preview", ""))
        # Strip HTML tags for cleaner context
        body_clean = re.sub(r'<[^>]+>', ' ', body).strip()[:2000]

        user_instruction = ""
        tl = task.lower()
        for pattern in [r'saying\s+(.+)', r'with\s+(?:the\s+)?message\s+(.+)', r'that\s+(.+)']:
            m = re.search(pattern, tl)
            if m:
                user_instruction = f"\nUser's instruction for the reply: {m.group(1)}"
                break

        prompt = f"""You are a professional email assistant. Draft a concise, polite reply to the email below.

Original email:
From: {sender}
Subject: {subject}
Body:
{body_clean}
{user_instruction}

Write ONLY the reply body (no subject line, no "To:", no signature placeholder).
Be professional, concise, and match the tone of the original email.
Reply:"""

        messages = [{"role": "user", "content": prompt}]
        try:
            return await self.ai_service.generate_response(messages, use_agent_model=False)
        except Exception as e:
            self._log(f"Draft reply error: {e}")
            return "(Could not generate draft — please write your reply manually.)"

    async def _handle_email_workflow(
        self,
        task: str,
        context: Optional[List[Dict[str, str]]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Multi-step email workflow:
        1. Search / list matching emails
        2. Read each full email
        3. Draft a reply per email using LLM
        4. Present all drafts for user confirmation
        """
        topic = self._extract_email_topic(task)

        # Step 1 — list or search
        if topic:
            yield {"type": "thought", "content": f"Searching your inbox for emails about '{topic}'…"}
            list_params: Dict[str, Any] = {"action": "search", "query": topic}
        else:
            yield {"type": "thought", "content": "Fetching your recent inbox…"}
            list_params = {"action": "list", "folder": "inbox", "top": 10}

        yield {"type": "action", "tool": "email_read", "input": list_params}
        list_result = await self.executor.execute("email_read", list_params)
        yield {"type": "observation", "result": list_result.to_observation(), "status": list_result.status.value}

        if list_result.status != ExecutionStatus.SUCCESS or not isinstance(list_result.result, dict):
            answer = f"Could not read emails: {list_result.error or 'unknown error'}"
            self.trace.final_answer = answer
            yield {"type": "final_answer", "content": answer, "sources": []}
            return

        emails = list_result.result.get("messages", [])
        if not emails:
            answer = "No emails found matching your request."
            self.trace.final_answer = answer
            yield {"type": "final_answer", "content": answer, "sources": []}
            return

        # Step 2 & 3 — read full content + draft reply for each (cap at 5)
        drafts: List[Dict[str, Any]] = []
        for i, summary in enumerate(emails[:5]):
            msg_id = summary.get("id", "")
            subject = summary.get("subject", "(no subject)")
            sender_name = summary.get("from_name") or summary.get("from", "")

            yield {"type": "thought", "content": f"Reading email {i + 1}: {subject[:60]}…"}
            read_params = {"action": "read", "message_id": msg_id}
            yield {"type": "action", "tool": "email_read", "input": read_params}
            read_result = await self.executor.execute("email_read", read_params)
            yield {"type": "observation", "result": read_result.to_observation(), "status": read_result.status.value}

            if read_result.status != ExecutionStatus.SUCCESS:
                continue

            full_email = read_result.result.get("message", summary)

            yield {"type": "thought", "content": f"Drafting reply for: {subject[:60]}…"}
            reply_body = await self._llm_draft_reply(task, full_email)

            drafts.append({
                "num": i + 1,
                "message_id": msg_id,
                "subject": subject,
                "from": sender_name,
                "reply": reply_body,
            })

        if not drafts:
            answer = "Read the emails but could not generate draft replies."
            self.trace.final_answer = answer
            yield {"type": "final_answer", "content": answer, "sources": []}
            return

        # Cache drafts for follow-up send confirmation
        if self.user_id:
            _email_draft_cache[self.user_id] = drafts

        # Step 4 — present drafts
        lines = [f"I've drafted {len(drafts)} repl{'ies' if len(drafts) > 1 else 'y'}:\n"]
        for d in drafts:
            lines.append(f"---\n**#{d['num']} — {d['subject']}**\nFrom: {d['from']}\n\n{d['reply']}\n")
        lines.append(
            "---\nReview the drafts above.\n"
            "- Say **`send all`** to send all of them\n"
            "- Say **`send 1`** or **`send 1, 3`** to send specific ones\n"
            "- Or edit the text above and paste your revised reply before sending"
        )

        answer = "\n".join(lines)
        self.trace.final_answer = answer
        self.trace.success = True
        yield {"type": "final_answer", "content": answer, "sources": []}

    async def _handle_send_confirmation(
        self,
        task: str,
        draft_numbers: List[int],
        context: Optional[List[Dict[str, str]]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Send the confirmed draft replies."""
        if not self.user_id or self.user_id not in _email_draft_cache:
            answer = "No pending drafts found. Please run the email workflow again."
            self.trace.final_answer = answer
            yield {"type": "final_answer", "content": answer, "sources": []}
            return

        all_drafts = _email_draft_cache[self.user_id]
        to_send = (
            all_drafts
            if not draft_numbers
            else [d for d in all_drafts if d["num"] in draft_numbers]
        )

        if not to_send:
            answer = "No matching drafts to send."
            self.trace.final_answer = answer
            yield {"type": "final_answer", "content": answer, "sources": []}
            return

        results = []
        for d in to_send:
            yield {"type": "thought", "content": f"Sending reply #{d['num']}: {d['subject'][:60]}…"}
            send_params = {"message_id": d["message_id"], "body": d["reply"]}
            yield {"type": "action", "tool": "email_reply", "input": send_params}
            result = await self.executor.execute("email_reply", send_params)
            yield {"type": "observation", "result": result.to_observation(), "status": result.status.value}
            ok = result.status == ExecutionStatus.SUCCESS
            results.append(f"{'✓' if ok else '✗'} **{d['subject']}** — {'sent' if ok else result.error}")

        # Clear cache after sending
        _email_draft_cache.pop(self.user_id, None)

        answer = "**Replies sent:**\n" + "\n".join(results)
        self.trace.final_answer = answer
        self.trace.success = True
        yield {"type": "final_answer", "content": answer, "sources": []}

    # Phrases that explicitly ask for a free-form report (no saved template)
    _NO_TEMPLATE_SIGNALS = [
        "no template", "without template", "tanpa template",
        "free form", "free-form", "bebas", "quick report", "simple report",
        "laporan singkat", "laporan sederhana",
    ]

    async def _handle_file_generation(
        self,
        task: str,
        fmt: str,
        filename: str,
        context: Optional[List[Dict[str, str]]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Dedicated handler for file-generation requests."""
        observations: List[str] = []
        tl = task.lower()

        # Allow the user to explicitly bypass saved templates
        skip_template = any(sig in tl for sig in self._NO_TEMPLATE_SIGNALS)

        # Attempt to find a matching user/company template.
        # First try the detected format; if nothing matches, search all formats
        # so a DOCX template is found even when the router guessed XLSX.
        matched = None
        if skip_template:
            self._log("Template matching skipped (user requested free-form report)")
        else:
            matched = await self._select_template(task, fmt)
            if not matched:
                matched = await self._select_template(task, None)
        if matched:
            # Let the template's own format take precedence over the router's guess
            template_fmt = matched.get("format")
            if template_fmt and template_fmt != fmt:
                self._log(f"Overriding detected format '{fmt}' → '{template_fmt}' from template")
                fmt = template_fmt
                filename = self._derive_filename(task, fmt)
        matched_template = matched["sections"] if matched else None
        template_file_path = matched["file_path"] if matched else None
        if matched_template:
            msg = "Using your saved report template for this document"
            if template_file_path:
                msg += " (style-preserving mode)"
            msg += "…"
            yield {"type": "thought", "content": msg}

        # Step 1b runs first so we know whether live finance data will be fetched.
        # If it will, skip RAG entirely — old regulatory documents will contaminate
        # the observations with stale rates/prices.
        finance_symbols = self._detect_finance_symbols(task)
        has_live_finance = bool(finance_symbols)

        # Step 1a — pull data from the knowledge base.
        # Skip when we have live finance data; only run when the user explicitly
        # references their documents or no live data exists.
        explicit_doc_ref = any(kw in tl for kw in self._RAG_SIGNALS)
        needs_rag = (not has_live_finance) and (bool(matched_template) or explicit_doc_ref)
        if needs_rag:
            yield {"type": "thought", "content": "Searching your uploaded documents…"}
            rag_params = {"query": task, "top_k": 10}
            yield {"type": "action", "tool": "rag_search", "input": rag_params}
            rag_result = await self.executor.execute("rag_search", rag_params)
            obs = rag_result.to_observation()
            observations.append(f"[Knowledge Base]\n{obs}")
            yield {"type": "observation", "result": obs, "status": rag_result.status.value}

            # Per-section targeted search so each heading gets relevant content
            if matched_template:
                seen_queries = {task.lower()}
                for s in matched_template:
                    heading = s.get("heading", "")
                    query = s.get("placeholder") or heading
                    if query and query.lower() not in seen_queries:
                        seen_queries.add(query.lower())
                        yield {"type": "thought", "content": f"Searching documents for: {heading}…"}
                        s_params = {"query": query, "top_k": 5}
                        yield {"type": "action", "tool": "rag_search", "input": s_params}
                        s_result = await self.executor.execute("rag_search", s_params)
                        obs = s_result.to_observation()
                        observations.append(f"[Knowledge Base — {heading}]\n{obs}")
                        yield {"type": "observation", "result": obs, "status": s_result.status.value}

        # Step 1b — fetch live Yahoo Finance data for every detected currency / index
        for symbol, label in finance_symbols:
            # Current quote
            yield {"type": "thought", "content": f"Fetching {label} live rate from Yahoo Finance…"}
            q_params = {"symbol": symbol, "action": "quote"}
            yield {"type": "action", "tool": "yahoo_finance", "input": q_params}
            q_result = await self.executor.execute("yahoo_finance", q_params)
            obs = q_result.to_observation()
            observations.append(f"[Yahoo Finance — current rate: {label}]\n{obs}")
            yield {"type": "observation", "result": obs, "status": q_result.status.value}

            # 3-month history for trend analysis
            h_params = {"symbol": symbol, "action": "history", "period": "3mo"}
            yield {"type": "action", "tool": "yahoo_finance", "input": h_params}
            h_result = await self.executor.execute("yahoo_finance", h_params)
            obs = h_result.to_observation()
            observations.append(f"[Yahoo Finance — 3-month history: {label}]\n{obs}")
            yield {"type": "observation", "result": obs, "status": h_result.status.value}

            # Yahoo Finance news headlines for this symbol
            yield {"type": "thought", "content": f"Fetching {label} news from Yahoo Finance…"}
            n_params = {"symbol": symbol, "action": "news"}
            yield {"type": "action", "tool": "yahoo_finance", "input": n_params}
            n_result = await self.executor.execute("yahoo_finance", n_params)
            obs = n_result.to_observation()
            observations.append(f"[Yahoo Finance — news: {label}]\n{obs}")
            yield {"type": "observation", "result": obs, "status": n_result.status.value}

        # Step 1b-extra — scan template section headings for additional data needs
        # (e.g. "Suku Bunga", "Inflasi", "Indeks Acuan" headings not in the task text)
        if matched_template:
            fetched_symbols = {s for s, _ in finance_symbols}
            extra_symbols, extra_web_queries = await self._plan_section_data(
                matched_template, fetched_symbols
            )
            for symbol, label in extra_symbols:
                yield {"type": "thought", "content": f"Fetching {label} from Yahoo Finance…"}
                q_params = {"symbol": symbol, "action": "quote"}
                yield {"type": "action", "tool": "yahoo_finance", "input": q_params}
                q_result = await self.executor.execute("yahoo_finance", q_params)
                obs = q_result.to_observation()
                observations.append(f"[Yahoo Finance — {label}]\n{obs}")
                yield {"type": "observation", "result": obs, "status": q_result.status.value}

                h_params = {"symbol": symbol, "action": "history", "period": "1mo"}
                yield {"type": "action", "tool": "yahoo_finance", "input": h_params}
                h_result = await self.executor.execute("yahoo_finance", h_params)
                obs = h_result.to_observation()
                observations.append(f"[Yahoo Finance — history: {label}]\n{obs}")
                yield {"type": "observation", "result": obs, "status": h_result.status.value}
        else:
            extra_web_queries = []

        # Step 1c — Tavily web search: symbol queries + section-heading queries
        search_queries = self._derive_search_queries(task, finance_symbols)
        for q in extra_web_queries:
            if q not in search_queries:
                search_queries.append(q)
        for search_query in search_queries:
            yield {"type": "thought", "content": f"Searching latest news via Tavily: {search_query}…"}
            ws_params = {"query": search_query, "num_results": 5}
            yield {"type": "action", "tool": "web_search", "input": ws_params}
            ws_result = await self.executor.execute("web_search", ws_params)
            obs = ws_result.to_observation()
            observations.append(f"[Tavily Web Search — {search_query}]\n{obs}")
            yield {"type": "observation", "result": obs, "status": ws_result.status.value}

        # Step 2 — ask LLM to structure the content JSON from all collected data
        yield {"type": "thought", "content": f"Analysing research data and building {fmt.upper()} content…"}
        content = await self._llm_build_file_content(
            task, fmt, observations, matched_template, template_file_path
        )

        # Step 3 — call generate_file
        gen_params = {
            "format": fmt,
            "filename": filename.rsplit(".", 1)[0],
            "content": json.dumps(content, ensure_ascii=False),
        }
        if template_file_path:
            gen_params["template_file_path"] = template_file_path
        yield {"type": "thought", "content": f"Generating {fmt.upper()} file…"}
        yield {"type": "action", "tool": "generate_file", "input": gen_params}
        file_result = await self.executor.execute("generate_file", gen_params)
        yield {"type": "observation", "result": file_result.to_observation(), "status": file_result.status.value}

        # Step 4 — compose final answer
        success = False
        if file_result.status == ExecutionStatus.SUCCESS and isinstance(file_result.result, dict):
            r = file_result.result
            dl_url = r.get("download_url", "")
            dl_name = r.get("filename", filename)
            err_in_result = r.get("error", "")
            if dl_url and not err_in_result:
                answer = (
                    f"Your {fmt.upper()} file is ready!\n\n"
                    f"[{dl_name}]({dl_url})\n\n"
                    f"Click the link above to download."
                )
                success = True
            else:
                reason = err_in_result or "download URL not returned"
                answer = f"Sorry, I could not generate the file: {reason}"
        else:
            err = file_result.error or "unknown error"
            answer = f"Sorry, I could not generate the file: {err}"

        self.trace.final_answer = answer
        self.trace.success = success
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

        # Email send-confirmation fast path (user confirming pending drafts)
        draft_nums = self._detect_send_confirmation(task)
        if draft_nums is not None and self.user_id and _email_draft_cache.get(self.user_id):
            self._log(f"EMAIL SEND CONFIRMATION: nums={draft_nums or 'all'}")
            async for event in self._handle_send_confirmation(task, draft_nums, context):
                yield event
            await self.executor.close()
            self.trace.total_time = time.time() - start_time
            return

        # "Read email from X" fast path — search then read in full
        sender_query = self._detect_read_email_from(task)
        if sender_query:
            self._log(f"READ EMAIL FROM: {sender_query}")
            async for event in self._handle_read_latest_email(task, sender_query, context):
                yield event
            await self.executor.close()
            self.trace.total_time = time.time() - start_time
            return

        # Email read-and-reply workflow fast path
        if self._detect_email_workflow(task):
            self._log("EMAIL WORKFLOW REQUEST")
            async for event in self._handle_email_workflow(task, context):
                yield event
            await self.executor.close()
            self.trace.total_time = time.time() - start_time
            return

        # File generation fast path — runs before the normal tool detection
        file_fmt, file_name = self._detect_file_request(task)

        # If no explicit format was found, check whether the user has a saved template
        # that matches this generation intent — use the template's format.
        if not file_fmt:
            tl_check = task.lower()
            _gen_words = [
                "generate", "create", "make", "build", "produce", "write", "prepare",
                "buat", "hasilkan", "tulis", "siapkan",
            ]
            _doc_words = [
                "analysis", "report", "laporan", "analisis", "analisa",
                "document", "summary", "ringkasan", "dokumen",
            ]
            if (any(w in tl_check for w in _gen_words)
                    and any(w in tl_check for w in _doc_words)):
                inferred = await self._infer_format_from_templates(task)
                if inferred:
                    file_fmt = inferred
                    file_name = self._derive_filename(task, inferred)

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
