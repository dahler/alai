import time
import json
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.services.conversation import ConversationService
from app.services.message import MessageService
from app.services.ai import AIService
from app.services.document import DocumentService
from app.services.rag import RAGService
from app.services.knowledge_graph import KnowledgeGraphService
from app.router.service import RouterService
from app.router.constants import RouterAction
from app.middleware.auth import get_optional_user, get_session_id
from app.schemas.message import MessageResponse, SendMessageRequest, AttachmentInfo
from app.models.user import User
from app.models.message import Message
from app.models.attachment import Attachment
from app.agent.loop import AgentLoop

router = APIRouter(prefix="/conversations/{conversation_id}/messages", tags=["messages"])


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [CHAT] {message}")


def format_message_response(message: Message) -> dict:
    """Format message with attachments for response"""
    attachments = []
    for att in message.attachments:
        attachments.append(AttachmentInfo(
            id=att.id,
            filename=att.filename,
            original_filename=att.original_filename,
            content_type=att.content_type,
            file_size=att.file_size,
            url=f"/api/uploads/{att.filename}",
            is_image=att.content_type.startswith("image/"),
        ))

    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "attachments": attachments,
    }


@router.get("")
async def get_messages(
    conversation_id: int,
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = get_session_id(request, response) if not user else None
    conv_service = ConversationService(db)

    conversation = await conv_service.get_by_id(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if not await conv_service.can_access(conversation, user, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Fetch messages with attachments
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(selectinload(Message.attachments))
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()

    return [format_message_response(msg) for msg in messages]


@router.post("")
async def send_message(
    conversation_id: int,
    data: SendMessageRequest,
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = get_session_id(request, response) if not user else None
    conv_service = ConversationService(db)
    msg_service = MessageService(db)

    conversation = await conv_service.get_by_id(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if not await conv_service.can_access(conversation, user, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Save user message
    user_message = await msg_service.add_message(
        conversation_id=conversation_id,
        role="user",
        content=data.content,
        attachment_ids=data.attachment_ids,
    )

    # Reload message with attachments
    result = await db.execute(
        select(Message)
        .where(Message.id == user_message.id)
        .options(selectinload(Message.attachments))
    )
    user_message = result.scalar_one()

    return format_message_response(user_message)


@router.post("/stream")
async def send_message_stream(
    conversation_id: int,
    data: SendMessageRequest,
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    request_start = time.time()
    log("=" * 60)
    log("NEW CHAT REQUEST")
    log("=" * 60)
    log(f"Conversation ID: {conversation_id}")
    log(f"User message: {data.content[:100]}{'...' if len(data.content) > 100 else ''}")
    log(f"Attachments: {len(data.attachment_ids)} file(s)")

    session_id = get_session_id(request, response) if not user else None
    conv_service = ConversationService(db)
    msg_service = MessageService(db)
    ai_service = AIService()
    router_service = RouterService()

    conversation = await conv_service.get_by_id(conversation_id)
    if not conversation:
        log("✗ Conversation not found!")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if not await conv_service.can_access(conversation, user, session_id):
        log("✗ Access denied!")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    log("✓ Access verified")

    # Get attachment info for images and documents
    image_paths = []
    document_contents = []
    doc_service = DocumentService()

    if data.attachment_ids:
        log(f"Processing {len(data.attachment_ids)} attachment(s)...")
        result = await db.execute(
            select(Attachment).where(Attachment.id.in_(data.attachment_ids))
        )
        attachments = result.scalars().all()
        log(f"  Found {len(attachments)} attachment(s) in database")

        for att in attachments:
            log(f"  → {att.original_filename}")
            log(f"    Type: {att.content_type}")
            log(f"    Path: {att.file_path}")

            if att.content_type.startswith("image/"):
                image_paths.append(att.file_path)
                log(f"    ✓ Added as IMAGE")
            else:
                # Extract text from documents (PDF, TXT, etc.)
                log(f"    Extracting text...")
                text = await doc_service.extract_text(att.file_path)
                if text:
                    # Truncate if too long
                    text = doc_service.truncate_text(text, max_chars=12000)
                    document_contents.append(f"=== Document: {att.original_filename} ===\n{text}")
                    log(f"    ✓ Extracted {len(text)} chars")
                else:
                    log(f"    ✗ Failed to extract text")

        log(f"Summary: {len(image_paths)} image(s), {len(document_contents)} document(s)")

    # Router classification
    log("-" * 60)
    log("ROUTER CLASSIFICATION")
    log("-" * 60)
    router_result = await router_service.classify(
        query=data.content,
        has_attachments=len(data.attachment_ids) > 0,
        has_images=len(image_paths) > 0,
    )
    log(f"Router decision: {router_result.action.value} ({router_result.confidence:.0%})")

    # RAG Search with Knowledge Graph if needed
    rag_context = ""
    if router_result.action == RouterAction.RAG_SEARCH:
        log("-" * 60)
        log("HYBRID RAG RETRIEVAL (Vector + Knowledge Graph)")
        log("-" * 60)

        # Use Knowledge Graph hybrid search for better results
        kg_service = KnowledgeGraphService(db)
        hybrid_results = await kg_service.hybrid_search(
            query=data.content,
            user_id=user.id if user else None,
            top_k=5,
            vector_weight=0.6,
            graph_weight=0.4,
        )

        if hybrid_results:
            rag_chunks = []
            for result in hybrid_results:
                # Build context including graph information
                chunk_info = f"[Source: {result.filename}"
                if result.source == "hybrid":
                    chunk_info += f" | Vector: {result.vector_score:.0%}, Graph: {result.graph_score:.0%}"
                elif result.source == "vector":
                    chunk_info += f" | Similarity: {result.vector_score:.0%}"
                else:
                    chunk_info += f" | Graph score: {result.graph_score:.0%}"
                chunk_info += "]\n"

                # Add entity context if available
                if result.matched_entities:
                    entities_str = ", ".join(
                        f"{e['name']} ({e['type']})"
                        for e in result.matched_entities[:3]
                    )
                    chunk_info += f"Related entities: {entities_str}\n"

                # Add relationship context if available
                if result.relationships:
                    rels_str = "; ".join(
                        f"{r.get('source_name', 'Entity')} {r['relation']} {r.get('target_name', 'Entity')}"
                        for r in result.relationships[:2]
                    )
                    chunk_info += f"Relationships: {rels_str}\n"

                chunk_info += f"\n{result.chunk_text}"
                rag_chunks.append(chunk_info)

            rag_context = "\n\n---\n\n".join(rag_chunks)
            log(f"✓ Retrieved {len(hybrid_results)} relevant chunks via hybrid search")
            log(f"  Sources: {sum(1 for r in hybrid_results if r.source == 'vector')} vector, "
                f"{sum(1 for r in hybrid_results if r.source == 'graph')} graph, "
                f"{sum(1 for r in hybrid_results if r.source == 'hybrid')} hybrid")
        else:
            # Fallback to basic RAG if no hybrid results
            log("⚠ No hybrid results, falling back to basic vector search")
            rag_service = RAGService(db)
            rag_results = await rag_service.search(
                query=data.content,
                user_id=user.id if user else None,
                top_k=5,
            )
            if rag_results:
                rag_chunks = []
                for result in rag_results:
                    rag_chunks.append(
                        f"[Source: {result['filename']} (similarity: {result['similarity']:.0%})]\n{result['chunk_text']}"
                    )
                rag_context = "\n\n---\n\n".join(rag_chunks)
                log(f"✓ Retrieved {len(rag_results)} relevant chunks (vector only)")
            else:
                log("⚠ No relevant documents found")

    # Save user message first
    log("Saving user message to database...")
    await msg_service.add_message(
        conversation_id=conversation_id,
        role="user",
        content=data.content,
        attachment_ids=data.attachment_ids,
    )
    log("✓ User message saved")

    # Get conversation history for context
    history = await msg_service.get_recent_context(conversation_id, limit=20)
    log(f"Loaded {len(history)} message(s) for context")

    # Build the final user message with document content
    user_message = data.content

    # Add RAG context if available
    if rag_context:
        user_message = f"""The following information was retrieved from the knowledge base:

{rag_context}

---

User's question: {data.content}

Please answer based on the retrieved information above. If the information doesn't fully answer the question, say so."""
        log(f"Enhanced message with RAG context ({len(user_message)} total chars)")

    # Add directly attached document content (for newly uploaded docs)
    elif document_contents:
        doc_text = "\n\n".join(document_contents)
        user_message = f"""The user has attached the following document(s):

{doc_text}

User's request: {data.content}"""
        log(f"Enhanced message with {len(document_contents)} document(s) ({len(user_message)} total chars)")

    # Handle AGENTIC mode - use agent loop for complex multi-step tasks
    if router_result.action == RouterAction.AGENTIC:
        log("-" * 60)
        log("STARTING AGENTIC MODE")
        log("-" * 60)

        async def generate_agentic():
            full_response = ""
            gen_start = time.time()

            try:
                # Create agent loop
                agent = AgentLoop(
                    ai_service=ai_service,
                    db_session=db,
                    user_id=user.id if user else None,
                    max_steps=10,
                    verbose=True,
                )

                # Convert history to dict format for agent
                context = [{"role": msg.role, "content": msg.content} for msg in history]

                # Stream agent output
                async for output in agent.run_streaming(data.content, context):
                    full_response += output
                    # Escape for SSE format
                    for line in output.split('\n'):
                        yield f"data: {line}\n"
                    yield "\n"

                gen_elapsed = time.time() - gen_start
                log("-" * 60)
                log("AGENTIC MODE COMPLETE")
                log("-" * 60)
                log(f"Response length: {len(full_response)} chars")
                log(f"Generation time: {gen_elapsed:.2f}s")
                log(f"Agent steps: {len(agent.trace.steps) if agent.trace else 0}")

                # Save assistant message
                log("Saving assistant message...")
                await msg_service.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=full_response,
                )
                log("✓ Assistant message saved")

                # Update conversation title if first message
                if len(history) <= 1:
                    log("Generating conversation title...")
                    title = await ai_service.generate_title(data.content)
                    await conv_service.update_title(conversation_id, title)
                    log(f"✓ Title set: {title}")

                total_elapsed = time.time() - request_start
                log("=" * 60)
                log(f"REQUEST COMPLETE - Total time: {total_elapsed:.2f}s")
                log("=" * 60)

                yield "data: [DONE]\n\n"

            except Exception as e:
                import traceback
                log(f"✗ AGENTIC ERROR: {str(e)}")
                log(traceback.format_exc())
                yield f"data: [ERROR] {str(e)}\n\n"

        return StreamingResponse(
            generate_agentic(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Standard AI generation (non-agentic)
    log("-" * 60)
    log("STARTING AI GENERATION")
    log("-" * 60)

    async def generate():
        full_response = ""
        gen_start = time.time()
        try:
            async for chunk in ai_service.generate_response_stream(
                history, user_message, image_paths=image_paths
            ):
                full_response += chunk
                yield f"data: {chunk}\n\n"

            gen_elapsed = time.time() - gen_start
            log("-" * 60)
            log("AI GENERATION COMPLETE")
            log("-" * 60)
            log(f"Response length: {len(full_response)} chars")
            log(f"Generation time: {gen_elapsed:.2f}s")

            # Save assistant message after streaming completes
            log("Saving assistant message...")
            await msg_service.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_response,
            )
            log("✓ Assistant message saved")

            # Update conversation title if this is the first message
            if len(history) <= 1:
                log("Generating conversation title...")
                # Use original content for title, not the enhanced message
                title = await ai_service.generate_title(data.content)
                await conv_service.update_title(conversation_id, title)
                log(f"✓ Title set: {title}")

            total_elapsed = time.time() - request_start
            log("=" * 60)
            log(f"REQUEST COMPLETE - Total time: {total_elapsed:.2f}s")
            log("=" * 60)

            yield "data: [DONE]\n\n"
        except Exception as e:
            import traceback
            log(f"✗ ERROR: {str(e)}")
            log(traceback.format_exc())
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
