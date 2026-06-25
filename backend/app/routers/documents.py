"""
Documents API router — Docling-based ingestion architecture.
"""

from fastapi import (
    APIRouter, BackgroundTasks, Depends, HTTPException,
    status, UploadFile, File, Form,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.middleware.auth import get_current_user, get_optional_user
from app.models.user import User
from app.models.attachment import Attachment
from app.models.document_chunk import DocumentChunk
from app.models.document_folder import DocumentFolder
from app.services.rag import RAGService
from app.services.docling_service import DoclingService
from app.services.knowledge_graph import (
    KnowledgeGraphService,
    extract_graph_background,
)
from app.services.storage import StorageService
from app.config import settings

router = APIRouter(prefix="/documents", tags=["documents"])
storage_service = StorageService()

# All MIME types accepted for ingestion
ALLOWED_CONTENT_TYPES: set[str] = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument"
    ".wordprocessingml.document",           # .docx
    "application/vnd.openxmlformats-officedocument"
    ".presentationml.presentation",          # .pptx
    "application/vnd.openxmlformats-officedocument"
    ".spreadsheetml.sheet",                  # .xlsx
    "text/html",
    "message/rfc822",                        # .eml
    "application/vnd.ms-outlook",            # .msg
    "text/plain",
    "text/markdown",
    "application/json",
    "text/xml",
}


def _is_allowed(content_type: str) -> bool:
    return (
        content_type in ALLOWED_CONTENT_TYPES
        or content_type.startswith("text/")
    )


@router.get("")
async def list_documents(
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """List all documents accessible by the current user."""
    rag = RAGService(db)
    company_docs = await rag.get_company_documents()
    personal_docs = await rag.get_user_documents(user.id) if user else []
    return {
        "personal_documents": personal_docs,
        "company_documents": company_docs,
    }


@router.post("/reembed-sections")
async def reembed_sections(
    attachment_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Backfill summary_embedding for sections that have none.
    Pass ?attachment_id=<id> to fix one doc, or omit to fix all.
    """
    rag = RAGService(db)
    result = await rag.reembed_sections(attachment_id=attachment_id)
    return result


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    is_company_doc: bool = Form(False),
    extract_graph: bool = Form(True),
    folder_id: Optional[int] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload and ingest a document using the Docling pipeline.

    Phase 1 (sync): parse → sections → summaries → chunks → embeddings
    Phase 2 (async): entity + knowledge-graph extraction
    """
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File too large. Maximum size is "
                f"{settings.MAX_FILE_SIZE // (1024 * 1024)}MB"
            ),
        )
    await file.seek(0)

    if not _is_allowed(file.content_type or ""):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type '{file.content_type}' is not supported.",
        )

    file_info = await storage_service.save_file(file)
    attachment = Attachment(
        filename=file_info["filename"],
        original_filename=file_info["original_filename"],
        content_type=file_info["content_type"],
        file_size=file_info["file_size"],
        file_path=file_info["file_path"],
        user_id=user.id,
        is_company_doc=is_company_doc,
        graph_status="pending" if (extract_graph and settings.ENABLE_KNOWLEDGE_GRAPH) else None,
        processing_status="uploaded",
        folder_id=folder_id,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    # Phase 1 (sync): Docling ingestion pipeline
    rag = RAGService(db)
    stats = await rag.embed_document(
        attachment_id=attachment.id,
        user_id=user.id,
        is_company_doc=is_company_doc,
    )

    if "error" in stats:
        storage_service.delete_file(attachment.filename)
        await db.delete(attachment)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process document: {stats['error']}",
        )

    # Phase 2 (async): graph extraction (disabled via ENABLE_KNOWLEDGE_GRAPH flag)
    if extract_graph and settings.ENABLE_KNOWLEDGE_GRAPH:
        background_tasks.add_task(extract_graph_background, attachment.id)

    return {
        "id": attachment.id,
        "filename": attachment.original_filename,
        "content_type": attachment.content_type,
        "file_size": attachment.file_size,
        "is_company_doc": is_company_doc,
        "graph_status": attachment.graph_status,
        "processing_status": attachment.processing_status,
        "message": (
            "Document uploaded. Knowledge graph extraction running in background."  # noqa: E501
            if extract_graph
            else "Document uploaded and processed successfully."
        ),
        "stats": {
            "sections_created": stats.get("sections_created", 0),
            "chunks_created": stats.get("chunks_created", 0),
            "processing_time": round(stats.get("processing_time", 0), 2),
        },
    }


@router.post("/upload-batch")
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    is_company_doc: bool = Form(False),
    extract_graph: bool = Form(True),
    folder_id: Optional[int] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload multiple documents at once via the Docling pipeline."""
    # Snapshot user_id immediately — db.expire_all() inside embed_document()
    # expires all ORM objects including `user`, making user.id inaccessible.
    user_id = user.id
    results = []
    graph_ids: list[int] = []

    # ---------------------------------------------------------------
    # Pass 1: validate, save files, create attachment records
    # ---------------------------------------------------------------
    saved: list[dict] = []   # {file, attachment, saved_filename}

    for file in files:
        saved_filename: str | None = None
        att_id: int | None = None
        try:
            content = await file.read()
            if len(content) > settings.MAX_FILE_SIZE:
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": (
                        f"File too large "
                        f"(max {settings.MAX_FILE_SIZE // (1024 * 1024)}MB)"
                    ),
                })
                continue
            await file.seek(0)

            if not _is_allowed(file.content_type or ""):
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": f"Unsupported type: {file.content_type}",
                })
                continue

            file_info = await storage_service.save_file(file)
            saved_filename = file_info["filename"]

            attachment = Attachment(
                filename=file_info["filename"],
                original_filename=file_info["original_filename"],
                content_type=file_info["content_type"],
                file_size=file_info["file_size"],
                file_path=file_info["file_path"],
                user_id=user.id,
                is_company_doc=is_company_doc,
                graph_status=(
                    "pending"
                    if (extract_graph and settings.ENABLE_KNOWLEDGE_GRAPH)
                    else None
                ),
                processing_status="uploaded",
                folder_id=folder_id,
            )
            db.add(attachment)
            await db.commit()
            await db.refresh(attachment)
            saved.append({
                "file": file,
                "attachment": attachment,
                "att_id": attachment.id,  # snapshot PK before any later expiry
                "saved_filename": saved_filename,
            })
        except Exception as exc:
            await db.rollback()
            if saved_filename:
                storage_service.delete_file(saved_filename)
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(exc),
            })

    # ---------------------------------------------------------------
    # Pass 2: parse + embed in sub-batches to keep peak memory low.
    # Models load once per sub-batch; parsed data is freed after each
    # sub-batch finishes before the next one starts.
    # ---------------------------------------------------------------
    _PARSE_BATCH_SIZE = 3

    for batch_start in range(0, len(saved), _PARSE_BATCH_SIZE):
        chunk = saved[batch_start: batch_start + _PARSE_BATCH_SIZE]

        docling = DoclingService()
        batch_items = [
            (item["attachment"].file_path,
             item["attachment"].original_filename or "")
            for item in chunk
        ]
        parsed_chunk = await docling.parse_batch(batch_items)

        for item, parsed in zip(chunk, parsed_chunk):
            attachment = item["attachment"]
            att_id = item["att_id"]  # use snapshotted PK (avoids expired-attr lazy load)
            try:
                rag = RAGService(db)
                stats = await rag.embed_document(
                    attachment_id=att_id,
                    user_id=user_id,
                    is_company_doc=is_company_doc,
                    parsed_document=parsed,
                )

                if "error" in stats:
                    storage_service.delete_file(item["saved_filename"])
                    await db.refresh(attachment)
                    await db.delete(attachment)
                    await db.commit()
                    results.append({
                        "filename": item["file"].filename,
                        "status": "error",
                        "error": stats["error"],
                    })
                else:
                    await db.refresh(attachment)  # reload mutable fields after embed
                    if extract_graph and settings.ENABLE_KNOWLEDGE_GRAPH:
                        graph_ids.append(att_id)
                    results.append({
                        "filename": item["file"].filename,
                        "status": "success",
                        "id": att_id,
                        "file_size": attachment.file_size,
                        "graph_status": attachment.graph_status,
                        "processing_status": attachment.processing_status,
                        "stats": {
                            "sections_created": stats.get(
                                "sections_created", 0
                            ),
                            "chunks_created": stats.get("chunks_created", 0),
                            "processing_time": round(
                                stats.get("processing_time", 0), 2
                            ),
                        },
                    })
            except Exception as exc:
                import traceback as _tb
                print(
                    f"[BATCH ERROR] {item['file'].filename}: {exc}\n"
                    + _tb.format_exc()
                )
                await db.rollback()
                storage_service.delete_file(item["saved_filename"])
                try:
                    r = await db.execute(
                        select(Attachment).where(Attachment.id == att_id)
                    )
                    orphan = r.scalar_one_or_none()
                    if orphan:
                        await db.delete(orphan)
                        await db.commit()
                except Exception:
                    pass
                results.append({
                    "filename": item["file"].filename,
                    "status": "error",
                    "error": str(exc),
                })

    for aid in graph_ids:
        background_tasks.add_task(extract_graph_background, aid)

    succeeded = sum(1 for r in results if r["status"] == "success")
    return {
        "results": results,
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
    }


@router.get("/{attachment_id}/graph-status")
async def get_graph_status(
    attachment_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll graph extraction status for a document."""
    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Document not found")
    if attachment.user_id != user.id and not attachment.is_company_doc:
        raise HTTPException(status_code=403, detail="Access denied")
    return {
        "id": attachment.id,
        "graph_status": attachment.graph_status,
        "processing_status": attachment.processing_status,
    }


@router.get("/{document_id}/chunks")
async def get_document_chunks(
    document_id: int,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all chunks for a document ordered by position."""
    result = await db.execute(
        select(Attachment).where(Attachment.id == document_id)
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Document not found")
    if not attachment.is_company_doc and (
        not user or attachment.user_id != user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    chunks_result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.attachment_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    chunks = chunks_result.scalars().all()

    return {
        "document": {
            "id": attachment.id,
            "filename": attachment.original_filename,
            "sections_count": attachment.sections_count,
        },
        "chunks": [
            {
                "id": c.id,
                "chunk_index": c.chunk_index,
                "chunk_text": c.chunk_text,
                "heading_context": c.heading_context,
                "page_start": c.page_start,
                "page_end": c.page_end,
            }
            for c in chunks
        ],
    }


@router.get("/{document_id}/download")
async def download_document(
    document_id: int,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Download the original document file."""
    result = await db.execute(
        select(Attachment).where(Attachment.id == document_id)
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Document not found")
    if not attachment.is_company_doc and (
        not user or attachment.user_id != user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    file_path = storage_service.get_file_path(attachment.filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=file_path,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{attachment.original_filename}"'
            )
        },
    )


@router.post("/{attachment_id}/extract-graph")
async def re_extract_graph(
    attachment_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-trigger knowledge graph extraction for an embedded document."""
    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Document not found")

    if attachment.is_company_doc:
        if not user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only admins can re-extract company documents",
            )
    elif attachment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if not attachment.is_embedded:
        raise HTTPException(
            status_code=400,
            detail="Document must be embedded before graph extraction",
        )

    attachment.graph_status = "pending"
    await db.commit()
    background_tasks.add_task(extract_graph_background, attachment_id)
    return {"id": attachment.id, "graph_status": "pending"}


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and all associated data (chunks, sections, graph)."""
    result = await db.execute(
        select(Attachment).where(Attachment.id == document_id)
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Document not found")

    is_owner = attachment.user_id == user.id
    if not is_owner and not user.is_admin:
        raise HTTPException(
            status_code=403, detail="You can only delete your own documents"
        )

    rag = RAGService(db)
    chunks_deleted = await rag.delete_document_chunks(document_id)

    kg = KnowledgeGraphService(db)
    graph_result = await kg.delete_document_graph(document_id)

    storage_service.delete_file(attachment.filename)
    await db.delete(attachment)
    await db.commit()

    return {
        "message": "Document deleted successfully",
        "chunks_deleted": chunks_deleted,
        "graph_links_deleted": graph_result["deleted_links"],
        "graph_relationships_deleted": graph_result["deleted_relationships"],
    }


class MoveFolderBody(BaseModel):
    folder_id: Optional[int] = None


@router.patch("/{document_id}/folder")
async def move_document_folder(
    document_id: int,
    body: MoveFolderBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign or remove a folder for a document."""
    result = await db.execute(
        select(Attachment).where(Attachment.id == document_id)
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Document not found")
    if attachment.user_id != user.id and not attachment.is_company_doc:
        raise HTTPException(status_code=403, detail="Access denied")

    if body.folder_id is not None:
        folder_result = await db.execute(
            select(DocumentFolder).where(DocumentFolder.id == body.folder_id)
        )
        if not folder_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Folder not found")

    attachment.folder_id = body.folder_id
    await db.commit()
    return {"id": attachment.id, "folder_id": attachment.folder_id}


@router.get("/search")
async def search_documents(
    query: str,
    top_k: int = 5,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Search documents using the section-first hybrid pipeline."""
    if not query or len(query) < 3:
        raise HTTPException(
            status_code=400,
            detail="Query must be at least 3 characters",
        )

    rag = RAGService(db)
    results = await rag.search(
        query=query,
        user_id=user.id if user else None,
        top_k=min(top_k, 20),
    )
    return {"query": query, "results": results, "count": len(results)}
