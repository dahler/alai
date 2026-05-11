"""
Relationship model for Knowledge Graph.
Stores relationships between entities extracted from documents.
"""

from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Float, ForeignKey, Text, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, Optional

from app.database import Base

if TYPE_CHECKING:
    from app.models.entity import Entity
    from app.models.attachment import Attachment
    from app.models.document_chunk import DocumentChunk


class EntityRelationship(Base):
    """
    Represents a relationship between two entities.

    Relationships are directional: source -> relation -> target
    Example: "Bank Indonesia" -> "regulates" -> "QRIS"
    """
    __tablename__ = "entity_relationships"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Source entity
    source_entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Relationship type (e.g., "regulates", "owns", "mentions")
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Target entity
    target_entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Confidence score from extraction (0.0 to 1.0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    # Source document where this relationship was extracted
    source_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Source chunk for more granular tracking
    source_chunk_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True
    )

    # Optional context/evidence for the relationship
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    source_entity: Mapped["Entity"] = relationship(
        "Entity",
        foreign_keys=[source_entity_id],
        back_populates="outgoing_relationships"
    )
    target_entity: Mapped["Entity"] = relationship(
        "Entity",
        foreign_keys=[target_entity_id],
        back_populates="incoming_relationships"
    )
    source_document: Mapped[Optional["Attachment"]] = relationship(
        "Attachment",
        foreign_keys=[source_document_id]
    )
    source_chunk: Mapped[Optional["DocumentChunk"]] = relationship(
        "DocumentChunk",
        foreign_keys=[source_chunk_id]
    )

    # Indexes for graph traversal
    __table_args__ = (
        Index('ix_relationships_source_relation', 'source_entity_id', 'relation_type'),
        Index('ix_relationships_target_relation', 'target_entity_id', 'relation_type'),
        Index('ix_relationships_triple', 'source_entity_id', 'relation_type', 'target_entity_id'),
    )

    def __repr__(self) -> str:
        return f"<EntityRelationship(source={self.source_entity_id}, rel='{self.relation_type}', target={self.target_entity_id})>"
