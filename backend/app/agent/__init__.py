"""
Agentic AI Module

Provides tool calling, structured pipeline, and autonomous task execution.
"""

from app.agent.tools import Tool, ToolRegistry, tool_registry
from app.agent.executor import ToolExecutor
from app.agent.loop import AgentLoop, AgentState
from app.agent.pipeline import AgentPipeline

# AgentPipeline is the recommended entry point; AgentLoop is kept for compat.
__all__ = [
    "Tool",
    "ToolRegistry",
    "tool_registry",
    "ToolExecutor",
    "AgentLoop",
    "AgentPipeline",
    "AgentState",
]
