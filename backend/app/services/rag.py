"""
RAG (Retrieval Augmented Generation) service.
Handles document chunking, embedding, storage, and semantic search.
"""

import time
import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_, and_

from app.config import settings
from app.models.document_chunk import DocumentChunk
from app.models.attachment import Attachment
from app.services.embedding import EmbeddingService
from app.services.document import DocumentService


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [RAG] {message}")


class RAGService:
    """Service for RAG operations: chunk, embed, search."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_service = EmbeddingService()
        self.document_service = DocumentService()
        self.chunk_size = settings.RAG_CHUNK_SIZE
        self.chunk_overlap = settings.RAG_CHUNK_OVERLAP
        self.top_k = settings.RAG_TOP_K

    def _chunk_text(self, text: str) -> list[str]:
        """
        Split text into overlapping chunks.

        Args:
            text: Full document text

        Returns:
            List of text chunks
        """
        # Clean the text
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) <= self.chunk_size:
            return [text] if text else []

        chunks = []
        start = 0

        while start < len(text):
            end = start + self.chunk_size

            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence end within the last 20% of chunk
                search_start = end - int(self.chunk_size * 0.2)
                search_text = text[search_start:end]

                # Find last sentence boundary
                for sep in ['. ', '? ', '! ', '\n']:
                    last_sep = search_text.rfind(sep)
                    if last_sep != -1:
                        end = search_start + last_sep + len(sep)
                        break

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Move start with overlap
            start = end - self.chunk_overlap
            if start >= len(text):
                break

        return chunks

    async def embed_document(
        self,
        attachment_id: int,
        user_id: Optional[int] = None,
        is_company_doc: bool = False,
    ) -> bool:
        """
        Extract, chunk, embed, and store a document.

        Args:
            attachment_id: ID of the attachment to embed
            user_id: Owner user ID (None for company docs)
            is_company_doc: Whether this is a company-wide document

        Returns:
            True if successful, False otherwise
        """
        log("=" * 50)
        log("EMBEDDING DOCUMENT")
        log("=" * 50)

        # Get attachment
        result = await self.db.execute(
            select(Attachment).where(Attachment.id == attachment_id)
        )
        attachment = result.scalar_one_or_none()

        if not attachment:
            log(f"✗ Attachment {attachment_id} not found")
            return False

        log(f"Document: {attachment.original_filename}")
        log(f"Type: {attachment.content_type}")
        log(f"Company doc: {is_company_doc}")

        # Extract text
        log("Extracting text...")
        text = await self.document_service.extract_text(attachment.file_path)

        if not text:
            log("✗ Failed to extract text")
            return False

        log(f"✓ Extracted {len(text)} characters")

        # Chunk text
        log("Chunking text...")
        chunks = self._chunk_text(text)
        log(f"✓ Created {len(chunks)} chunks")

        if not chunks:
            log("✗ No chunks created")
            return False

        # Generate embeddings
        log("Generating embeddings...")
        embeddings = await self.embedding_service.embed_texts(chunks)

        # Filter out failed embeddings
        valid_chunks = [
            (i, chunk, emb)
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
            if emb is not None
        ]

        if not valid_chunks:
            log("✗ No valid embeddings generated")
            return False

        log(f"✓ Generated {len(valid_chunks)} valid embeddings")

        # Delete existing chunks for this attachment
        await self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.attachment_id == attachment_id)
        )

        # Store chunks
        log("Storing chunks in database...")
        for chunk_index, chunk_text, embedding in valid_chunks:
            chunk = DocumentChunk(
                attachment_id=attachment_id,
                user_id=user_id if not is_company_doc else None,
                is_company_doc=is_company_doc,
                chunk_index=chunk_index,
                chunk_text=chunk_text,
                embedding=embedding,
            )
            self.db.add(chunk)

        # Update attachment
        attachment.is_embedded = True
        attachment.user_id = user_id
        attachment.is_company_doc = is_company_doc

        await self.db.commit()

        log(f"✓ Stored {len(valid_chunks)} chunks")
        log("=" * 50)

        return True

    async def search(
        self,
        query: str,
        user_id: Optional[int] = None,
        top_k: Optional[int] = None,
    ) -> list[dict]:
        """
        Search for relevant document chunks.

        Args:
            query: Search query
            user_id: Current user ID (for access control)
            top_k: Number of results to return

        Returns:
            List of relevant chunks with metadata
        """
        top_k = top_k or self.top_k

        log("-" * 50)
        log("RAG SEARCH")
        log("-" * 50)
        log(f"Query: {query[:80]}{'...' if len(query) > 80 else ''}")
        log(f"User ID: {user_id}")
        log(f"Top K: {top_k}")

        # Generate query embedding
        start_time = time.time()
        query_embedding = await self.embedding_service.embed_text(query)

        if not query_embedding:
            log("✗ Failed to embed query")
            return []

        embed_time = time.time() - start_time
        log(f"✓ Query embedded in {embed_time:.2f}s")

        # Build access control filter
        # User can access: their own docs + company docs
        if user_id:
            access_filter = or_(
                DocumentChunk.is_company_doc == True,  # noqa: E712
                DocumentChunk.user_id == user_id,
            )
        else:
            # Anonymous users can only access company docs
            access_filter = DocumentChunk.is_company_doc == True  # noqa: E712

        # Search using cosine distance
        search_start = time.time()
        result = await self.db.execute(
            select(
                DocumentChunk,
                DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
            )
            .where(access_filter)
            .order_by("distance")
            .limit(top_k)
        )

        rows = result.all()
        search_time = time.time() - search_start
        log(f"✓ Found {len(rows)} chunks in {search_time:.2f}s")

        # Format results
        results = []
        for chunk, distance in rows:
            # Get attachment info
            att_result = await self.db.execute(
                select(Attachment).where(Attachment.id == chunk.attachment_id)
            )
            attachment = att_result.scalar_one_or_none()

            similarity = 1 - distance  # Convert distance to similarity

            results.append({
                "chunk_id": chunk.id,
                "chunk_text": chunk.chunk_text,
                "chunk_index": chunk.chunk_index,
                "similarity": similarity,
                "attachment_id": chunk.attachment_id,
                "filename": attachment.original_filename if attachment else "Unknown",
                "is_company_doc": chunk.is_company_doc,
            })

            log(f"  [{similarity:.2%}] {attachment.original_filename if attachment else 'Unknown'} (chunk {chunk.chunk_index})")

        log("-" * 50)

        return results

    async def delete_document_chunks(self, attachment_id: int) -> int:
        """
        Delete all chunks for a document.

        Args:
            attachment_id: ID of the attachment

        Returns:
            Number of chunks deleted
        """
        result = await self.db.execute(
            delete(DocumentChunk)
            .where(DocumentChunk.attachment_id == attachment_id)
            .returning(DocumentChunk.id)
        )
        deleted_ids = result.scalars().all()
        await self.db.commit()

        log(f"Deleted {len(deleted_ids)} chunks for attachment {attachment_id}")
        return len(deleted_ids)

    async def get_user_documents(self, user_id: int) -> list[dict]:
        """Get all documents owned by a user."""
        result = await self.db.execute(
            select(Attachment)
            .where(
                and_(
                    Attachment.user_id == user_id,
                    Attachment.is_embedded == True,  # noqa: E712
                )
            )
            .order_by(Attachment.created_at.desc())
        )
        attachments = result.scalars().all()

        return [
            {
                "id": att.id,
                "filename": att.original_filename,
                "content_type": att.content_type,
                "file_size": att.file_size,
                "is_company_doc": att.is_company_doc,
                "created_at": att.created_at.isoformat(),
            }
            for att in attachments
        ]

    async def get_company_documents(self) -> list[dict]:
        """Get all company documents."""
        result = await self.db.execute(
            select(Attachment)
            .where(
                and_(
                    Attachment.is_company_doc == True,  # noqa: E712
                    Attachment.is_embedded == True,  # noqa: E712
                )
            )
            .order_by(Attachment.created_at.desc())
        )
        attachments = result.scalars().all()

        return [
            {
                "id": att.id,
                "filename": att.original_filename,
                "content_type": att.content_type,
                "file_size": att.file_size,
                "created_at": att.created_at.isoformat(),
            }
            for att in attachments
        ]
