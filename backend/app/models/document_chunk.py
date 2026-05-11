from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Boolean, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from typing import TYPE_CHECKING

from app.database import Base
from app.config import settings

if TYPE_CHECKING:
    from app.models.attachment import Attachment
    from app.models.user import User


class DocumentChunk(Base):
    """Stores document chunks with embeddings for RAG."""
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Link to the source attachment
    attachment_id: Mapped[int] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), index=True
    )

    # Owner - null means company document (accessible by all)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Company document flag
    is_company_doc: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Chunk data
    chunk_index: Mapped[int] = mapped_column(Integer)  # Order within document
    chunk_text: Mapped[str] = mapped_column(Text)

    # Embedding vector
    embedding: Mapped[list] = mapped_column(Vector(settings.RAG_EMBEDDING_DIM))

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    attachment: Mapped["Attachment"] = relationship("Attachment", back_populates="chunks")
    user: Mapped["User"] = relationship("User", back_populates="document_chunks")

    # Index for vector similarity search
    __table_args__ = (
        Index(
            'ix_document_chunks_embedding',
            embedding,
            postgresql_using='ivfflat',
            postgresql_with={'lists': 100},
            postgresql_ops={'embedding': 'vector_cosine_ops'}
        ),
    )
