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
        """Log message if verbose mode is enabled."""
        if self.verbose:
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] [AGENT] {message}")

    async def _detect_required_tool(self, task: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Use LLM to intelligently detect which tool is required for the task.
        Returns tool name and parameters, or None for direct answer queries.
        """
        self._log("Using LLM to determine required tool...")

        tool_detection_prompt = f"""You are a tool selector. Analyze the user's request and decide which tool to use.

Available tools:
1. rag_search - Search uploaded documents, files, PDFs, company SOPs, knowledge base, manuals
2. web_search - Search the internet for current news, weather, prices, latest information, real-time data
3. calculator - Perform mathematical calculations
4. get_current_time - Get current time/date
5. read_url - Read content from a specific URL
6. none - No tool needed, can answer directly from knowledge

User request: "{task}"

Respond with ONLY a JSON object (no markdown, no explanation):
{{"tool": "<tool_name>", "params": {{"key": "value"}}, "reason": "<brief reason>"}}

Examples:
- "What's in my company SOP about leave policy?" → {{"tool": "rag_search", "params": {{"query": "leave policy", "top_k": 5}}, "reason": "searching uploaded documents"}}
- "What's the latest news about AI?" → {{"tool": "web_search", "params": {{"query": "latest AI news 2024", "num_results": 5}}, "reason": "need current information"}}
- "Calculate 15% of 250" → {{"tool": "calculator", "params": {{"expression": "0.15 * 250"}}, "reason": "math calculation"}}
- "What is Python?" → {{"tool": "none", "params": {{}}, "reason": "general knowledge question"}}

JSON:"""

        try:
            messages = [{"role": "user", "content": tool_detection_prompt}]
            response = await self.ai_service.generate_response(messages, use_agent_model=True)

            # Parse the JSON response
            cleaned = response.strip()

            # Try to extract JSON from the response
            json_match = re.search(r'\{[^{}]*\}', cleaned)
            if json_match:
                parsed = json.loads(json_match.group())
                tool_name = parsed.get("tool", "none").lower().strip()
                params = parsed.get("params", {})
                reason = parsed.get("reason", "")

                self._log(f"LLM selected tool: {tool_name} | Reason: {reason}")

                if tool_name == "none":
                    return None

                # Validate tool exists
                if not tool_registry.get(tool_name):
                    self._log(f"Unknown tool '{tool_name}', falling back to web_search")
                    return ("web_search", {"query": task, "num_results": 5})

                # Ensure required params exist
                if tool_name == "rag_search" and "query" not in params:
                    params["query"] = task
                    params["top_k"] = params.get("top_k", 5)
                elif tool_name == "web_search" and "query" not in params:
                    params["query"] = task
                    params["num_results"] = params.get("num_results", 5)
                elif tool_name == "calculator" and "expression" not in params:
                    # Try to extract expression from task
                    expr_match = re.search(r'[\d\+\-\*\/\(\)\^\.\s%]+', task)
                    if expr_match:
                        params["expression"] = expr_match.group().strip()
                    else:
                        params["expression"] = task

                return (tool_name, params)

        except Exception as e:
            self._log(f"LLM tool detection failed: {e}, using fallback")

        # Fallback to simple keyword detection if LLM fails
        return self._fallback_detect_tool(task)

    def _fallback_detect_tool(self, task: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Fallback keyword-based tool detection if LLM detection fails."""
        task_lower = task.lower()

        # RAG patterns (English + Indonesian)
        rag_keywords = [
            "document", "pdf", "file", "uploaded", "sop", "company", "my files", "knowledge base", "manual", "handbook",
            "dokumen", "berkas", "file saya", "perusahaan", "panduan", "buku pegangan"
        ]
        if any(kw in task_lower for kw in rag_keywords):
            return ("rag_search", {"query": task, "top_k": 5})

        # Web search patterns (English + Indonesian)
        web_keywords = [
            "search", "latest", "news", "current", "today", "weather", "price", "stock",
            "cari", "terbaru", "berita", "sekarang", "hari ini", "cuaca", "harga", "saham",
            "lihat web", "temukan", "cek", "update"
        ]
        if any(kw in task_lower for kw in web_keywords):
            return ("web_search", {"query": task, "num_results": 5})

        # Time patterns (English + Indonesian)
        if any(word in task_lower for word in ["time", "what time", "current time", "jam berapa", "waktu sekarang"]):
            return ("get_current_time", {"timezone": "Asia/Jakarta"})

        return None

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

        self._log(f"Starting task: {task[:100]}...")

        # FORCED TOOL CALL: Use LLM to detect if we should auto-execute a tool first
        forced_tool = await self._detect_required_tool(task)
        initial_observation = None

        if forced_tool:
            tool_name, tool_params = forced_tool
            self._log(f"FORCED TOOL CALL: {tool_name} with {tool_params}")

            # Yield thought about using the tool
            yield {"type": "thought", "content": f"I need to use {tool_name} to get current information for this task."}

            # Yield action
            yield {"type": "action", "tool": tool_name, "input": tool_params}

            # Execute the tool
            result = await self.executor.execute(tool_name, tool_params)
            initial_observation = result.to_observation()

            self._log(f"FORCED TOOL RESULT: {initial_observation[:200]}...")
            yield {"type": "observation", "result": initial_observation, "status": result.status.value}

            # Track sources
            if result.status == ExecutionStatus.SUCCESS:
                if tool_name == "web_search" and isinstance(result.result, dict):
                    for r in result.result.get("results", []):
                        if "url" in r:
                            self.trace.sources.append(r["url"])

            # Record the step
            step = AgentStep(
                step_number=1,
                state=AgentState.OBSERVING,
                thought=f"Using {tool_name} to get information",
                action=tool_name,
                action_input=tool_params,
                observation=initial_observation,
            )
            self.trace.steps.append(step)

        # Build messages for LLM
        system_prompt = """You are ALAI, a helpful AI assistant. You have access to real-time information through tools.

When given search results or tool outputs, summarize the information clearly and helpfully.
Always cite your sources when providing information from search results.
Be concise but thorough in your responses."""

        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation context if provided
        if context:
            for msg in context[-10:]:
                messages.append(msg)

        # Build the task message with tool results if we have them
        if initial_observation:
            task_message = f"""User's question: {task}

I searched and found this information:

{initial_observation}

Based on these search results, please provide a helpful answer to the user's question. Cite the sources."""
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

                self._log(f"Action: {action}")
                yield {"type": "action", "tool": action, "input": action_input}

                # Execute the tool
                result = await self.executor.execute(action, action_input or {})

                step.state = AgentState.OBSERVING
                observation = result.to_observation()
                step.observation = observation

                self._log(f"Observation: {observation[:200]}...")
                yield {"type": "observation", "result": observation, "status": result.status.value}

                # Track sources
                if result.status == ExecutionStatus.SUCCESS:
                    if action == "rag_search" and isinstance(result.result, dict):
                        for r in result.result.get("results", []):
                            if "source" in r:
                                self.trace.sources.append(r["source"])
                    elif action == "web_search" and isinstance(result.result, dict):
                        for r in result.result.get("results", []):
                            if "url" in r:
                                self.trace.sources.append(r["url"])

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
    ) -> AsyncGenerator[str, None]:
        """
        Run agent with streaming output for real-time display.

        Yields formatted strings suitable for SSE streaming.
        """
        async for event in self.run(task, context):
            event_type = event.get("type")

            if event_type == "thought":
                yield f"🤔 **Thinking:** {event['content']}\n\n"

            elif event_type == "action":
                tool = event.get("tool")
                tool_input = event.get("input", {})
                yield f"🔧 **Using tool:** `{tool}`\n"
                if tool_input:
                    yield f"```json\n{json.dumps(tool_input, indent=2)}\n```\n\n"

            elif event_type == "observation":
                result = event.get("result", "")
                status = event.get("status", "")
                if status == "success":
                    yield f"📋 **Result:**\n```\n{result[:1000]}\n```\n\n"
                else:
                    yield f"⚠️ **{status}:** {result}\n\n"

            elif event_type == "final_answer":
                content = event.get("content", "")
                sources = event.get("sources", [])
                yield f"\n---\n\n{content}"
                if sources:
                    yield f"\n\n**Sources:**\n"
                    for source in sources[:5]:
                        yield f"- {source}\n"

            elif event_type == "error":
                yield f"\n❌ **Error:** {event.get('message')}\n"
