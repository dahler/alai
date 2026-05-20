"""
Documents API router for RAG document management.
Handles personal and company document uploads, listing, and deletion.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import Optional

from app.database import get_db
from app.middleware.auth import get_current_user, get_optional_user
from app.models.user import User
from app.models.attachment import Attachment
from app.models.document_chunk import DocumentChunk
from app.services.rag import RAGService
from app.services.knowledge_graph import KnowledgeGraphService, extract_graph_background
from app.services.storage import StorageService
from app.config import settings

router = APIRouter(prefix="/documents", tags=["documents"])
storage_service = StorageService()


@router.get("")
async def list_documents(
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all documents accessible by the current user.
    Returns personal documents + company documents.
    """
    rag_service = RAGService(db)

    # Get company documents (accessible by all)
    company_docs = await rag_service.get_company_documents()

    # Get personal documents if logged in
    personal_docs = []
    if user:
        personal_docs = await rag_service.get_user_documents(user.id)

    return {
        "personal_documents": personal_docs,
        "company_documents": company_docs,
    }


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    is_company_doc: bool = Form(False),
    extract_graph: bool = Form(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload and embed a document for RAG.
    Chunking and embedding run synchronously; graph extraction runs in the background.
    """
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE // (1024*1024)}MB",
        )
    await file.seek(0)

    allowed_types = {
        "application/pdf", "text/plain", "text/markdown",
        "application/json", "text/html", "text/xml",
    }
    if file.content_type not in allowed_types and not file.content_type.startswith("text/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type {file.content_type} is not supported for RAG.",
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
        graph_status="pending" if extract_graph else None,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    # Phase 1 (sync): extract text, chunk, embed, store chunks
    kg_service = KnowledgeGraphService(db)
    stats = await kg_service.ingest_document(
        attachment_id=attachment.id,
        user_id=user.id,
        is_company_doc=is_company_doc,
        extract_graph=False,
    )

    if "error" in stats:
        storage_service.delete_file(attachment.filename)
        await db.delete(attachment)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process document: {stats['error']}",
        )

    # Phase 2 (async): entity + graph extraction in background
    if extract_graph:
        background_tasks.add_task(extract_graph_background, attachment.id)

    return {
        "id": attachment.id,
        "filename": attachment.original_filename,
        "content_type": attachment.content_type,
        "file_size": attachment.file_size,
        "is_company_doc": is_company_doc,
        "graph_status": attachment.graph_status,
        "message": "Document uploaded. Knowledge graph extraction running in background."
        if extract_graph else "Document uploaded and processed successfully.",
        "stats": {
            "chunks_created": stats["chunks_created"],
            "processing_time": round(stats["processing_time"], 2),
        },
    }


@router.post("/upload-batch")
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    is_company_doc: bool = Form(False),
    extract_graph: bool = Form(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload multiple documents at once.
    Chunking/embedding runs synchronously per file; graph extraction is deferred to background.
    """
    allowed_types = {
        "application/pdf", "text/plain", "text/markdown",
        "application/json", "text/html", "text/xml",
    }

    results = []
    graph_attachment_ids: list[int] = []

    for file in files:
        saved_filename: str | None = None
        committed_attachment_id: int | None = None
        try:
            content = await file.read()
            if len(content) > settings.MAX_FILE_SIZE:
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": f"File too large (max {settings.MAX_FILE_SIZE // (1024 * 1024)}MB)",
                })
                continue
            await file.seek(0)

            if file.content_type not in allowed_types and not (file.content_type or "").startswith("text/"):
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": f"Unsupported file type: {file.content_type}",
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
                graph_status="pending" if extract_graph else None,
            )
            db.add(attachment)
            await db.commit()
            await db.refresh(attachment)
            committed_attachment_id = attachment.id

            # Phase 1 (sync): chunks + embeddings only
            kg_service = KnowledgeGraphService(db)
            stats = await kg_service.ingest_document(
                attachment_id=attachment.id,
                user_id=user.id,
                is_company_doc=is_company_doc,
                extract_graph=False,
            )

            if "error" in stats:
                storage_service.delete_file(saved_filename)
                await db.delete(attachment)
                await db.commit()
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": stats["error"],
                })
            else:
                if extract_graph:
                    graph_attachment_ids.append(attachment.id)
                results.append({
                    "filename": file.filename,
                    "status": "success",
                    "id": attachment.id,
                    "file_size": attachment.file_size,
                    "graph_status": attachment.graph_status,
                    "stats": {
                        "chunks_created": stats["chunks_created"],
                        "processing_time": round(stats["processing_time"], 2),
                    },
                })
        except Exception as e:
            await db.rollback()

            if saved_filename:
                storage_service.delete_file(saved_filename)

            if committed_attachment_id:
                try:
                    result = await db.execute(
                        select(Attachment).where(Attachment.id == committed_attachment_id)
                    )
                    orphan = result.scalar_one_or_none()
                    if orphan:
                        await db.delete(orphan)
                        await db.commit()
                except Exception:
                    pass

            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e),
            })

    # Schedule background graph extraction for all successful uploads
    for att_id in graph_attachment_ids:
        background_tasks.add_task(extract_graph_background, att_id)

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
    """Poll the graph extraction status for a document."""
    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if attachment.user_id != user.id and not attachment.is_company_doc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return {"id": attachment.id, "graph_status": attachment.graph_status}


@router.post("/{attachment_id}/extract-graph")
async def re_extract_graph(
    attachment_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-trigger knowledge graph extraction for an already-embedded document."""
    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if attachment.is_company_doc:
        if not user.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can re-extract company documents")
    else:
        if attachment.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if not attachment.is_embedded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
    """
    Delete a document and its embeddings.
    Users can delete their own documents.
    Admins can delete company documents.
    """
    # Get attachment
    result = await db.execute(
        select(Attachment).where(Attachment.id == document_id)
    )
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Check permissions
    if attachment.is_company_doc:
        if not user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can delete company documents",
            )
    else:
        if attachment.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own documents",
            )

    # Delete chunks
    rag_service = RAGService(db)
    chunks_deleted = await rag_service.delete_document_chunks(document_id)

    # Delete graph data
    kg_service = KnowledgeGraphService(db)
    graph_result = await kg_service.delete_document_graph(document_id)

    # Delete file from storage
    storage_service.delete_file(attachment.filename)

    # Delete attachment record
    await db.delete(attachment)
    await db.commit()

    return {
        "message": "Document deleted successfully",
        "chunks_deleted": chunks_deleted,
        "graph_links_deleted": graph_result["deleted_links"],
        "graph_relationships_deleted": graph_result["deleted_relationships"],
    }


@router.get("/search")
async def search_documents(
    query: str,
    top_k: int = 5,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Search documents using semantic search.
    Returns relevant chunks based on the query.
    """
    if not query or len(query) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query must be at least 3 characters",
        )

    rag_service = RAGService(db)
    results = await rag_service.search(
        query=query,
        user_id=user.id if user else None,
        top_k=min(top_k, 20),  # Limit max results
    )

    return {
        "query": query,
        "results": results,
        "count": len(results),
    }


@router.post("/{attachment_id}/embed")
async def embed_existing_document(
    attachment_id: int,
    is_company_doc: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Embed an existing attachment for RAG.
    Useful for embedding documents that were uploaded before RAG was enabled.
    """
    # Get attachment
    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    # Check permissions
    if is_company_doc and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create company documents",
        )

    # Check if document type is supported
    if not attachment.is_document:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {attachment.content_type} is not supported for RAG",
        )

    # Embed document
    rag_service = RAGService(db)
    success = await rag_service.embed_document(
        attachment_id=attachment.id,
        user_id=user.id,
        is_company_doc=is_company_doc,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to embed document",
        )

    return {
        "message": "Document embedded successfully",
        "attachment_id": attachment_id,
        "is_company_doc": is_company_doc,
    }
