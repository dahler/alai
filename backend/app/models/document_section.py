from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from typing import TYPE_CHECKING, List, Optional

from app.database import Base
from app.config import settings

if TYPE_CHECKING:
    from app.models.attachment import Attachment
    from app.models.document_chunk import DocumentChunk
    from app.models.document_summary import DocumentSummary


class DocumentSection(Base):
    """A structural section extracted from a document (heading + content)."""
    __tablename__ = "document_sections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    attachment_id: Mapped[int] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), index=True
    )
    parent_section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("document_sections.id", ondelete="CASCADE"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer, default=1)  # heading depth (1=H1, 2=H2 …)
    section_index: Mapped[int] = mapped_column(Integer, default=0)  # position in doc
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_start: Mapped[int] = mapped_column(Integer, default=0)
    page_end: Mapped[int] = mapped_column(Integer, default=0)

    # Summary and its embedding for section-first retrieval
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary_embedding: Mapped[Optional[list]] = mapped_column(
        Vector(settings.RAG_EMBEDDING_DIM), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    attachment: Mapped["Attachment"] = relationship("Attachment", back_populates="sections")
    chunks: Mapped[List["DocumentChunk"]] = relationship("DocumentChunk", back_populates="section")
    summaries: Mapped[List["DocumentSummary"]] = relationship("DocumentSummary", back_populates="section")
    subsections: Mapped[List["DocumentSection"]] = relationship(
        "DocumentSection", back_populates="parent_section"
    )
    parent_section: Mapped[Optional["DocumentSection"]] = relationship(
        "DocumentSection", back_populates="subsections", remote_side="DocumentSection.id"
    )

    __table_args__ = (
        Index(
            'ix_document_sections_summary_embedding',
            summary_embedding,
            postgresql_using='ivfflat',
            postgresql_with={'lists': 100},
            postgresql_ops={'summary_embedding': 'vector_cosine_ops'},
        ),
    )
