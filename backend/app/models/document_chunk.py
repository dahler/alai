from datetime import datetime
from sqlalchemy import Integer, DateTime, ForeignKey, Text, Boolean, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from typing import TYPE_CHECKING, Optional

from app.database import Base
from app.config import settings

if TYPE_CHECKING:
    from app.models.attachment import Attachment
    from app.models.user import User
    from app.models.document_section import DocumentSection


class DocumentChunk(Base):
    """Stores document chunks with embeddings for RAG."""
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    attachment_id: Mapped[int] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_company_doc: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True
    )

    # Link to the section this chunk belongs to
    section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("document_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Chunk data
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)

    # "Doc Title > Section > Subsection" prepended for richer embedding
    heading_context: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Page range this chunk covers
    page_start: Mapped[int] = mapped_column(Integer, default=0)
    page_end: Mapped[int] = mapped_column(Integer, default=0)

    # Token count (approximate)
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    # Embedding vector
    embedding: Mapped[list] = mapped_column(Vector(settings.RAG_EMBEDDING_DIM))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    attachment: Mapped["Attachment"] = relationship("Attachment", back_populates="chunks")
    user: Mapped[Optional["User"]] = relationship("User", back_populates="document_chunks")
    section: Mapped[Optional["DocumentSection"]] = relationship(
        "DocumentSection", back_populates="chunks"
    )

    __table_args__ = (
        Index(
            'ix_document_chunks_embedding',
            embedding,
            postgresql_using='ivfflat',
            postgresql_with={'lists': 100},
            postgresql_ops={
                'embedding': 'vector_cosine_ops',
            },
        ),
    )
