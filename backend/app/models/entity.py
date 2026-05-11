"""
Entity model for Knowledge Graph.
Stores extracted entities from documents with optional embeddings for similarity matching.
"""

from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from typing import TYPE_CHECKING, List, Optional

from app.database import Base
from app.config import settings

if TYPE_CHECKING:
    from app.models.relationship import EntityRelationship
    from app.models.document_entity import DocumentEntity


class Entity(Base):
    """
    Represents an extracted entity from documents.

    Entities are normalized and deduplicated across documents.
    Each entity can have an embedding for similarity-based matching.
    """
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Entity identification
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Optional description/context
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Aliases for fuzzy matching (JSON array stored as text)
    aliases: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Embedding for semantic similarity matching
    embedding: Mapped[Optional[list]] = mapped_column(
        Vector(settings.RAG_EMBEDDING_DIM), nullable=True
    )

    # Metadata
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    outgoing_relationships: Mapped[List["EntityRelationship"]] = relationship(
        "EntityRelationship",
        foreign_keys="EntityRelationship.source_entity_id",
        back_populates="source_entity",
        cascade="all, delete-orphan"
    )
    incoming_relationships: Mapped[List["EntityRelationship"]] = relationship(
        "EntityRelationship",
        foreign_keys="EntityRelationship.target_entity_id",
        back_populates="target_entity",
        cascade="all, delete-orphan"
    )
    document_links: Mapped[List["DocumentEntity"]] = relationship(
        "DocumentEntity",
        back_populates="entity",
        cascade="all, delete-orphan"
    )

    # Indexes for efficient querying
    __table_args__ = (
        Index('ix_entities_type_name', 'entity_type', 'normalized_name'),
        Index(
            'ix_entities_embedding',
            embedding,
            postgresql_using='ivfflat',
            postgresql_with={'lists': 100},
            postgresql_ops={'embedding': 'vector_cosine_ops'}
        ),
    )

    def __repr__(self) -> str:
        return f"<Entity(id={self.id}, name='{self.name}', type='{self.entity_type}')>"
