"""
Tool Executor - Executes tools and returns results.

Handles tool invocation, sandboxing, error handling, and result formatting.
"""

import asyncio
import json
import math
import re
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import httpx
from bs4 import BeautifulSoup

from app.agent.tools import Tool, tool_registry, ToolCategory


def log(message: str):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [TOOL] {message}", flush=True)


class ExecutionStatus(str, Enum):
    """Status of tool execution."""
    SUCCESS = "success"
    ERROR = "error"
    PENDING_CONFIRMATION = "pending_confirmation"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ToolResult:
    """Result of tool execution."""
    tool_name: str
    status: ExecutionStatus
    result: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time,
            "metadata": self.metadata,
        }

    def to_observation(self) -> str:
        """Format result as observation for agent."""
        if self.status == ExecutionStatus.SUCCESS:
            if isinstance(self.result, dict):
                return json.dumps(self.result, indent=2, default=str)
            return str(self.result)
        elif self.status == ExecutionStatus.ERROR:
            return f"Error: {self.error}"
        elif self.status == ExecutionStatus.PENDING_CONFIRMATION:
            return "Awaiting user confirmation..."
        elif self.status == ExecutionStatus.TIMEOUT:
            return "Tool execution timed out"
        else:
            return f"Tool execution status: {self.status.value}"


class ToolExecutor:
    """
    Executes tools and manages tool state.

    Provides sandboxed execution environment for tools with
    proper error handling and timeout management.
    """

    def __init__(
        self,
        db_session=None,
        user_id: Optional[int] = None,
        timeout: float = 30.0,
    ):
        self.db_session = db_session
        self.user_id = user_id
        self.timeout = timeout
        self._http_client: Optional[httpx.AsyncClient] = None
        self._pending_confirmations: Dict[str, Dict[str, Any]] = {}

    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with browser-like headers."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                }
            )
        return self._http_client

    async def close(self):
        """Close resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def execute(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        require_confirmation: bool = False,
    ) -> ToolResult:
        """
        Execute a tool with given parameters.

        Args:
            tool_name: Name of the tool to execute
            parameters: Parameters to pass to the tool
            require_confirmation: Override tool's confirmation requirement

        Returns:
            ToolResult with execution status and result
        """
        start_time = asyncio.get_event_loop().time()

        # Get tool definition
        tool = tool_registry.get(tool_name)
        if not tool:
            return ToolResult(
                tool_name=tool_name,
                status=ExecutionStatus.ERROR,
                result=None,
                error=f"Unknown tool: {tool_name}",
            )

        # Check if confirmation is required
        if tool.requires_confirmation or require_confirmation:
            confirmation_id = f"{tool_name}_{start_time}"
            self._pending_confirmations[confirmation_id] = {
                "tool_name": tool_name,
                "parameters": parameters,
            }
            return ToolResult(
                tool_name=tool_name,
                status=ExecutionStatus.PENDING_CONFIRMATION,
                result=None,
                metadata={"confirmation_id": confirmation_id},
            )

        # Execute with timeout
        params_preview = json.dumps(parameters, default=str)
        params_preview = params_preview if len(params_preview) <= 120 else params_preview[:120] + "..."
        log(f"{'─'*50}")
        log(f"▶ CALLING: {tool_name}")
        log(f"  PARAMS : {params_preview}")

        try:
            result = await asyncio.wait_for(
                self._execute_tool(tool_name, parameters),
                timeout=self.timeout,
            )
            elapsed = asyncio.get_event_loop().time() - start_time

            # Summarise result for log
            if isinstance(result, dict):
                if "results" in result:
                    summary = f"{result.get('count', len(result['results']))} result(s)"
                elif "error" in result:
                    summary = f"error: {result['error']}"
                elif "rate" in result or "price" in result:
                    price = result.get("rate") or result.get("price")
                    summary = f"price/rate = {price}"
                else:
                    summary = str(result)[:120]
            else:
                summary = str(result)[:120]

            log(f"  STATUS : SUCCESS ({elapsed:.2f}s)")
            log(f"  RESULT : {summary}")
            log(f"{'─'*50}")

            return ToolResult(
                tool_name=tool_name,
                status=ExecutionStatus.SUCCESS,
                result=result,
                execution_time=elapsed,
            )
        except asyncio.TimeoutError:
            log(f"  STATUS : TIMEOUT after {self.timeout}s")
            log(f"{'─'*50}")
            return ToolResult(
                tool_name=tool_name,
                status=ExecutionStatus.TIMEOUT,
                result=None,
                error=f"Tool execution timed out after {self.timeout}s",
            )
        except Exception as e:
            elapsed = asyncio.get_event_loop().time() - start_time
            log(f"  STATUS : ERROR ({elapsed:.2f}s)")
            log(f"  ERROR  : {str(e)}")
            log(f"{'─'*50}")
            return ToolResult(
                tool_name=tool_name,
                status=ExecutionStatus.ERROR,
                result=None,
                error=str(e),
                execution_time=elapsed,
                metadata={"traceback": traceback.format_exc()},
            )

    async def _execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
    ) -> Any:
        """Internal tool execution dispatch."""

        # Dispatch to appropriate handler
        handlers = {
            "rag_search": self._execute_rag_search,
            "web_search": self._execute_web_search,
            "read_url": self._execute_read_url,
            "calculator": self._execute_calculator,
            "python_execute": self._execute_python,
            "get_current_time": self._execute_current_time,
            "get_weather": self._execute_weather,
            "read_file": self._execute_read_file,
            "create_subtask": self._execute_create_subtask,
            "final_answer": self._execute_final_answer,
            "yahoo_finance": self._execute_yahoo_finance,
            "generate_file": self._execute_generate_file,
        }

        handler = handlers.get(tool_name)
        if handler:
            return await handler(parameters)
        else:
            raise ValueError(f"No handler for tool: {tool_name}")

    # =========================================================================
    # Tool Implementations
    # =========================================================================

    async def _execute_rag_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search the knowledge base using RAG."""
        from app.services.knowledge_graph import KnowledgeGraphService

        query = params.get("query", "")
        top_k = min(params.get("top_k", 5), 10)

        if not self.db_session:
            return {"error": "Database session not available"}

        try:
            kg_service = KnowledgeGraphService(self.db_session)
            results = await kg_service.hybrid_search(
                query=query,
                user_id=self.user_id,
                top_k=top_k,
                vector_weight=0.6,
                graph_weight=0.4,
            )
        except Exception as e:
            await self.db_session.rollback()
            return {"error": f"RAG search failed: {str(e)}"}

        if not results:
            return {
                "query": query,
                "results": [],
                "message": "No relevant documents found",
            }

        formatted_results = []
        for r in results:
            formatted_results.append({
                "source": r.filename,
                "content": r.chunk_text[:500] + "..." if len(r.chunk_text) > 500 else r.chunk_text,
                "score": round(r.combined_score, 3),
                "entities": [e["name"] for e in (r.matched_entities or [])[:3]],
            })

        return {
            "query": query,
            "results": formatted_results,
            "count": len(formatted_results),
        }

    async def _execute_web_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search the web using Tavily API."""
        from app.config import settings

        query = params.get("query", "")
        num_results = min(params.get("num_results", 5), 10)

        # Check if Tavily API key is configured
        if not settings.TAVILY_API_KEY:
            print("[AGENT] Tavily API key not configured, using Bing fallback")
            return await self._execute_web_search_fallback(query, num_results)

        # Run the synchronous Tavily search in a thread pool
        try:
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._tavily_search(query, num_results)
            )
            return {
                "query": query,
                "results": results,
                "count": len(results),
            }
        except Exception as e:
            print(f"[AGENT] Tavily search error: {e}")
            # Fallback to Bing
            return await self._execute_web_search_fallback(query, num_results)

    def _tavily_search(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Search using Tavily API."""
        from tavily import TavilyClient
        from app.config import settings

        try:
            client = TavilyClient(api_key=settings.TAVILY_API_KEY)
            response = client.search(
                query=query,
                max_results=num_results,
                include_answer=False,
                include_raw_content=False,
            )

            results = []
            for r in response.get("results", []):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("content", ""),
                    "url": r.get("url", ""),
                })

            print(f"[AGENT] Tavily search found {len(results)} results for: {query[:50]}...")
            return results

        except Exception as e:
            print(f"[AGENT] Tavily search failed: {e}")
            raise

    async def _execute_web_search_fallback(self, query: str, num_results: int) -> Dict[str, Any]:
        """Fallback web search using Bing."""
        try:
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._bing_search(query, num_results)
            )
            return {
                "query": query,
                "results": results,
                "count": len(results),
            }
        except Exception as e:
            print(f"[AGENT] Fallback search error: {e}")
            return {
                "query": query,
                "results": [],
                "error": str(e),
            }

    def _bing_search(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Fallback search using Bing."""
        import requests
        from urllib.parse import quote_plus

        try:
            url = f"https://www.bing.com/search?q={quote_plus(query)}&count={num_results}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
            }

            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            results = []

            for result in soup.select(".b_algo")[:num_results]:
                title_elem = result.select_one("h2 a")
                snippet_elem = result.select_one(".b_caption p")

                if title_elem:
                    results.append({
                        "title": title_elem.get_text(strip=True),
                        "snippet": snippet_elem.get_text(strip=True) if snippet_elem else "",
                        "url": title_elem.get("href", ""),
                    })

            print(f"[AGENT] Bing fallback found {len(results)} results")
            return results
        except Exception as e:
            print(f"[AGENT] Bing fallback failed: {e}")
            return []

    async def _execute_read_url(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Read content from a URL."""
        url = params.get("url", "")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        client = await self.get_http_client()

        try:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")

            if "text/html" in content_type:
                soup = BeautifulSoup(response.text, "html.parser")

                # Remove script and style elements
                for element in soup(["script", "style", "nav", "footer", "header"]):
                    element.decompose()

                # Get text content
                text = soup.get_text(separator="\n", strip=True)

                # Truncate if too long
                if len(text) > 10000:
                    text = text[:10000] + "\n\n[Content truncated...]"

                return {
                    "url": url,
                    "title": soup.title.string if soup.title else "",
                    "content": text,
                    "content_type": "html",
                }
            elif "application/json" in content_type:
                return {
                    "url": url,
                    "content": response.json(),
                    "content_type": "json",
                }
            else:
                text = response.text[:10000]
                return {
                    "url": url,
                    "content": text,
                    "content_type": "text",
                }
        except Exception as e:
            return {
                "url": url,
                "error": str(e),
            }

    async def _execute_calculator(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute mathematical calculations safely."""
        expression = params.get("expression", "")

        # Define safe math functions
        safe_dict = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "log": math.log,
            "log10": math.log10,
            "log2": math.log2,
            "exp": math.exp,
            "pi": math.pi,
            "e": math.e,
            "ceil": math.ceil,
            "floor": math.floor,
            "factorial": math.factorial,
            "gcd": math.gcd,
            "radians": math.radians,
            "degrees": math.degrees,
        }

        # Clean the expression
        expression = expression.replace("^", "**")

        try:
            # Evaluate safely
            result = eval(expression, {"__builtins__": {}}, safe_dict)
            return {
                "expression": expression,
                "result": result,
            }
        except Exception as e:
            return {
                "expression": expression,
                "error": str(e),
            }

    async def _execute_python(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python code in a sandboxed environment."""
        code = params.get("code", "")

        # WARNING: This is a simplified implementation
        # In production, use a proper sandbox like RestrictedPython or a container

        import io
        import sys
        from contextlib import redirect_stdout, redirect_stderr

        # Capture output
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Limited globals for safety
        safe_globals = {
            "__builtins__": {
                "print": print,
                "len": len,
                "range": range,
                "str": str,
                "int": int,
                "float": float,
                "list": list,
                "dict": dict,
                "set": set,
                "tuple": tuple,
                "bool": bool,
                "sum": sum,
                "min": min,
                "max": max,
                "abs": abs,
                "round": round,
                "sorted": sorted,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "True": True,
                "False": False,
                "None": None,
            },
            "math": math,
        }

        local_vars = {}

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, safe_globals, local_vars)

            stdout = stdout_capture.getvalue()
            stderr = stderr_capture.getvalue()

            # Get the last expression result if available
            result = local_vars.get("result", None)

            return {
                "code": code,
                "stdout": stdout,
                "stderr": stderr,
                "result": result,
                "variables": {k: str(v)[:200] for k, v in local_vars.items() if not k.startswith("_")},
            }
        except Exception as e:
            return {
                "code": code,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }

    async def _execute_current_time(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current date and time."""
        from zoneinfo import ZoneInfo

        timezone_str = params.get("timezone", "UTC")

        try:
            tz = ZoneInfo(timezone_str)
            now = datetime.now(tz)

            return {
                "timezone": timezone_str,
                "datetime": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "day_of_week": now.strftime("%A"),
                "timestamp": now.timestamp(),
            }
        except Exception as e:
            # Fallback to UTC
            now = datetime.utcnow()
            return {
                "timezone": "UTC",
                "datetime": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "error": f"Invalid timezone '{timezone_str}', using UTC",
            }

    async def _execute_weather(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get weather information (placeholder - needs API key)."""
        location = params.get("location", "")

        # This is a placeholder - in production, use a weather API
        return {
            "location": location,
            "error": "Weather API not configured. Please set WEATHER_API_KEY in environment.",
            "suggestion": "You can search for weather using web_search tool instead.",
        }

    async def _execute_read_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Read an uploaded file."""
        from sqlalchemy import select
        from app.models.attachment import Attachment
        from app.services.document import DocumentService

        file_id = params.get("file_id")

        if not self.db_session:
            return {"error": "Database session not available"}

        # Get attachment
        try:
            result = await self.db_session.execute(
                select(Attachment).where(Attachment.id == file_id)
            )
            attachment = result.scalar_one_or_none()
        except Exception as e:
            await self.db_session.rollback()
            return {"error": f"Database error reading file: {str(e)}"}

        if not attachment:
            return {"error": f"File with ID {file_id} not found"}

        # Check access permissions
        if attachment.user_id != self.user_id and not attachment.is_company_doc:
            return {"error": "Access denied to this file"}

        # Extract text
        doc_service = DocumentService()
        text = await doc_service.extract_text(attachment.file_path)

        if not text:
            return {
                "file_id": file_id,
                "filename": attachment.original_filename,
                "error": "Could not extract text from file",
            }

        # Truncate if too long
        if len(text) > 15000:
            text = text[:15000] + "\n\n[Content truncated...]"

        return {
            "file_id": file_id,
            "filename": attachment.original_filename,
            "content_type": attachment.content_type,
            "content": text,
        }

    async def _execute_create_subtask(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a subtask for complex task breakdown."""
        description = params.get("description", "")
        priority = params.get("priority", 3)

        # This is tracked internally by the agent loop
        return {
            "created": True,
            "description": description,
            "priority": priority,
            "message": f"Subtask created: {description}",
        }

    async def _execute_final_answer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Provide the final answer."""
        answer = params.get("answer", "")
        sources = params.get("sources", [])

        return {
            "final": True,
            "answer": answer,
            "sources": sources,
        }

    async def _execute_yahoo_finance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get stock data from Yahoo Finance."""
        symbol = params.get("symbol", "").upper()
        action = params.get("action", "quote")
        period = params.get("period", "1mo")

        if not symbol:
            return {"error": "Stock symbol is required"}

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._yahoo_finance_sync(symbol, action, period)
            )
            return result
        except Exception as e:
            print(f"[AGENT] Yahoo Finance error: {e}")
            return {
                "symbol": symbol,
                "error": str(e),
            }

    def _yahoo_finance_sync(self, symbol: str, action: str, period: str) -> Dict[str, Any]:
        """Synchronous Yahoo Finance data fetching."""
        import yfinance as yf

        try:
            ticker = yf.Ticker(symbol)

            if action == "quote":
                # Get current quote
                info = ticker.fast_info

                # Check if this is a currency pair (e.g., IDR=X, EUR=X)
                is_currency = symbol.endswith("=X")

                result = {
                    "symbol": symbol,
                    "action": "quote",
                    "price": getattr(info, 'last_price', None),
                    "previous_close": getattr(info, 'previous_close', None),
                    "open": getattr(info, 'open', None),
                    "day_high": getattr(info, 'day_high', None),
                    "day_low": getattr(info, 'day_low', None),
                }

                if is_currency:
                    # For currency pairs, add helpful context
                    base_currency = symbol.replace("=X", "")
                    result["type"] = "currency_pair"
                    result["description"] = f"USD to {base_currency} exchange rate"
                    result["rate"] = getattr(info, 'last_price', None)
                else:
                    result["volume"] = getattr(info, 'last_volume', None)
                    result["market_cap"] = getattr(info, 'market_cap', None)
                    result["currency"] = getattr(info, 'currency', 'USD')

                return result

            elif action == "info":
                # Get detailed company info
                info = ticker.info
                return {
                    "symbol": symbol,
                    "action": "info",
                    "name": info.get("longName", info.get("shortName", symbol)),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "country": info.get("country"),
                    "website": info.get("website"),
                    "description": info.get("longBusinessSummary", "")[:500] + "..." if info.get("longBusinessSummary") else None,
                    "employees": info.get("fullTimeEmployees"),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "dividend_yield": info.get("dividendYield"),
                    "52_week_high": info.get("fiftyTwoWeekHigh"),
                    "52_week_low": info.get("fiftyTwoWeekLow"),
                }

            elif action == "history":
                # Get historical data
                hist = ticker.history(period=period)
                if hist.empty:
                    return {
                        "symbol": symbol,
                        "action": "history",
                        "error": "No historical data available",
                    }

                # Get summary statistics
                latest = hist.iloc[-1]
                first = hist.iloc[0]
                change = ((latest['Close'] - first['Close']) / first['Close']) * 100

                return {
                    "symbol": symbol,
                    "action": "history",
                    "period": period,
                    "start_date": str(hist.index[0].date()),
                    "end_date": str(hist.index[-1].date()),
                    "start_price": round(first['Close'], 2),
                    "end_price": round(latest['Close'], 2),
                    "change_percent": round(change, 2),
                    "high": round(hist['High'].max(), 2),
                    "low": round(hist['Low'].min(), 2),
                    "avg_volume": int(hist['Volume'].mean()),
                    "data_points": len(hist),
                }

            elif action == "financials":
                # Get financial data
                info = ticker.info
                return {
                    "symbol": symbol,
                    "action": "financials",
                    "revenue": info.get("totalRevenue"),
                    "gross_profit": info.get("grossProfits"),
                    "net_income": info.get("netIncomeToCommon"),
                    "ebitda": info.get("ebitda"),
                    "total_cash": info.get("totalCash"),
                    "total_debt": info.get("totalDebt"),
                    "free_cash_flow": info.get("freeCashflow"),
                    "operating_cash_flow": info.get("operatingCashflow"),
                    "profit_margins": info.get("profitMargins"),
                    "return_on_equity": info.get("returnOnEquity"),
                }

            elif action == "news":
                # Get recent news
                news = ticker.news
                news_items = []
                for item in news[:5]:  # Limit to 5 news items
                    news_items.append({
                        "title": item.get("title"),
                        "publisher": item.get("publisher"),
                        "link": item.get("link"),
                        "published": item.get("providerPublishTime"),
                    })

                return {
                    "symbol": symbol,
                    "action": "news",
                    "news": news_items,
                }

            else:
                return {
                    "symbol": symbol,
                    "error": f"Unknown action: {action}. Use: quote, info, history, financials, or news",
                }

        except Exception as e:
            print(f"[AGENT] Yahoo Finance sync error: {e}")
            raise

    async def _execute_generate_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a downloadable file."""
        import json as _json
        from app.services.file_generation import FileGenerationService

        fmt = params.get("format", "").lower()
        filename = params.get("filename", "document")
        content_raw = params.get("content", "{}")

        if fmt not in ("csv", "xlsx", "docx", "pptx", "pdf"):
            return {"error": f"Unsupported format '{fmt}'. Use: csv, xlsx, docx, pptx, pdf"}

        try:
            content = _json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except _json.JSONDecodeError as e:
            return {"error": f"Invalid content JSON: {e}"}

        try:
            svc = FileGenerationService()
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: svc.generate(fmt, filename, content)
            )
            return {
                "file_id": result["file_id"],
                "filename": result["filename"],
                "download_url": result["download_url"],
                "message": (
                    f"File generated successfully. "
                    f"Download: [{result['filename']}]({result['download_url']})"
                ),
            }
        except Exception as e:
            return {"error": f"File generation failed: {e}"}
