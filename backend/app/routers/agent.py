"""
Agent API Router - Dedicated endpoints for agentic interactions.

Provides more detailed control and visibility into agent execution.
"""

import time
import json
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional

from app.database import get_db
from app.middleware.auth import get_current_user, get_optional_user
from app.models.user import User
from app.services.ai import AIService
from app.agent.loop import AgentLoop
from app.agent.tools import tool_registry
from app.agent.executor import ToolExecutor


router = APIRouter(prefix="/agent", tags=["agent"])


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [AGENT-API] {message}")


class AgentRequest(BaseModel):
    """Request for agent execution."""
    task: str
    context: Optional[List[dict]] = None  # Previous conversation context
    max_steps: int = 10


class ToolExecuteRequest(BaseModel):
    """Request to execute a specific tool."""
    tool_name: str
    parameters: dict


@router.get("/tools")
async def list_tools():
    """
    List all available tools for the agent.
    """
    tools = tool_registry.get_all()
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category.value,
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "description": p.description,
                        "required": p.required,
                    }
                    for p in t.parameters
                ],
                "requires_confirmation": t.requires_confirmation,
            }
            for t in tools
        ],
        "count": len(tools),
    }


@router.post("/execute")
async def execute_agent(
    request: AgentRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute the agent for a given task (non-streaming).

    Returns the complete agent trace with all steps.
    """
    log(f"Starting agent execution: {request.task[:100]}...")
    start_time = time.time()

    ai_service = AIService()
    agent = AgentLoop(
        ai_service=ai_service,
        db_session=db,
        user_id=user.id if user else None,
        max_steps=min(request.max_steps, 15),  # Limit max steps
        verbose=True,
    )

    # Collect all events
    events = []
    final_answer = None

    async for event in agent.run(request.task, request.context):
        events.append(event)
        if event.get("type") == "final_answer":
            final_answer = event.get("content")

    elapsed = time.time() - start_time
    log(f"Agent execution complete in {elapsed:.2f}s")

    return {
        "task": request.task,
        "events": events,
        "final_answer": final_answer,
        "trace": agent.trace.to_dict() if agent.trace else None,
        "execution_time": elapsed,
    }


@router.post("/stream")
async def stream_agent(
    request: AgentRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute the agent for a given task with streaming output.

    Streams events as Server-Sent Events (SSE).
    """
    log(f"Starting streaming agent: {request.task[:100]}...")

    ai_service = AIService()
    agent = AgentLoop(
        ai_service=ai_service,
        db_session=db,
        user_id=user.id if user else None,
        max_steps=min(request.max_steps, 15),
        verbose=True,
    )

    async def generate():
        try:
            async for event in agent.run(request.task, request.context):
                # Send event as SSE
                event_json = json.dumps(event, default=str)
                yield f"data: {event_json}\n\n"

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete', 'trace': agent.trace.to_dict() if agent.trace else None})}\n\n"

        except Exception as e:
            log(f"Agent error: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tools/{tool_name}")
async def execute_tool(
    tool_name: str,
    request: ToolExecuteRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute a specific tool directly (for testing/debugging).
    """
    log(f"Direct tool execution: {tool_name}")

    # Verify tool exists
    tool = tool_registry.get(tool_name)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{tool_name}' not found",
        )

    # Execute tool
    executor = ToolExecutor(
        db_session=db,
        user_id=user.id if user else None,
        timeout=30.0,
    )

    try:
        result = await executor.execute(tool_name, request.parameters)
        return result.to_dict()
    finally:
        await executor.close()


@router.get("/status")
async def agent_status():
    """
    Get agent system status and capabilities.
    """
    tools = tool_registry.get_all()
    categories = {}
    for t in tools:
        cat = t.category.value
        if cat not in categories:
            categories[cat] = 0
        categories[cat] += 1

    return {
        "status": "ready",
        "capabilities": {
            "total_tools": len(tools),
            "categories": categories,
            "max_steps": 15,
            "features": [
                "web_search",
                "knowledge_base_search",
                "calculations",
                "code_execution",
                "url_reading",
            ],
        },
        "model": "Uses configured Ollama model",
    }
