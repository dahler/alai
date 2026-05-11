"""
DocumentEntity model for Knowledge Graph.
Links documents and chunks to extracted entities.
"""

from datetime import datetime
from sqlalchemy import Integer, DateTime, ForeignKey, Float, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, Optional

from app.database import Base

if TYPE_CHECKING:
    from app.models.entity import Entity
    from app.models.attachment import Attachment
    from app.models.document_chunk import DocumentChunk


class DocumentEntity(Base):
    """
    Links documents/chunks to entities.

    This table enables:
    - Finding all entities in a document
    - Finding all documents that mention an entity
    - Tracking entity mentions at chunk level
    """
    __tablename__ = "document_entities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Document reference
    document_id: Mapped[int] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Entity reference
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Optional chunk reference for granular tracking
    chunk_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Mention count in this document
    mention_count: Mapped[int] = mapped_column(Integer, default=1)

    # Confidence of entity extraction
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    document: Mapped["Attachment"] = relationship("Attachment", foreign_keys=[document_id])
    entity: Mapped["Entity"] = relationship("Entity", back_populates="document_links")
    chunk: Mapped[Optional["DocumentChunk"]] = relationship(
        "DocumentChunk", foreign_keys=[chunk_id]
    )

    # Indexes for efficient queries
    __table_args__ = (
        Index('ix_document_entities_doc_entity', 'document_id', 'entity_id', unique=True),
    )

    def __repr__(self) -> str:
        return f"<DocumentEntity(doc={self.document_id}, entity={self.entity_id})>"
