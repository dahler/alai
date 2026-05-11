from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, List

from app.router.service import RouterService
from app.router.constants import RouterAction, RouterResult

router = APIRouter(prefix="/router", tags=["router"])

# Singleton router service
_router_service: Optional[RouterService] = None


def get_router_service() -> RouterService:
    """Get or create router service singleton."""
    global _router_service
    if _router_service is None:
        _router_service = RouterService()
    return _router_service


class ClassifyRequest(BaseModel):
    """Request body for classification endpoint."""
    query: str = Field(..., min_length=1, max_length=10000)
    has_attachments: bool = False
    has_images: bool = False


class ClassifyResponse(BaseModel):
    """Response from classification endpoint."""
    action: str
    confidence: float
    reason: Optional[str] = None


class BatchClassifyRequest(BaseModel):
    """Request body for batch classification."""
    requests: List[ClassifyRequest] = Field(..., max_length=10)


class BatchClassifyResponse(BaseModel):
    """Response from batch classification."""
    results: List[ClassifyResponse]


@router.post("/classify", response_model=ClassifyResponse)
async def classify_request(request: ClassifyRequest) -> ClassifyResponse:
    """
    Classify a user request into an action type.

    The router determines what workflow should handle the request
    WITHOUT answering the question itself.

    Actions:
    - direct_answer: General questions, the main AI model handles directly
    - rag_search: Questions about documents, needs RAG retrieval first
    - vision_analysis: Image-related questions, needs vision model
    - external_api: Real-time data, needs external API call first
    - memory_lookup: References previous conversation, needs context retrieval
    """
    service = get_router_service()

    result = await service.classify(
        query=request.query,
        has_attachments=request.has_attachments,
        has_images=request.has_images,
    )

    return ClassifyResponse(
        action=result.action,
        confidence=result.confidence,
        reason=result.reason,
    )


@router.post("/classify/batch", response_model=BatchClassifyResponse)
async def classify_batch(request: BatchClassifyRequest) -> BatchClassifyResponse:
    """
    Classify multiple requests in a batch.
    Useful for pre-classifying a queue of requests.
    """
    service = get_router_service()
    results = []

    for req in request.requests:
        result = await service.classify(
            query=req.query,
            has_attachments=req.has_attachments,
            has_images=req.has_images,
        )
        results.append(ClassifyResponse(
            action=result.action,
            confidence=result.confidence,
            reason=result.reason,
        ))

    return BatchClassifyResponse(results=results)


@router.get("/health")
async def router_health():
    """Check router service health."""
    service = get_router_service()
    model_available = await service.health_check()

    return {
        "status": "healthy" if model_available else "degraded",
        "model": service.model,
        "model_available": model_available,
        "fallback_enabled": True,
    }


@router.get("/actions")
async def list_actions():
    """List all available routing actions."""
    return {
        "actions": [
            {
                "name": action.value,
                "description": _get_action_description(action)
            }
            for action in RouterAction
        ]
    }


def _get_action_description(action: RouterAction) -> str:
    """Get human-readable description for an action."""
    descriptions = {
        RouterAction.DIRECT_ANSWER: "General knowledge questions handled by main AI model",
        RouterAction.RAG_SEARCH: "Questions requiring document retrieval (RAG)",
        RouterAction.VISION_ANALYSIS: "Questions about images or visual content",
        RouterAction.EXTERNAL_API: "Requests requiring real-time external data",
        RouterAction.MEMORY_LOOKUP: "References to previous conversation context",
    }
    return descriptions.get(action, "Unknown action")
