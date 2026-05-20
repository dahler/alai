from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List, Optional

from app.database import Base

if TYPE_CHECKING:
    from app.models.message import Message
    from app.models.user import User
    from app.models.document_chunk import DocumentChunk


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Owner of the attachment - null for anonymous users
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Company document flag - if true, accessible by all users
    is_company_doc: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Whether this document has been processed for RAG
    is_embedded: Mapped[bool] = mapped_column(Boolean, default=False)
    # Graph extraction status: None=not requested, pending/processing/done/failed/skipped
    graph_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default=None)

    filename: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    message: Mapped["Message"] = relationship("Message", back_populates="attachments")
    user: Mapped["User"] = relationship("User", back_populates="attachments")
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="attachment", cascade="all, delete-orphan"
    )

    @property
    def url(self) -> str:
        return f"/api/uploads/{self.filename}"

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    @property
    def is_document(self) -> bool:
        """Check if this is a document that can be embedded for RAG."""
        doc_types = {
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/json",
            "text/html",
        }
        return self.content_type in doc_types or self.content_type.startswith("text/")
