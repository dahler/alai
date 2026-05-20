"""
Knowledge Graph Service - Main Orchestrator.
Coordinates document ingestion, entity/relationship extraction, and graph construction.
"""

import re
import time
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from app.models.entity import Entity
from app.models.relationship import EntityRelationship
from app.models.document_entity import DocumentEntity
from app.models.document_chunk import DocumentChunk
from app.models.attachment import Attachment
from app.services.entity_extraction import EntityExtractionService
from app.services.relationship_extraction import RelationshipExtractionService
from app.services.graph_linking import GraphLinkingService
from app.services.graph_retrieval import GraphRetrievalService, RetrievalResult
from app.services.embedding import EmbeddingService
from app.services.document import DocumentService
from app.config import settings


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [KNOWLEDGE_GRAPH] {message}")


class KnowledgeGraphService:
    """
    Main orchestrator for Knowledge Graph operations.

    Handles:
    - Document ingestion with graph construction
    - Hybrid retrieval (vector + graph)
    - Graph statistics and management
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.entity_extraction = EntityExtractionService()
        self.relationship_extraction = RelationshipExtractionService()
        self.graph_linking = GraphLinkingService(db)
        self.graph_retrieval = GraphRetrievalService(db)
        self.embedding_service = EmbeddingService()
        self.document_service = DocumentService()
        self.chunk_size = settings.RAG_CHUNK_SIZE
        self.chunk_overlap = settings.RAG_CHUNK_OVERLAP

    async def ingest_document(
        self,
        attachment_id: int,
        user_id: Optional[int] = None,
        is_company_doc: bool = False,
        extract_graph: bool = True,
    ) -> dict:
        """
        Ingest a document into both vector store and knowledge graph.

        Pipeline:
        1. Extract text from document
        2. Chunk text
        3. Generate embeddings and store chunks
        4. Extract entities from chunks
        5. Extract relationships between entities
        6. Link entities to existing graph
        7. Create document-entity associations

        Args:
            attachment_id: Document attachment ID
            user_id: Owner user ID
            is_company_doc: Whether company-wide accessible
            extract_graph: Whether to extract knowledge graph (can be disabled for speed)

        Returns:
            Dictionary with ingestion statistics
        """
        log("=" * 60)
        log("DOCUMENT INGESTION - KNOWLEDGE GRAPH + RAG")
        log("=" * 60)

        start_time = time.time()
        stats = {
            "attachment_id": attachment_id,
            "chunks_created": 0,
            "entities_extracted": 0,
            "entities_new": 0,
            "entities_linked": 0,
            "relationships_extracted": 0,
            "relationships_created": 0,
            "processing_time": 0,
        }

        # Get attachment
        result = await self.db.execute(
            select(Attachment).where(Attachment.id == attachment_id)
        )
        attachment = result.scalar_one_or_none()

        if not attachment:
            log(f"✗ Attachment {attachment_id} not found")
            return {"error": "Attachment not found", **stats}

        log(f"Document: {attachment.original_filename}")
        log(f"Type: {attachment.content_type}")
        log(f"Company doc: {is_company_doc}")
        log(f"Extract graph: {extract_graph}")

        # Step 1: Extract text
        log("-" * 40)
        log("Step 1: Extracting text...")
        text = await self.document_service.extract_text(attachment.file_path)

        if not text:
            log("✗ Failed to extract text")
            return {"error": "Failed to extract text", **stats}

        log(f"✓ Extracted {len(text)} characters")

        # Step 2: Chunk text
        log("-" * 40)
        log("Step 2: Chunking text...")
        chunks = self._chunk_text(text)
        log(f"✓ Created {len(chunks)} chunks")

        if not chunks:
            return {"error": "No chunks created", **stats}

        # Step 3: Generate embeddings
        log("-" * 40)
        log("Step 3: Generating embeddings...")
        embeddings = await self.embedding_service.embed_texts(chunks)

        valid_chunks = [
            (i, chunk, emb)
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
            if emb is not None
        ]

        if not valid_chunks:
            return {"error": "No valid embeddings generated", **stats}

        log(f"✓ Generated {len(valid_chunks)} embeddings")

        # Step 4: Delete existing chunks and store new ones
        await self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.attachment_id == attachment_id)
        )

        log("-" * 40)
        log("Step 4: Storing chunks in database...")

        chunk_records = []
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
            chunk_records.append(chunk)

        await self.db.flush()  # Get chunk IDs
        stats["chunks_created"] = len(chunk_records)
        log(f"✓ Stored {len(chunk_records)} chunks")

        # Step 5-7: Extract graph (if enabled)
        if extract_graph:
            await self._extract_and_link_graph(
                attachment_id, chunks, chunk_records, stats
            )

        # Update attachment
        attachment.is_embedded = True
        attachment.user_id = user_id
        attachment.is_company_doc = is_company_doc

        await self.db.commit()

        stats["processing_time"] = time.time() - start_time
        log("=" * 60)
        log(f"INGESTION COMPLETE in {stats['processing_time']:.2f}s")
        log(f"  Chunks: {stats['chunks_created']}")
        log(f"  Entities: {stats['entities_extracted']} extracted, {stats['entities_new']} new, {stats['entities_linked']} linked")
        log(f"  Relationships: {stats['relationships_extracted']} extracted, {stats['relationships_created']} created")
        log("=" * 60)

        return stats

    def _extract_regulation_title(self, chunks: list[str]) -> Optional[str]:
        """
        Derive a short regulation title from the first few chunks.

        Tries common Indonesian regulation header patterns (UU, PP, Perpres,
        Permen, POJK) and falls back to None so callers can use the filename.
        """
        search_text = " ".join(chunks[:3])[:3000]

        patterns = [
            (
                r"UNDANG[\s-]+UNDANG\s+(?:REPUBLIK\s+INDONESIA\s+)?"
                r"NOMOR\s+(\d+)\s+TAHUN\s+(\d{4})",
                "UU No. {}/{}",
            ),
            (
                r"PERATURAN\s+PEMERINTAH\s+(?:REPUBLIK\s+INDONESIA\s+)?"
                r"NOMOR\s+(\d+)\s+TAHUN\s+(\d{4})",
                "PP No. {}/{}",
            ),
            (
                r"PERATURAN\s+PRESIDEN\s+(?:REPUBLIK\s+INDONESIA\s+)?"
                r"NOMOR\s+(\d+)\s+TAHUN\s+(\d{4})",
                "Perpres No. {}/{}",
            ),
            (
                r"PERATURAN\s+OTORITAS\s+JASA\s+KEUANGAN\s+"
                r"NOMOR\s+(\d+)(?:/\w+)*\s+(?:TAHUN\s+)?(\d{4})",
                "POJK No. {}/{}",
            ),
            (
                r"PERATURAN\s+MENTERI\s+(?:\w+\s+){0,5}"
                r"NOMOR\s+(\d+)(?:/\w+)*\s+TAHUN\s+(\d{4})",
                "Permen No. {}/{}",
            ),
            (r"\bUU\s+No\.?\s*(\d+)[/\s]+Tahun\s+(\d{4})", "UU No. {}/{}"),
            (r"\bPP\s+No\.?\s*(\d+)[/\s]+Tahun\s+(\d{4})", "PP No. {}/{}"),
            (r"\bUU\s+No\.?\s*(\d+)/(\d{4})\b", "UU No. {}/{}"),
            (r"\bPP\s+No\.?\s*(\d+)/(\d{4})\b", "PP No. {}/{}"),
        ]

        for pattern, template in patterns:
            match = re.search(pattern, search_text, re.IGNORECASE)
            if match:
                num = match.group(1).split("/")[0]
                year = match.group(2)
                return template.format(num, year)

        return None

    async def _extract_and_link_graph(
        self,
        attachment_id: int,
        chunks: list[str],
        chunk_records: list[DocumentChunk],
        stats: dict,
    ):
        """Extract entities and relationships, link to graph."""

        # Derive regulation title so pasal entities are named correctly
        doc_title = self._extract_regulation_title(chunks)
        if doc_title:
            log(f"Detected regulation title: {doc_title}")

        # Step 5: Extract entities
        log("-" * 40)
        log("Step 5: Extracting entities...")

        all_entities = []
        chunk_entities_map = {}  # chunk_index -> entities

        for i, chunk_text in enumerate(chunks):
            entities = await self.entity_extraction.extract_entities(
                chunk_text,
                max_entities=15,
                document_title=doc_title,
            )
            all_entities.extend(entities)
            chunk_entities_map[i] = entities

        stats["entities_extracted"] = len(all_entities)
        log(f"✓ Extracted {len(all_entities)} entities across all chunks")

        # Step 6: Link entities to graph
        log("-" * 40)
        log("Step 6: Linking entities to graph...")

        entity_map = {}  # name -> Entity
        new_count = 0
        linked_count = 0

        for chunk_index, entities in chunk_entities_map.items():
            chunk_record = chunk_records[chunk_index] if chunk_index < len(chunk_records) else None
            chunk_id = chunk_record.id if chunk_record else None

            for extracted in entities:
                # Check if we've already processed this entity
                key = extracted.normalize_name()
                if key in entity_map:
                    linked_count += 1
                    continue

                entity = await self.graph_linking.find_or_create_entity(
                    extracted, attachment_id, chunk_id
                )
                entity_map[key] = entity
                entity_map[extracted.name.lower()] = entity

                if entity.mention_count == 1:
                    new_count += 1
                else:
                    linked_count += 1

        stats["entities_new"] = new_count
        stats["entities_linked"] = linked_count
        log(f"✓ New entities: {new_count}, Linked to existing: {linked_count}")

        # Step 7: Extract and link relationships
        log("-" * 40)
        log("Step 7: Extracting relationships...")

        total_rels_extracted = 0
        total_rels_created = 0

        for chunk_index, entities in chunk_entities_map.items():
            if len(entities) < 2:
                continue

            chunk_record = chunk_records[chunk_index] if chunk_index < len(chunk_records) else None
            chunk_id = chunk_record.id if chunk_record else None
            chunk_text = chunks[chunk_index]

            relationships = await self.relationship_extraction.extract_relationships(
                chunk_text, entities, max_relationships=10
            )
            total_rels_extracted += len(relationships)

            # Link relationships
            created = await self.graph_linking.link_relationships_batch(
                relationships, entity_map, attachment_id, chunk_id
            )
            total_rels_created += len(created)

        stats["relationships_extracted"] = total_rels_extracted
        stats["relationships_created"] = total_rels_created
        log(f"✓ Relationships: {total_rels_extracted} extracted, {total_rels_created} created")

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks."""
        import re

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
                search_start = end - int(self.chunk_size * 0.2)
                search_text = text[search_start:end]

                for sep in ['. ', '? ', '! ', '\n']:
                    last_sep = search_text.rfind(sep)
                    if last_sep != -1:
                        end = search_start + last_sep + len(sep)
                        break

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - self.chunk_overlap
            if start >= len(text):
                break

        return chunks

    async def hybrid_search(
        self,
        query: str,
        user_id: Optional[int] = None,
        top_k: int = 5,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
    ) -> list[RetrievalResult]:
        """
        Perform hybrid search combining vector and graph.

        Args:
            query: Search query
            user_id: User ID for access control
            top_k: Number of results
            vector_weight: Weight for vector similarity
            graph_weight: Weight for graph relevance

        Returns:
            List of RetrievalResult objects
        """
        return await self.graph_retrieval.hybrid_search(
            query, user_id, top_k, vector_weight, graph_weight
        )

    async def get_graph_stats(self) -> dict:
        """Get knowledge graph statistics."""
        # Count entities by type
        entity_result = await self.db.execute(
            select(Entity.entity_type, func.count(Entity.id))
            .group_by(Entity.entity_type)
        )
        entities_by_type = {row[0]: row[1] for row in entity_result.all()}

        # Count relationships by type
        rel_result = await self.db.execute(
            select(EntityRelationship.relation_type, func.count(EntityRelationship.id))
            .group_by(EntityRelationship.relation_type)
        )
        relationships_by_type = {row[0]: row[1] for row in rel_result.all()}

        # Total counts
        total_entities = sum(entities_by_type.values())
        total_relationships = sum(relationships_by_type.values())

        # Document count with graph data
        doc_result = await self.db.execute(
            select(func.count(func.distinct(DocumentEntity.document_id)))
        )
        documents_with_graph = doc_result.scalar() or 0

        return {
            "total_entities": total_entities,
            "total_relationships": total_relationships,
            "documents_with_graph": documents_with_graph,
            "entities_by_type": entities_by_type,
            "relationships_by_type": relationships_by_type,
        }

    async def get_entity_details(self, entity_id: int) -> Optional[dict]:
        """Get detailed information about an entity."""
        # Get entity
        result = await self.db.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        entity = result.scalar_one_or_none()

        if not entity:
            return None

        # Get outgoing relationships + chunk evidence
        out_result = await self.db.execute(
            select(EntityRelationship, Entity, DocumentChunk)
            .join(Entity, EntityRelationship.target_entity_id == Entity.id)
            .outerjoin(
                DocumentChunk,
                EntityRelationship.source_chunk_id == DocumentChunk.id,
            )
            .where(EntityRelationship.source_entity_id == entity_id)
        )
        outgoing = [
            {
                "id": rel.id,
                "relation": rel.relation_type,
                "target_id": target.id,
                "target_name": target.name,
                "target_type": target.entity_type,
                "confidence": rel.confidence,
                "context": rel.context,
                "chunk_text": (
                    chunk.chunk_text[:400] if chunk else None
                ),
            }
            for rel, target, chunk in out_result.all()
        ]

        # Get incoming relationships + chunk evidence
        in_result = await self.db.execute(
            select(EntityRelationship, Entity, DocumentChunk)
            .join(Entity, EntityRelationship.source_entity_id == Entity.id)
            .outerjoin(
                DocumentChunk,
                EntityRelationship.source_chunk_id == DocumentChunk.id,
            )
            .where(EntityRelationship.target_entity_id == entity_id)
        )
        incoming = [
            {
                "id": rel.id,
                "source_id": source.id,
                "source_name": source.name,
                "source_type": source.entity_type,
                "relation": rel.relation_type,
                "confidence": rel.confidence,
                "context": rel.context,
                "chunk_text": (
                    chunk.chunk_text[:400] if chunk else None
                ),
            }
            for rel, source, chunk in in_result.all()
        ]

        # Get documents
        doc_result = await self.db.execute(
            select(DocumentEntity, Attachment)
            .join(Attachment, DocumentEntity.document_id == Attachment.id)
            .where(DocumentEntity.entity_id == entity_id)
        )
        documents = [
            {
                "document_id": de.document_id,
                "filename": att.original_filename,
                "mention_count": de.mention_count,
            }
            for de, att in doc_result.all()
        ]

        return {
            "id": entity.id,
            "name": entity.name,
            "type": entity.entity_type,
            "normalized_name": entity.normalized_name,
            "aliases": entity.aliases,
            "mention_count": entity.mention_count,
            "created_at": entity.created_at.isoformat(),
            "outgoing_relationships": outgoing,
            "incoming_relationships": incoming,
            "documents": documents,
        }

    async def search_entities(
        self,
        query: str,
        entity_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search for entities by name or type."""
        conditions = [Entity.name.ilike(f"%{query}%")]

        if entity_type:
            conditions.append(Entity.entity_type == entity_type)

        result = await self.db.execute(
            select(Entity)
            .where(*conditions)
            .order_by(Entity.mention_count.desc())
            .limit(limit)
        )

        return [
            {
                "id": e.id,
                "name": e.name,
                "type": e.entity_type,
                "mention_count": e.mention_count,
            }
            for e in result.scalars().all()
        ]

    async def get_document_graph(self, document_id: int) -> dict:
        """Get graph data for a specific document."""
        # Get entities in document
        entity_result = await self.db.execute(
            select(Entity, DocumentEntity)
            .join(DocumentEntity, Entity.id == DocumentEntity.entity_id)
            .where(DocumentEntity.document_id == document_id)
        )

        entities = []
        entity_ids = set()
        for entity, doc_entity in entity_result.all():
            entities.append({
                "id": entity.id,
                "name": entity.name,
                "type": entity.entity_type,
                "mention_count": doc_entity.mention_count,
            })
            entity_ids.add(entity.id)

        # Get relationships between these entities
        if entity_ids:
            rel_result = await self.db.execute(
                select(EntityRelationship)
                .where(
                    EntityRelationship.source_entity_id.in_(entity_ids),
                    EntityRelationship.target_entity_id.in_(entity_ids),
                )
            )

            relationships = [
                {
                    "id": rel.id,
                    "source_id": rel.source_entity_id,
                    "relation": rel.relation_type,
                    "target_id": rel.target_entity_id,
                    "confidence": rel.confidence,
                }
                for rel in rel_result.scalars().all()
            ]
        else:
            relationships = []

        # Get related documents
        linking_service = GraphLinkingService(self.db)
        related_docs = await linking_service.find_related_documents(
            document_id, min_shared_entities=2
        )

        return {
            "document_id": document_id,
            "entities": entities,
            "relationships": relationships,
            "related_documents": related_docs,
        }

    async def run_graph_extraction(self, attachment_id: int) -> dict:
        """Run graph extraction on an already-embedded document's chunks."""
        result = await self.db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.attachment_id == attachment_id)
            .order_by(DocumentChunk.chunk_index)
        )
        chunk_records = list(result.scalars().all())
        chunks = [c.chunk_text for c in chunk_records]
        stats: dict = {
            "entities_extracted": 0, "entities_new": 0,
            "entities_linked": 0, "relationships_extracted": 0,
            "relationships_created": 0,
        }
        if chunks:
            await self._extract_and_link_graph(attachment_id, chunks, chunk_records, stats)
        return stats

    async def delete_document_graph(self, document_id: int) -> dict:
        """Delete graph data for a document."""
        # Delete document-entity links
        result = await self.db.execute(
            delete(DocumentEntity)
            .where(DocumentEntity.document_id == document_id)
            .returning(DocumentEntity.id)
        )
        deleted_links = len(result.scalars().all())

        # Delete relationships sourced from this document
        result = await self.db.execute(
            delete(EntityRelationship)
            .where(EntityRelationship.source_document_id == document_id)
            .returning(EntityRelationship.id)
        )
        deleted_rels = len(result.scalars().all())

        await self.db.commit()

        return {
            "document_id": document_id,
            "deleted_links": deleted_links,
            "deleted_relationships": deleted_rels,
        }


async def extract_graph_background(attachment_id: int) -> None:
    """
    Standalone background task: extract entities and build graph for an already-embedded document.
    Creates its own DB session so it can run after the request is done.
    """
    from app.database import async_session_maker

    log(f"Background graph extraction starting for attachment {attachment_id}")

    async with async_session_maker() as db:
        try:
            result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
            attachment = result.scalar_one_or_none()
            if not attachment:
                log(f"Attachment {attachment_id} not found in background task")
                return

            attachment.graph_status = 'processing'
            await db.commit()

            service = KnowledgeGraphService(db)
            stats = await service.run_graph_extraction(attachment_id)

            attachment.graph_status = 'done' if stats.get('entities_extracted', 0) >= 0 else 'skipped'
            await db.commit()

            log(f"Background graph extraction DONE for attachment {attachment_id}: "
                f"{stats.get('entities_extracted', 0)} entities, "
                f"{stats.get('relationships_created', 0)} relationships")

        except Exception as exc:
            log(f"Background graph extraction FAILED for attachment {attachment_id}: {exc}")
            try:
                async with async_session_maker() as db2:
                    result = await db2.execute(select(Attachment).where(Attachment.id == attachment_id))
                    att = result.scalar_one_or_none()
                    if att:
                        att.graph_status = 'failed'
                        await db2.commit()
            except Exception:
                pass
