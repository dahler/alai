"""
Graph Retrieval Service for Knowledge Graph + RAG.
Implements hybrid retrieval combining vector similarity with graph traversal.
"""

import time
from typing import Optional
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from app.models.entity import Entity
from app.models.relationship import EntityRelationship
from app.models.document_entity import DocumentEntity
from app.models.document_chunk import DocumentChunk
from app.models.attachment import Attachment
from app.services.embedding import EmbeddingService
from app.services.entity_extraction import EntityExtractionService
from app.config import settings


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [GRAPH_RETRIEVAL] {message}")


@dataclass
class RetrievalResult:
    """Result from hybrid retrieval."""
    chunk_id: int
    chunk_text: str
    document_id: int
    filename: str           # original filename shown to users
    stored_filename: str = ""  # server-side filename used in download URL
    vector_score: float = 0.0
    graph_score: float = 0.0
    combined_score: float = 0.0
    matched_entities: list = field(default_factory=list)
    relationships: list = field(default_factory=list)
    source: str = "vector"  # "vector", "graph", or "hybrid"


class GraphRetrievalService:
    """
    Hybrid retrieval service combining:
    1. Semantic vector search (existing RAG)
    2. Knowledge graph traversal
    3. Multi-hop relationship expansion
    4. Context merging and ranking
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_service = EmbeddingService()
        self.entity_extraction_service = EntityExtractionService()

    async def hybrid_search(
        self,
        query: str,
        user_id: Optional[int] = None,
        top_k: int = 10,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        max_graph_hops: int = 2,
        source_filter: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """
        Perform hybrid search combining vector similarity and graph relationships.

        Args:
            query: Search query
            user_id: User ID for access control
            top_k: Number of results to return
            vector_weight: Weight for vector similarity (0-1)
            graph_weight: Weight for graph relevance (0-1)
            max_graph_hops: Maximum graph traversal depth

        Returns:
            List of ranked RetrievalResult objects
        """
        log("=" * 50)
        log("HYBRID SEARCH")
        log("=" * 50)
        log(f"Query: {query[:80]}{'...' if len(query) > 80 else ''}")
        log(f"Weights: vector={vector_weight}, graph={graph_weight}")

        start_time = time.time()

        # Step 1: Vector search
        log("Step 1: Vector similarity search...")
        vector_results = await self._vector_search(query, user_id, top_k * 2, source_filter=source_filter)
        log(f"  Found {len(vector_results)} vector matches")

        # Step 2: Extract entities from query
        log("Step 2: Extracting query entities...")
        query_entities = await self.entity_extraction_service.extract_entities(
            query, max_entities=10
        )
        log(f"  Extracted {len(query_entities)} entities")

        # Step 3: Find matching entities in graph
        log("Step 3: Finding graph entities...")
        matched_entities = await self._find_matching_entities(query_entities)
        log(f"  Matched {len(matched_entities)} entities in graph")

        # Step 4: Graph traversal to find related chunks
        log("Step 4: Graph traversal...")
        graph_results = await self._graph_search(
            matched_entities, user_id, top_k * 2, max_graph_hops
        )
        log(f"  Found {len(graph_results)} graph matches")

        # Step 5: Merge and rank results
        log("Step 5: Merging and ranking...")
        merged_results = await self._merge_results(
            vector_results, graph_results,
            vector_weight, graph_weight, top_k
        )

        # Step 6: Apply source_filter post-merge (catches any graph results that slipped through)
        if source_filter:
            merged_results = [
                r for r in merged_results
                if source_filter.lower() in (r.filename or "").lower()
            ]
            log(f"After source_filter '{source_filter}': {len(merged_results)} results remain")

        elapsed = time.time() - start_time
        log(f"Hybrid search complete: {len(merged_results)} results in {elapsed:.2f}s")
        log("=" * 50)

        return merged_results

    async def _vector_search(
        self,
        query: str,
        user_id: Optional[int],
        top_k: int,
        source_filter: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """Perform vector similarity search."""
        # Generate query embedding
        query_embedding = await self.embedding_service.embed_text(query)
        if not query_embedding:
            return []

        # Build access control filter
        if user_id:
            access_filter = or_(
                DocumentChunk.is_company_doc == True,
                DocumentChunk.user_id == user_id,
            )
        else:
            access_filter = DocumentChunk.is_company_doc == True

        # Search chunks — JOIN with Attachment so we can filter by filename
        q = (
            select(
                DocumentChunk,
                Attachment.original_filename,
                Attachment.filename,
                DocumentChunk.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .join(Attachment, Attachment.id == DocumentChunk.attachment_id)
            .where(access_filter)
        )
        if source_filter:
            q = q.where(Attachment.original_filename.ilike(f"%{source_filter}%"))
        q = q.order_by("distance").limit(top_k)
        result = await self.db.execute(q)

        results = []
        for chunk, original_filename, stored_filename, distance in result.all():
            attachment = type("_A", (), {
                "original_filename": original_filename,
                "filename": stored_filename,
            })()

            similarity = 1 - distance

            results.append(RetrievalResult(
                chunk_id=chunk.id,
                chunk_text=chunk.chunk_text,
                document_id=chunk.attachment_id,
                filename=attachment.original_filename if attachment else "Unknown",
                stored_filename=attachment.filename if attachment else "",
                vector_score=similarity,
                source="vector",
            ))

        return results

    async def _find_matching_entities(
        self,
        query_entities: list,
    ) -> list[Entity]:
        """Find entities in the graph matching query entities."""
        matched = []

        for extracted in query_entities:
            normalized = extracted.normalize_name()

            # Try exact match
            result = await self.db.execute(
                select(Entity).where(
                    or_(
                        Entity.normalized_name == normalized,
                        Entity.name.ilike(f"%{extracted.name}%"),
                    )
                )
            )
            entities = result.scalars().all()
            matched.extend(entities)

        # Deduplicate
        seen = set()
        unique = []
        for entity in matched:
            if entity.id not in seen:
                seen.add(entity.id)
                unique.append(entity)

        return unique

    async def _graph_search(
        self,
        matched_entities: list[Entity],
        user_id: Optional[int],
        top_k: int,
        max_hops: int,
    ) -> list[RetrievalResult]:
        """
        Search using graph relationships.

        Traverses the knowledge graph to find related chunks.
        """
        if not matched_entities:
            return []

        # Collect all related entity IDs through graph traversal
        related_entity_ids = set()
        entity_relationships = {}  # Track relationships for context

        for entity in matched_entities:
            related_entity_ids.add(entity.id)
            await self._collect_related_entities(
                entity.id, related_entity_ids,
                entity_relationships, max_hops, 0
            )

        if not related_entity_ids:
            return []

        # Build access control filter
        if user_id:
            access_filter = or_(
                DocumentChunk.is_company_doc == True,
                DocumentChunk.user_id == user_id,
            )
        else:
            access_filter = DocumentChunk.is_company_doc == True

        # Find chunks associated with related entities
        result = await self.db.execute(
            select(DocumentChunk, DocumentEntity, Entity)
            .join(DocumentEntity, DocumentEntity.chunk_id == DocumentChunk.id)
            .join(Entity, DocumentEntity.entity_id == Entity.id)
            .where(
                DocumentEntity.entity_id.in_(related_entity_ids),
                access_filter,
            )
            .distinct(DocumentChunk.id)
            .limit(top_k)
        )

        results = []
        seen_chunks = set()

        for chunk, doc_entity, entity in result.all():
            if chunk.id in seen_chunks:
                continue
            seen_chunks.add(chunk.id)

            # Get attachment info
            att_result = await self.db.execute(
                select(Attachment).where(Attachment.id == chunk.attachment_id)
            )
            attachment = att_result.scalar_one_or_none()

            # Calculate graph score based on relationship depth
            graph_score = doc_entity.confidence

            # Get matched entities for this chunk
            matched = await self._get_chunk_entities(chunk.id, related_entity_ids)

            # Get relevant relationships
            rels = []
            for eid in [e["id"] for e in matched]:
                if eid in entity_relationships:
                    rels.extend(entity_relationships[eid])

            results.append(RetrievalResult(
                chunk_id=chunk.id,
                chunk_text=chunk.chunk_text,
                document_id=chunk.attachment_id,
                filename=attachment.original_filename if attachment else "Unknown",
                stored_filename=attachment.filename if attachment else "",
                graph_score=graph_score,
                matched_entities=matched,
                relationships=rels[:5],  # Limit relationships
                source="graph",
            ))

        return results

    async def _collect_related_entities(
        self,
        entity_id: int,
        collected: set,
        relationships: dict,
        max_hops: int,
        current_hop: int,
    ):
        """Recursively collect related entities through graph traversal."""
        if current_hop >= max_hops:
            return

        # Get outgoing relationships
        result = await self.db.execute(
            select(EntityRelationship, Entity)
            .join(Entity, EntityRelationship.target_entity_id == Entity.id)
            .where(EntityRelationship.source_entity_id == entity_id)
        )

        for rel, target in result.all():
            rel_info = {
                "source_id": entity_id,
                "relation": rel.relation_type,
                "target_id": target.id,
                "target_name": target.name,
            }

            if entity_id not in relationships:
                relationships[entity_id] = []
            relationships[entity_id].append(rel_info)

            if target.id not in collected:
                collected.add(target.id)
                await self._collect_related_entities(
                    target.id, collected, relationships,
                    max_hops, current_hop + 1
                )

        # Get incoming relationships
        result = await self.db.execute(
            select(EntityRelationship, Entity)
            .join(Entity, EntityRelationship.source_entity_id == Entity.id)
            .where(EntityRelationship.target_entity_id == entity_id)
        )

        for rel, source in result.all():
            rel_info = {
                "source_id": source.id,
                "source_name": source.name,
                "relation": rel.relation_type,
                "target_id": entity_id,
            }

            if entity_id not in relationships:
                relationships[entity_id] = []
            relationships[entity_id].append(rel_info)

            if source.id not in collected:
                collected.add(source.id)
                await self._collect_related_entities(
                    source.id, collected, relationships,
                    max_hops, current_hop + 1
                )

    async def _get_chunk_entities(
        self,
        chunk_id: int,
        entity_ids: set,
    ) -> list[dict]:
        """Get entities associated with a chunk."""
        result = await self.db.execute(
            select(Entity)
            .join(DocumentEntity, Entity.id == DocumentEntity.entity_id)
            .where(
                DocumentEntity.chunk_id == chunk_id,
                DocumentEntity.entity_id.in_(entity_ids),
            )
        )

        return [
            {"id": e.id, "name": e.name, "type": e.entity_type}
            for e in result.scalars().all()
        ]

    async def _merge_results(
        self,
        vector_results: list[RetrievalResult],
        graph_results: list[RetrievalResult],
        vector_weight: float,
        graph_weight: float,
        top_k: int,
    ) -> list[RetrievalResult]:
        """
        Merge and rank results from vector and graph searches.

        Uses weighted combination of scores for ranking.
        """
        # Create a map of chunk_id to results
        result_map = {}

        # Add vector results
        for result in vector_results:
            result_map[result.chunk_id] = result

        # Merge graph results
        for result in graph_results:
            if result.chunk_id in result_map:
                # Combine with existing vector result
                existing = result_map[result.chunk_id]
                existing.graph_score = result.graph_score
                existing.matched_entities = result.matched_entities
                existing.relationships = result.relationships
                existing.source = "hybrid"
            else:
                result_map[result.chunk_id] = result

        # Calculate combined scores
        for result in result_map.values():
            # Normalize scores
            v_score = result.vector_score if result.vector_score else 0.0
            g_score = result.graph_score if result.graph_score else 0.0

            # Boost for hybrid matches
            hybrid_boost = 1.1 if result.source == "hybrid" else 1.0

            # Calculate combined score
            result.combined_score = (
                (vector_weight * v_score + graph_weight * g_score) * hybrid_boost
            )

        # Sort by combined score
        sorted_results = sorted(
            result_map.values(),
            key=lambda x: x.combined_score,
            reverse=True
        )

        return sorted_results[:top_k]

    async def get_entity_context(
        self,
        entity_name: str,
        max_relationships: int = 10,
    ) -> dict:
        """
        Get full context for an entity including relationships.

        Useful for building context for LLM prompts.
        """
        # Find entity
        result = await self.db.execute(
            select(Entity).where(
                or_(
                    Entity.name.ilike(f"%{entity_name}%"),
                    Entity.normalized_name == entity_name.lower().strip(),
                )
            ).limit(1)
        )
        entity = result.scalar_one_or_none()

        if not entity:
            return {"found": False}

        # Get outgoing relationships
        out_result = await self.db.execute(
            select(EntityRelationship, Entity)
            .join(Entity, EntityRelationship.target_entity_id == Entity.id)
            .where(EntityRelationship.source_entity_id == entity.id)
            .limit(max_relationships)
        )

        outgoing = [
            {
                "relation": rel.relation_type,
                "target": target.name,
                "target_type": target.entity_type,
                "confidence": rel.confidence,
            }
            for rel, target in out_result.all()
        ]

        # Get incoming relationships
        in_result = await self.db.execute(
            select(EntityRelationship, Entity)
            .join(Entity, EntityRelationship.source_entity_id == Entity.id)
            .where(EntityRelationship.target_entity_id == entity.id)
            .limit(max_relationships)
        )

        incoming = [
            {
                "source": source.name,
                "source_type": source.entity_type,
                "relation": rel.relation_type,
                "confidence": rel.confidence,
            }
            for rel, source in in_result.all()
        ]

        # Get documents mentioning this entity
        doc_result = await self.db.execute(
            select(Attachment)
            .join(DocumentEntity, Attachment.id == DocumentEntity.document_id)
            .where(DocumentEntity.entity_id == entity.id)
            .limit(5)
        )

        documents = [
            {"id": att.id, "filename": att.original_filename}
            for att in doc_result.scalars().all()
        ]

        return {
            "found": True,
            "entity": {
                "id": entity.id,
                "name": entity.name,
                "type": entity.entity_type,
                "mention_count": entity.mention_count,
            },
            "outgoing_relationships": outgoing,
            "incoming_relationships": incoming,
            "documents": documents,
        }

    def format_graph_context(self, results: list[RetrievalResult]) -> str:
        """
        Format retrieval results into a context string for LLM.

        Includes both chunk text and relationship information.
        """
        context_parts = []

        for i, result in enumerate(results, 1):
            part = f"[Source {i}: {result.filename}]\n"
            part += f"{result.chunk_text}\n"

            # Add entity and relationship context
            if result.matched_entities:
                entities_str = ", ".join(
                    f"{e['name']} ({e['type']})"
                    for e in result.matched_entities[:5]
                )
                part += f"Entities: {entities_str}\n"

            if result.relationships:
                rels_str = "; ".join(
                    f"{r.get('source_name', 'Entity')} {r['relation']} {r.get('target_name', 'Entity')}"
                    for r in result.relationships[:3]
                )
                part += f"Relationships: {rels_str}\n"

            context_parts.append(part)

        return "\n---\n".join(context_parts)
