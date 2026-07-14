import time
import json
from fastapi import (
    APIRouter, Depends, HTTPException, status, Request, Response
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
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
from app.schemas.message import SendMessageRequest, AttachmentInfo
from app.models.user import User
from app.models.message import Message
from app.models.attachment import Attachment
from app.models.attachment_chunk import AttachmentChunk
from app.agent.pipeline import AgentPipeline as AgentLoop

router = APIRouter(
    prefix="/conversations/{conversation_id}/messages",
    tags=["messages"],
)

_RAG_INSTRUCTIONS = (
    "Instructions:\n"
    "- LANGUAGE: You MUST reply in the exact same language the user used to "
    "ask their question. If the question is in Indonesian, your entire answer "
    "must be in Indonesian. If the question is in English, answer in English. "
    "Never switch languages mid-answer.\n"
    "- ACCURACY: Use ONLY information explicitly stated in the retrieved "
    "content above. Do NOT invent, infer, elaborate beyond, or add anything "
    "not literally present in the sources — even if it sounds reasonable.\n"
    "- SCOPE: Focus on sections that directly answer the user's question. "
    "Omit standalone framing sections (e.g. 'Pendahuluan', 'Peran dan "
    "Tanggung Jawab') unless explicitly asked. When you cover a section, "
    "always include ALL of its sub-sections — never skip one.\n"
    "- HEADINGS: Each chunk header has the format 'number | title'. Use only "
    "the title part (after the '|') as the heading — strip the number and "
    "the '|' entirely (e.g. use 'Inisiasi, perencanaan dan perancangan', "
    "not '2.1.1 Inisiasi, perencanaan dan perancangan').\n"
    "- DETAIL: Under each heading write thorough paragraphs covering the full "
    "purpose, every activity, all parties involved, any criteria or "
    "conditions, and the outcome — exactly as described in the source. "
    "Do not compress into bullet fragments or one-liners.\n"
    "- CITATIONS: Cite the source number inline at the end of each "
    "paragraph, e.g. [1].\n"
    "- GAPS: If the retrieved content does not fully answer the question, "
    "say so explicitly."
)


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [CHAT] {message}")


# Characters available for input before output starts getting squeezed.
# num_ctx=16384 tokens × 4 chars/token = 65536 total chars.
# Reserve ~8192 tokens (32768 chars) for output, ~2000 chars for overhead
# (system prompt + history + question + instructions).
_MAX_INPUT_CHARS = 30000
_LARGE_DOC_THRESHOLD = 12_000  # chars — above this, analyze in chunks
_CHUNK_SIZE = 8_000             # chars per analysis chunk


def _split_doc_chunks(text: str, chunk_size: int = _CHUNK_SIZE) -> list[str]:
    """Split text at paragraph boundaries into chunks ≤ chunk_size chars."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            split = text.rfind('\n\n', start, end)
            if split <= start:
                split = text.rfind('\n', start, end)
            if split <= start:
                split = end
        else:
            split = end
        chunk = text[start:split].strip()
        if chunk:
            chunks.append(chunk)
        start = max(split + 1, start + 1)
    return chunks


async def _focus_extract(
    ai_service: AIService,
    doc_text: str,
    query: str,
) -> str:
    """
    Make a preliminary LLM call to extract only the sections of `doc_text`
    that are relevant to `query`. Used when the combined context (attachment
    + RAG) would exceed the model's input budget.
    """
    prompt = (
        f"From the document below, extract ONLY the passages relevant to "
        f"this question: {query}\n\n"
        f"Keep the original wording. Be concise. "
        f"If nothing is relevant, say 'No relevant content found.'\n\n"
        f"{doc_text}"
    )
    result = await ai_service.generate_response(
        [{"role": "user", "content": prompt}]
    )
    return f"[Relevant excerpts extracted]\n{result}"


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

    user_message = await msg_service.add_message(
        conversation_id=conversation_id,
        role="user",
        content=data.content,
        attachment_ids=data.attachment_ids,
    )

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
    preview = data.content[:100] + ("..." if len(data.content) > 100 else "")
    log(f"User message: {preview}")
    log(f"Attachments: {len(data.attachment_ids)} file(s)")

    session_id = get_session_id(request, response) if not user else None
    conv_service = ConversationService(db)
    msg_service = MessageService(db)
    ai_service = AIService()
    router_service = RouterService()

    conversation = await conv_service.get_by_id(conversation_id)
    if not conversation:
        log("Conversation not found!")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if not await conv_service.can_access(conversation, user, session_id):
        log("Access denied!")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    log("Access verified")

    image_paths = []
    document_contents = []
    # attachment_id -> list of chunk texts (populated for large docs)
    attachment_chunk_map: dict[int, list[str]] = {}
    doc_service = DocumentService()

    if data.attachment_ids:
        log(f"Processing {len(data.attachment_ids)} attachment(s)...")
        result = await db.execute(
            select(Attachment).where(
                Attachment.id.in_(data.attachment_ids)
            )
        )
        attachments = result.scalars().all()
        log(f"  Found {len(attachments)} attachment(s) in database")

        for att in attachments:
            log(f"  -> {att.original_filename}")
            log(f"     Type: {att.content_type}")

            if att.content_type.startswith("image/"):
                image_paths.append(att.file_path)
                log("     Added as IMAGE")
            else:
                # Check if chunks already exist in DB for this attachment
                existing = await db.execute(
                    select(AttachmentChunk)
                    .where(AttachmentChunk.attachment_id == att.id)
                    .order_by(AttachmentChunk.chunk_index)
                )
                stored_chunks = existing.scalars().all()

                if stored_chunks:
                    log(
                        f"     Loaded {len(stored_chunks)} cached chunk(s) "
                        f"from DB"
                    )
                    attachment_chunk_map[att.id] = [
                        c.chunk_text for c in stored_chunks
                    ]
                else:
                    log("     Extracting text...")
                    text = await doc_service.extract_text(att.file_path)
                    if text:
                        text = doc_service.truncate_text(
                            text, max_chars=80000
                        )
                        full_doc = (
                            f"=== Document: {att.original_filename}"
                            f" ===\n{text}"
                        )
                        log(f"     Extracted {len(text)} chars")

                        if len(full_doc) > _LARGE_DOC_THRESHOLD:
                            chunks = _split_doc_chunks(full_doc)
                            log(
                                f"     Splitting into {len(chunks)} chunk(s)"
                                f" — persisting to DB"
                            )
                            for idx, chunk_text in enumerate(chunks):
                                db.add(AttachmentChunk(
                                    attachment_id=att.id,
                                    chunk_index=idx,
                                    total_chunks=len(chunks),
                                    chunk_text=chunk_text,
                                ))
                            await db.flush()
                            attachment_chunk_map[att.id] = chunks
                        else:
                            document_contents.append(full_doc)
                    else:
                        log("     Failed to extract text")

        log(
            f"Summary: {len(image_paths)} image(s), "
            f"{len(document_contents)} small doc(s), "
            f"{len(attachment_chunk_map)} chunked doc(s)"
        )

    # No attachment on this message — check if a recent message in this
    # conversation had chunked documents and reuse them automatically.
    # This lets users ask follow-up questions without re-uploading the file.
    if not data.attachment_ids and not image_paths and not document_contents:
        from sqlalchemy import func as _func
        from app.models.message import Message as _Msg
        recent_chunks_q = await db.execute(
            select(AttachmentChunk)
            .join(Attachment, AttachmentChunk.attachment_id == Attachment.id)
            .join(_Msg, Attachment.message_id == _Msg.id)
            .where(_Msg.conversation_id == conversation_id)
            .order_by(
                _Msg.created_at.desc(),
                AttachmentChunk.chunk_index.asc(),
            )
        )
        recent_chunks = recent_chunks_q.scalars().all()
        if recent_chunks:
            # Group by attachment_id preserving the order from the latest msg
            seen_att: dict[int, list[str]] = {}
            for c in recent_chunks:
                seen_att.setdefault(c.attachment_id, []).append(c.chunk_text)
            # Use only the most recently uploaded attachment
            latest_att_id = next(iter(seen_att))
            attachment_chunk_map[latest_att_id] = seen_att[latest_att_id]
            log(
                f"Auto-reusing {len(seen_att[latest_att_id])} chunk(s) "
                f"from attachment {latest_att_id} (no file attached)"
            )

    # Check if this user has any documents in their knowledge base
    from app.models.document_chunk import DocumentChunk
    from sqlalchemy import func as sql_func
    kb_count_result = await db.execute(
        select(sql_func.count()).select_from(DocumentChunk).where(
            (DocumentChunk.user_id == user.id) | DocumentChunk.is_company_doc
            if user else DocumentChunk.is_company_doc
        )
    )
    has_knowledge_base = (kb_count_result.scalar() or 0) > 0

    # Language detection + routing
    log("-" * 60)
    log("LANGUAGE DETECTION & ROUTING")
    log("-" * 60)
    query_lang, english_query = await router_service.detect_and_translate(
        data.content
    )
    if query_lang != "en":
        log(f"Detected language: {query_lang} -> translating for routing")
    else:
        log("Language: en (no translation needed)")

    router_result = await router_service.classify(
        query=english_query,
        has_attachments=len(data.attachment_ids) > 0,
        has_images=len(image_paths) > 0,
        has_knowledge_base=has_knowledge_base,
    )
    log(
        f"Router decision: {router_result.action.value} "
        f"({router_result.confidence:.0%})"
    )

    rag_context = ""
    rag_sources: list[dict] = []

    do_rag = router_result.action == RouterAction.RAG_SEARCH

    if do_rag:
        log("-" * 60)
        label = (
            "Vector + Knowledge Graph"
            if settings.ENABLE_KNOWLEDGE_GRAPH
            else "Vector + Section Group Expansion"
        )
        log(f"RAG RETRIEVAL ({label})")
        log("-" * 60)

        if settings.ENABLE_KNOWLEDGE_GRAPH:
            kg_service = KnowledgeGraphService(db)
            hybrid_results = await kg_service.hybrid_search(
                query=data.content,
                user_id=user.id if user else None,
                top_k=5,
                vector_weight=0.6,
                graph_weight=0.4,
            )
            if hybrid_results:
                seen_doc_ids: set[int] = set()
                for r in hybrid_results:
                    if r.document_id not in seen_doc_ids:
                        seen_doc_ids.add(r.document_id)
                        rag_sources.append({
                            "number": len(rag_sources) + 1,
                            "filename": r.filename,
                            "stored_filename": r.stored_filename,
                            "document_id": r.document_id,
                            "chunk_text": r.chunk_text,
                        })
                doc_to_num = {
                    s["document_id"]: s["number"] for s in rag_sources
                }
                rag_chunks = []
                for result in hybrid_results:
                    src_num = doc_to_num[result.document_id]
                    chunk_info = f"[{src_num}] {result.filename}"
                    if result.source == "hybrid":
                        chunk_info += (
                            f" (vector {result.vector_score:.0%},"
                            f" graph {result.graph_score:.0%})"
                        )
                    elif result.source == "vector":
                        chunk_info += (
                            f" (similarity {result.vector_score:.0%})"
                        )
                    else:
                        chunk_info += (
                            f" (graph score {result.graph_score:.0%})"
                        )
                    chunk_info += "\n"
                    if result.matched_entities:
                        entities_str = ", ".join(
                            f"{e['name']} ({e['type']})"
                            for e in result.matched_entities[:3]
                        )
                        chunk_info += f"Related entities: {entities_str}\n"
                    if result.relationships:
                        rels_str = "; ".join(
                            f"{r.get('source_name', 'Entity')} "
                            f"{r['relation']} "
                            f"{r.get('target_name', 'Entity')}"
                            for r in result.relationships[:2]
                        )
                        chunk_info += f"Relationships: {rels_str}\n"
                    chunk_info += f"\n{result.chunk_text}"
                    rag_chunks.append(chunk_info)
                rag_context = "\n\n---\n\n".join(rag_chunks)
                log(
                    f"Retrieved {len(hybrid_results)} chunks "
                    f"from {len(rag_sources)} document(s)"
                )
            else:
                log("No hybrid results found")

        else:
            # Knowledge graph disabled — use RAGService directly so section
            # group expansion and BM25 re-ranking are applied.
            rag_service = RAGService(db)
            rag_results = await rag_service.search(
                query=data.content,
                user_id=user.id if user else None,
            )
            if rag_results:
                seen_doc_ids_v: set[int] = set()
                for r in rag_results:
                    doc_id = r.get("attachment_id", 0)
                    if doc_id and doc_id not in seen_doc_ids_v:
                        seen_doc_ids_v.add(doc_id)
                        rag_sources.append({
                            "number": len(rag_sources) + 1,
                            "filename": r["filename"],
                            "stored_filename": r.get("stored_filename", ""),
                            "document_id": doc_id,
                        })
                doc_to_num_v = {
                    s["document_id"]: s["number"] for s in rag_sources
                }
                rag_chunks = []
                for r in rag_results:
                    doc_id = r.get("attachment_id", 0)
                    num = doc_to_num_v.get(doc_id, "?")
                    heading = r.get("heading_context", "")
                    header = (
                        f"[{num}] {r['filename']} | {heading}"
                        if heading else
                        f"[{num}] {r['filename']}"
                    )
                    chunk_text = r['chunk_text'][:4000]
                    rag_chunks.append(f"{header}\n\n{chunk_text}")
                rag_context = "\n\n---\n\n".join(rag_chunks)
                # Hard cap: stay within model context window
                if len(rag_context) > 24000:
                    rag_context = rag_context[:24000]
                log(
                    f"Retrieved {len(rag_results)} chunks "
                    f"from {len(rag_sources)} document(s) "
                    f"({len(rag_context)} chars)"
                )
            else:
                log("No relevant documents found")

    log("Saving user message to database...")
    await msg_service.add_message(
        conversation_id=conversation_id,
        role="user",
        content=data.content,
        attachment_ids=data.attachment_ids,
    )
    log("User message saved")

    history = await msg_service.get_recent_context(conversation_id, limit=6)
    log(f"Loaded {len(history)} message(s) for context")

    user_message = data.content
    # All chunks across all chunked attachments, in order
    doc_chunks: list[str] = []
    for att_id in data.attachment_ids:
        if att_id in attachment_chunk_map:
            doc_chunks.extend(attachment_chunk_map[att_id])

    # If attachment + RAG combined would overflow the input budget, run a
    # focused extraction pass on each attachment first so only the sections
    # relevant to the user's query are kept.
    # Only applies when BOTH are present — large-doc queries use doc_chunks.
    if document_contents and rag_context:
        total_chars = (
            sum(len(d) for d in document_contents) + len(rag_context)
        )
        if total_chars > _MAX_INPUT_CHARS:
            log(
                f"Context too large ({total_chars} chars) — "
                "extracting relevant sections from attachment(s)..."
            )
            extracted = []
            for doc in document_contents:
                focused = await _focus_extract(
                    ai_service, doc, data.content
                )
                extracted.append(focused)
                log(
                    f"  Extracted {len(focused)} chars "
                    f"(was {len(doc)} chars)"
                )
            document_contents = extracted

    if rag_context and document_contents:
        # Small attachment + RAG — combine both contexts
        doc_text = "\n\n".join(document_contents)
        source_list = "\n".join(
            f"[{s['number']}] {s['filename']}" for s in rag_sources
        )
        user_message = (
            "The user has attached the following document(s) for analysis:"
            f"\n\n{doc_text}"
            "\n\n---\n\n"
            "The following reference material was retrieved from the"
            " knowledge base:"
            f"\n\nSources:\n{source_list}"
            f"\n\nRetrieved content:\n{rag_context}"
            f"\n\n---\n\nUser's question: {data.content}"
            f"\n\n{_RAG_INSTRUCTIONS}"
        )
        log(
            f"Enhanced message with attachment + RAG context "
            f"({len(user_message)} chars)"
        )

    elif rag_context:
        source_list = "\n".join(
            f"[{s['number']}] {s['filename']}" for s in rag_sources
        )
        user_message = (
            "The following information was retrieved from the knowledge base:"
            f"\n\nSources:\n{source_list}"
            f"\n\nRetrieved content:\n{rag_context}"
            f"\n\n---\n\nUser's question: {data.content}"
            f"\n\n{_RAG_INSTRUCTIONS}"
        )
        log(f"Enhanced message with RAG context ({len(user_message)} chars)")

    elif document_contents:
        # Small doc — single call
        doc_text = "\n\n".join(document_contents)
        user_message = (
            f"The user has attached the following document(s):\n\n"
            f"{doc_text}\n\nUser's request: {data.content}"
        )
        log(
            f"Enhanced message with {len(document_contents)} document(s) "
            f"({len(user_message)} total chars)"
        )

    if doc_chunks:
        log(f"Chunked analysis: {len(doc_chunks)} chunk(s) ready")

    if router_result.action == RouterAction.AGENTIC:
        log("-" * 60)
        log("STARTING AGENTIC MODE")
        log("-" * 60)

        if query_lang != "en":
            agent_task = (
                f"{english_query}\n\n"
                f"(Original query in {query_lang}: {data.content})\n"
                f"IMPORTANT: Respond in {query_lang} "
                f"(same language as the original query)."
            )
        else:
            agent_task = data.content

        async def generate_agentic():
            full_response = ""
            gen_start = time.time()

            try:
                agent = AgentLoop(
                    ai_service=ai_service,
                    db_session=db,
                    user_id=user.id if user else None,
                    max_steps=10,
                    verbose=True,
                )

                context = [
                    {"role": msg.role, "content": msg.content}
                    for msg in history
                ]

                async for output in agent.run_streaming(
                    agent_task, context, show_steps=False
                ):
                    full_response += output
                    yield f"data: {json.dumps(output)}\n\n"

                gen_elapsed = time.time() - gen_start
                log("-" * 60)
                log("AGENTIC MODE COMPLETE")
                log("-" * 60)
                log(f"Response length: {len(full_response)} chars")
                log(f"Generation time: {gen_elapsed:.2f}s")
                steps = (
                    len(agent.trace.steps) if agent.trace else 0
                )
                log(f"Agent steps: {steps}")

                log("Saving assistant message...")
                await msg_service.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=full_response,
                    sources=rag_sources if rag_sources else None,
                )
                log("Assistant message saved")

                if len(history) <= 1:
                    log("Generating conversation title...")
                    title = await ai_service.generate_title(data.content)
                    await conv_service.update_title(conversation_id, title)
                    log(f"Title set: {title}")

                total_elapsed = time.time() - request_start
                log("=" * 60)
                log(f"REQUEST COMPLETE - Total time: {total_elapsed:.2f}s")
                log("=" * 60)

                if rag_sources:
                    yield f"data: [SOURCES]{json.dumps(rag_sources)}\n\n"
                yield "data: [DONE]\n\n"

            except Exception as e:
                import traceback
                log(f"AGENTIC ERROR: {str(e)}")
                log(traceback.format_exc())
                try:
                    await db.rollback()
                except Exception:
                    pass
                yield f"data: [ERROR] {str(e)}\n\n"
            finally:
                try:
                    await db.close()
                except Exception:
                    pass

        return StreamingResponse(
            generate_agentic(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    log("-" * 60)
    log("STARTING AI GENERATION")
    log("-" * 60)

    async def generate():
        full_response = ""
        gen_start = time.time()
        try:
            if doc_chunks:
                # Large document: stream analysis chunk by chunk.
                # Build condensed history so the LLM knows what was said in
                # previous turns (e.g. "find issues" → "fix them all").
                # Truncate long assistant responses to avoid blowing up the
                # per-chunk context, but keep enough to be meaningful.
                _MAX_ASST_CHARS = 6000
                chunk_history_base = []
                for msg in history:
                    role = (
                        msg.role if hasattr(msg, 'role') else msg['role']
                    )
                    content = (
                        msg.content
                        if hasattr(msg, 'content')
                        else msg['content']
                    )
                    if role == 'assistant' and len(content) > _MAX_ASST_CHARS:
                        content = (
                            content[:_MAX_ASST_CHARS]
                            + "\n...[previous response truncated]"
                        )
                    chunk_history_base.append(
                        {"role": role, "content": content}
                    )

                n = len(doc_chunks)
                log(f"Chunked analysis: {n} section(s)")
                intro = f"*Analyzing document in {n} part(s)...*\n\n"
                full_response += intro
                yield f"data: {intro}\n\n"

                for i, chunk_text in enumerate(doc_chunks, 1):
                    header = f"---\n\n**Part {i} of {n}**\n\n"
                    full_response += header
                    for line in header.splitlines(keepends=True):
                        yield f"data: {line}\n\n"

                    chunk_prompt = (
                        f"Document section ({i} of {n}):\n\n"
                        f"{chunk_text}\n\n"
                        f"User's task: {data.content}\n\n"
                        "Address ONLY this section. Be specific and thorough."
                    )
                    chunk_messages = chunk_history_base + [
                        {"role": "user", "content": chunk_prompt}
                    ]
                    async for token in ai_service.generate_response_stream(
                        chunk_messages
                    ):
                        full_response += token
                        yield f"data: {token}\n\n"

                    yield "data: \n\n"
            else:
                async for chunk in ai_service.generate_response_stream(
                    history, user_message, image_paths=image_paths,
                    use_agent_model=do_rag,
                ):
                    full_response += chunk
                    yield f"data: {chunk}\n\n"

            if not full_response.strip() and do_rag:
                fallback = (
                    "Maaf, saya tidak dapat menemukan informasi yang "
                    "relevan dalam dokumen yang tersedia untuk menjawab "
                    "pertanyaan ini."
                )
                full_response = fallback
                yield f"data: {fallback}\n\n"

            gen_elapsed = time.time() - gen_start
            log("-" * 60)
            log("AI GENERATION COMPLETE")
            log("-" * 60)
            log(f"Response length: {len(full_response)} chars")
            log(f"Generation time: {gen_elapsed:.2f}s")

            log("Saving assistant message...")
            await msg_service.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_response,
            )
            log("Assistant message saved")

            if len(history) <= 1:
                log("Generating conversation title...")
                title = await ai_service.generate_title(data.content)
                await conv_service.update_title(conversation_id, title)
                log(f"Title set: {title}")

            total_elapsed = time.time() - request_start
            log("=" * 60)
            log(f"REQUEST COMPLETE - Total time: {total_elapsed:.2f}s")
            log("=" * 60)

            if rag_sources:
                yield f"data: [SOURCES]{json.dumps(rag_sources)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            import traceback
            log(f"ERROR: {str(e)}")
            log(traceback.format_exc())
            try:
                await db.rollback()
            except Exception:
                pass
            yield f"data: [ERROR] {str(e)}\n\n"
        finally:
            try:
                await db.close()
            except Exception:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
