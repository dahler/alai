"""
Graph Linking Service for Knowledge Graph.
Handles entity deduplication, matching, and linking across documents.
"""

import json
import re
import time
from typing import Optional
from difflib import SequenceMatcher
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from app.models.entity import Entity
from app.models.relationship import EntityRelationship
from app.models.document_entity import DocumentEntity
from app.services.entity_extraction import ExtractedEntity
from app.services.relationship_extraction import ExtractedRelationship
from app.services.embedding import EmbeddingService
from app.config import settings


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [GRAPH_LINK] {message}")


# Similarity thresholds
EXACT_MATCH_THRESHOLD = 1.0
FUZZY_MATCH_THRESHOLD = 0.85
SEMANTIC_MATCH_THRESHOLD = 0.90


class GraphLinkingService:
    """
    Service for linking entities and relationships in the knowledge graph.

    Handles:
    - Entity deduplication using fuzzy and semantic matching
    - Entity alias management
    - Cross-document entity linking
    - Relationship creation and deduplication
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_service = EmbeddingService()

    async def find_or_create_entity(
        self,
        extracted: ExtractedEntity,
        document_id: Optional[int] = None,
        chunk_id: Optional[int] = None,
    ) -> Entity:
        """
        Find an existing entity or create a new one.

        Uses multiple matching strategies:
        1. Exact normalized name match
        2. Fuzzy string matching
        3. Semantic similarity (if embeddings available)

        Args:
            extracted: Extracted entity from text
            document_id: Source document ID
            chunk_id: Source chunk ID

        Returns:
            Existing or newly created Entity
        """
        normalized_name = extracted.normalize_name()

        # Strategy 1: Exact normalized name match
        existing = await self._find_exact_match(
            normalized_name, extracted.entity_type
        )
        if existing:
            log(f"Exact match found: '{extracted.name}' -> Entity {existing.id}")
            await self._update_entity_mention(existing, extracted, document_id, chunk_id)
            return existing

        # Strategy 2: Fuzzy string matching
        existing = await self._find_fuzzy_match(
            extracted.name, normalized_name, extracted.entity_type
        )
        if existing:
            log(f"Fuzzy match found: '{extracted.name}' -> Entity {existing.id} ('{existing.name}')")
            await self._add_entity_alias(existing, extracted.name)
            await self._update_entity_mention(existing, extracted, document_id, chunk_id)
            return existing

        # Strategy 3: Semantic similarity (if embeddings available)
        existing = await self._find_semantic_match(
            extracted.name, extracted.entity_type
        )
        if existing:
            log(f"Semantic match found: '{extracted.name}' -> Entity {existing.id} ('{existing.name}')")
            await self._add_entity_alias(existing, extracted.name)
            await self._update_entity_mention(existing, extracted, document_id, chunk_id)
            return existing

        # No match found - create new entity
        log(f"Creating new entity: '{extracted.name}' ({extracted.entity_type})")
        return await self._create_entity(extracted, document_id, chunk_id)

    async def _find_exact_match(
        self,
        normalized_name: str,
        entity_type: str,
    ) -> Optional[Entity]:
        """Find entity with exact normalized name match."""
        result = await self.db.execute(
            select(Entity).where(
                Entity.normalized_name == normalized_name,
                Entity.entity_type == entity_type,
            )
        )
        return result.scalar_one_or_none()

    async def _find_fuzzy_match(
        self,
        name: str,
        normalized_name: str,
        entity_type: str,
    ) -> Optional[Entity]:
        """Find entity using fuzzy string matching."""
        # Get candidates of same type
        result = await self.db.execute(
            select(Entity).where(Entity.entity_type == entity_type)
        )
        candidates = result.scalars().all()

        best_match = None
        best_score = 0.0

        for candidate in candidates:
            # Check normalized name similarity
            score = SequenceMatcher(
                None, normalized_name, candidate.normalized_name
            ).ratio()

            # Also check original name
            name_score = SequenceMatcher(
                None, name.lower(), candidate.name.lower()
            ).ratio()

            # Check aliases
            alias_score = 0.0
            if candidate.aliases:
                try:
                    aliases = json.loads(candidate.aliases)
                    for alias in aliases:
                        alias_sim = SequenceMatcher(
                            None, normalized_name, alias.lower()
                        ).ratio()
                        alias_score = max(alias_score, alias_sim)
                except json.JSONDecodeError:
                    pass

            # Take best score
            final_score = max(score, name_score, alias_score)

            if final_score >= FUZZY_MATCH_THRESHOLD and final_score > best_score:
                best_match = candidate
                best_score = final_score

        return best_match

    async def _find_semantic_match(
        self,
        name: str,
        entity_type: str,
    ) -> Optional[Entity]:
        """Find entity using semantic similarity."""
        # Generate embedding for the entity name
        embedding = await self.embedding_service.embed_text(name)
        if not embedding:
            return None

        # Search for similar entities of same type with embeddings
        result = await self.db.execute(
            select(
                Entity,
                Entity.embedding.cosine_distance(embedding).label("distance")
            )
            .where(
                Entity.entity_type == entity_type,
                Entity.embedding.isnot(None),
            )
            .order_by("distance")
            .limit(1)
        )

        row = result.first()
        if row:
            entity, distance = row
            similarity = 1 - distance
            if similarity >= SEMANTIC_MATCH_THRESHOLD:
                return entity

        return None

    async def _create_entity(
        self,
        extracted: ExtractedEntity,
        document_id: Optional[int] = None,
        chunk_id: Optional[int] = None,
    ) -> Entity:
        """Create a new entity in the database."""
        # Generate embedding for the entity name
        embedding = await self.embedding_service.embed_text(extracted.name)

        entity = Entity(
            name=extracted.name,
            normalized_name=extracted.normalize_name(),
            entity_type=extracted.entity_type,
            embedding=embedding,
            mention_count=1,
        )
        self.db.add(entity)
        await self.db.flush()  # Get the ID

        # Link to document if provided
        if document_id:
            doc_entity = DocumentEntity(
                document_id=document_id,
                entity_id=entity.id,
                chunk_id=chunk_id,
                confidence=extracted.confidence,
            )
            self.db.add(doc_entity)

        return entity

    async def _update_entity_mention(
        self,
        entity: Entity,
        extracted: ExtractedEntity,
        document_id: Optional[int] = None,
        chunk_id: Optional[int] = None,
    ):
        """Update entity mention count and document link."""
        entity.mention_count += 1

        if document_id:
            # Check if document link exists
            result = await self.db.execute(
                select(DocumentEntity).where(
                    DocumentEntity.document_id == document_id,
                    DocumentEntity.entity_id == entity.id,
                )
            )
            doc_entity = result.scalar_one_or_none()

            if doc_entity:
                doc_entity.mention_count += 1
            else:
                doc_entity = DocumentEntity(
                    document_id=document_id,
                    entity_id=entity.id,
                    chunk_id=chunk_id,
                    confidence=extracted.confidence,
                )
                self.db.add(doc_entity)

    async def _add_entity_alias(self, entity: Entity, alias: str):
        """Add an alias to an entity."""
        try:
            aliases = json.loads(entity.aliases) if entity.aliases else []
        except json.JSONDecodeError:
            aliases = []

        alias_lower = alias.lower().strip()
        if alias_lower not in [a.lower() for a in aliases]:
            aliases.append(alias)
            entity.aliases = json.dumps(aliases)

    async def create_relationship(
        self,
        extracted: ExtractedRelationship,
        source_entity: Entity,
        target_entity: Entity,
        document_id: Optional[int] = None,
        chunk_id: Optional[int] = None,
    ) -> Optional[EntityRelationship]:
        """
        Create a relationship between entities.

        Checks for existing relationships to avoid duplicates.

        Args:
            extracted: Extracted relationship
            source_entity: Source entity
            target_entity: Target entity
            document_id: Source document ID
            chunk_id: Source chunk ID

        Returns:
            Created or existing EntityRelationship
        """
        # Check if relationship already exists
        result = await self.db.execute(
            select(EntityRelationship).where(
                EntityRelationship.source_entity_id == source_entity.id,
                EntityRelationship.relation_type == extracted.relation_type,
                EntityRelationship.target_entity_id == target_entity.id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            log(f"Relationship exists: {source_entity.name} -> {existing.relation_type} -> {target_entity.name}")
            # Update confidence if higher
            if extracted.confidence > existing.confidence:
                existing.confidence = extracted.confidence
            return existing

        # Create new relationship
        log(f"Creating relationship: {source_entity.name} -> {extracted.relation_type} -> {target_entity.name}")
        relationship = EntityRelationship(
            source_entity_id=source_entity.id,
            relation_type=extracted.relation_type,
            target_entity_id=target_entity.id,
            confidence=extracted.confidence,
            source_document_id=document_id,
            source_chunk_id=chunk_id,
            context=extracted.context,
        )
        self.db.add(relationship)
        return relationship

    async def link_entities_batch(
        self,
        entities: list[ExtractedEntity],
        document_id: int,
        chunk_id: Optional[int] = None,
    ) -> dict[str, Entity]:
        """
        Link a batch of entities to the graph.

        Returns a mapping of entity names to Entity objects.
        """
        entity_map = {}

        for extracted in entities:
            entity = await self.find_or_create_entity(
                extracted, document_id, chunk_id
            )
            entity_map[extracted.name.lower()] = entity
            entity_map[extracted.normalize_name()] = entity

        return entity_map

    async def link_relationships_batch(
        self,
        relationships: list[ExtractedRelationship],
        entity_map: dict[str, Entity],
        document_id: int,
        chunk_id: Optional[int] = None,
    ) -> list[EntityRelationship]:
        """
        Link a batch of relationships to the graph.

        Args:
            relationships: Extracted relationships
            entity_map: Mapping of entity names to Entity objects
            document_id: Source document ID
            chunk_id: Source chunk ID

        Returns:
            List of created/found EntityRelationship objects
        """
        created_relationships = []

        for extracted in relationships:
            # Find source and target entities
            source_key = extracted.source.lower().strip()
            target_key = extracted.target.lower().strip()

            source_entity = entity_map.get(source_key)
            target_entity = entity_map.get(target_key)

            # Try normalized names if not found
            if not source_entity:
                source_entity = entity_map.get(extracted.normalize_source())
            if not target_entity:
                target_entity = entity_map.get(extracted.normalize_target())

            if source_entity and target_entity:
                relationship = await self.create_relationship(
                    extracted, source_entity, target_entity,
                    document_id, chunk_id
                )
                if relationship:
                    created_relationships.append(relationship)
            else:
                log(f"Skipping relationship - entities not found: {extracted.source} -> {extracted.target}")

        return created_relationships

    async def get_entity_connections(
        self,
        entity_id: int,
        max_depth: int = 2,
    ) -> dict:
        """
        Get all connections for an entity up to a certain depth.

        Args:
            entity_id: Entity to get connections for
            max_depth: Maximum depth of graph traversal

        Returns:
            Dictionary with connected entities and relationships
        """
        visited = {entity_id}
        connections = {
            "entities": [],
            "relationships": [],
        }

        await self._traverse_connections(
            entity_id, visited, connections, max_depth, 0
        )

        return connections

    async def _traverse_connections(
        self,
        entity_id: int,
        visited: set,
        connections: dict,
        max_depth: int,
        current_depth: int,
    ):
        """Recursively traverse entity connections."""
        if current_depth >= max_depth:
            return

        # Get outgoing relationships
        result = await self.db.execute(
            select(EntityRelationship, Entity)
            .join(Entity, EntityRelationship.target_entity_id == Entity.id)
            .where(EntityRelationship.source_entity_id == entity_id)
        )

        for rel, target_entity in result.all():
            connections["relationships"].append({
                "source_id": entity_id,
                "relation": rel.relation_type,
                "target_id": target_entity.id,
                "target_name": target_entity.name,
                "confidence": rel.confidence,
            })

            if target_entity.id not in visited:
                visited.add(target_entity.id)
                connections["entities"].append({
                    "id": target_entity.id,
                    "name": target_entity.name,
                    "type": target_entity.entity_type,
                    "depth": current_depth + 1,
                })

                await self._traverse_connections(
                    target_entity.id, visited, connections,
                    max_depth, current_depth + 1
                )

        # Get incoming relationships
        result = await self.db.execute(
            select(EntityRelationship, Entity)
            .join(Entity, EntityRelationship.source_entity_id == Entity.id)
            .where(EntityRelationship.target_entity_id == entity_id)
        )

        for rel, source_entity in result.all():
            connections["relationships"].append({
                "source_id": source_entity.id,
                "source_name": source_entity.name,
                "relation": rel.relation_type,
                "target_id": entity_id,
                "confidence": rel.confidence,
            })

            if source_entity.id not in visited:
                visited.add(source_entity.id)
                connections["entities"].append({
                    "id": source_entity.id,
                    "name": source_entity.name,
                    "type": source_entity.entity_type,
                    "depth": current_depth + 1,
                })

                await self._traverse_connections(
                    source_entity.id, visited, connections,
                    max_depth, current_depth + 1
                )

    async def get_documents_for_entity(self, entity_id: int) -> list[dict]:
        """Get all documents that mention an entity."""
        from app.models.attachment import Attachment

        result = await self.db.execute(
            select(DocumentEntity, Attachment)
            .join(Attachment, DocumentEntity.document_id == Attachment.id)
            .where(DocumentEntity.entity_id == entity_id)
        )

        documents = []
        for doc_entity, attachment in result.all():
            documents.append({
                "document_id": attachment.id,
                "filename": attachment.original_filename,
                "mention_count": doc_entity.mention_count,
                "confidence": doc_entity.confidence,
            })

        return documents

    async def find_related_documents(
        self,
        document_id: int,
        min_shared_entities: int = 2,
    ) -> list[dict]:
        """
        Find documents related to a given document through shared entities.

        Args:
            document_id: Document to find relations for
            min_shared_entities: Minimum shared entities to be considered related

        Returns:
            List of related documents with shared entity info
        """
        from app.models.attachment import Attachment

        # Get entities in the source document
        result = await self.db.execute(
            select(DocumentEntity.entity_id)
            .where(DocumentEntity.document_id == document_id)
        )
        source_entity_ids = [row[0] for row in result.all()]

        if not source_entity_ids:
            return []

        # Find documents sharing these entities
        result = await self.db.execute(
            select(
                DocumentEntity.document_id,
                func.count(DocumentEntity.entity_id).label("shared_count"),
            )
            .where(
                DocumentEntity.entity_id.in_(source_entity_ids),
                DocumentEntity.document_id != document_id,
            )
            .group_by(DocumentEntity.document_id)
            .having(func.count(DocumentEntity.entity_id) >= min_shared_entities)
            .order_by(func.count(DocumentEntity.entity_id).desc())
        )

        related_docs = []
        for doc_id, shared_count in result.all():
            # Get document info
            doc_result = await self.db.execute(
                select(Attachment).where(Attachment.id == doc_id)
            )
            attachment = doc_result.scalar_one_or_none()

            if attachment:
                # Get shared entities
                shared_result = await self.db.execute(
                    select(Entity)
                    .join(DocumentEntity, Entity.id == DocumentEntity.entity_id)
                    .where(
                        DocumentEntity.document_id == doc_id,
                        DocumentEntity.entity_id.in_(source_entity_ids),
                    )
                )
                shared_entities = [
                    {"id": e.id, "name": e.name, "type": e.entity_type}
                    for e in shared_result.scalars().all()
                ]

                related_docs.append({
                    "document_id": doc_id,
                    "filename": attachment.original_filename,
                    "shared_entity_count": shared_count,
                    "shared_entities": shared_entities,
                })

        return related_docs
