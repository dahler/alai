"""
Integration example: How to use the Router with your existing chatbot flow.

This module shows how to integrate the router into your message processing pipeline.
"""

from typing import AsyncGenerator, Optional, Callable, Awaitable
import logging

from app.router.service import RouterService
from app.router.constants import RouterAction, RouterResult, CONFIDENCE_THRESHOLD_LOW

logger = logging.getLogger(__name__)


class RoutedChatHandler:
    """
    Example integration of Router with existing chat flow.

    This orchestrates the workflow based on router classification.
    """

    def __init__(
        self,
        router: RouterService,
        # Your existing service callbacks
        direct_answer_fn: Callable[..., Awaitable[AsyncGenerator[str, None]]],
        rag_search_fn: Optional[Callable[..., Awaitable[str]]] = None,
        vision_fn: Optional[Callable[..., Awaitable[str]]] = None,
        external_api_fn: Optional[Callable[..., Awaitable[str]]] = None,
        memory_fn: Optional[Callable[..., Awaitable[str]]] = None,
    ):
        self.router = router
        self.direct_answer_fn = direct_answer_fn
        self.rag_search_fn = rag_search_fn
        self.vision_fn = vision_fn
        self.external_api_fn = external_api_fn
        self.memory_fn = memory_fn

    async def handle_message(
        self,
        query: str,
        conversation_history: list,
        image_paths: Optional[list] = None,
        attachment_paths: Optional[list] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Process a message through the router and appropriate handler.

        Args:
            query: User's message
            conversation_history: Previous messages for context
            image_paths: Paths to attached images
            attachment_paths: Paths to other attachments

        Yields:
            Response chunks from the appropriate handler
        """
        has_images = bool(image_paths)
        has_attachments = bool(attachment_paths) or has_images

        # Step 1: Classify the request
        classification = await self.router.classify(
            query=query,
            has_attachments=has_attachments,
            has_images=has_images,
        )

        logger.info(
            f"[ROUTED_CHAT] Action: {classification.action}, "
            f"Confidence: {classification.confidence}"
        )

        # Step 2: Execute the appropriate workflow
        context = None

        if classification.action == RouterAction.RAG_SEARCH and self.rag_search_fn:
            # Retrieve relevant documents first
            context = await self.rag_search_fn(query, attachment_paths)
            query = f"Based on the following context:\n{context}\n\nAnswer: {query}"

        elif classification.action == RouterAction.VISION_ANALYSIS and self.vision_fn:
            # Vision analysis is handled by passing images to the model
            # No pre-processing needed, just ensure vision model is used
            pass

        elif classification.action == RouterAction.EXTERNAL_API and self.external_api_fn:
            # Fetch external data first
            external_data = await self.external_api_fn(query)
            query = f"Current data: {external_data}\n\nUser question: {query}"

        elif classification.action == RouterAction.MEMORY_LOOKUP and self.memory_fn:
            # Retrieve relevant memory/context
            memory_context = await self.memory_fn(query, conversation_history)
            query = f"Previous context: {memory_context}\n\nContinue with: {query}"

        # Step 3: Generate response using your existing AI service
        async for chunk in self.direct_answer_fn(
            messages=conversation_history,
            user_message=query,
            image_paths=image_paths if classification.action == RouterAction.VISION_ANALYSIS else None,
        ):
            yield chunk


# Example usage with your existing AIService
async def example_integration():
    """
    Example showing how to integrate with your existing code.
    """
    from app.services.ai import AIService
    from app.router.service import RouterService

    # Initialize services
    router = RouterService()
    ai_service = AIService()

    # Create routed handler
    handler = RoutedChatHandler(
        router=router,
        direct_answer_fn=ai_service.generate_response_stream,
        # Add your other service functions here:
        # rag_search_fn=your_rag_service.search,
        # vision_fn=your_vision_service.analyze,
        # external_api_fn=your_api_service.fetch,
        # memory_fn=your_memory_service.retrieve,
    )

    # Process a message
    async for chunk in handler.handle_message(
        query="What is Python?",
        conversation_history=[],
    ):
        print(chunk, end="", flush=True)


# Simplified integration for your existing message endpoint
async def route_and_process(
    query: str,
    conversation_history: list,
    image_paths: Optional[list] = None,
    attachment_paths: Optional[list] = None,
) -> dict:
    """
    Simple function to get routing decision.

    Use this in your existing endpoint to decide workflow.

    Returns:
        dict with 'action', 'confidence', and 'should_use_vision'
    """
    router = RouterService()

    result = await router.classify(
        query=query,
        has_attachments=bool(attachment_paths),
        has_images=bool(image_paths),
    )

    return {
        "action": result.action,
        "confidence": result.confidence,
        "should_use_vision": result.action == RouterAction.VISION_ANALYSIS,
        "needs_rag": result.action == RouterAction.RAG_SEARCH,
        "needs_external_api": result.action == RouterAction.EXTERNAL_API,
        "needs_memory": result.action == RouterAction.MEMORY_LOOKUP,
        "is_confident": result.confidence >= CONFIDENCE_THRESHOLD_LOW,
    }
