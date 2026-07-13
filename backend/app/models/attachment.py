from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List, Optional

from app.database import Base

if TYPE_CHECKING:
    from app.models.message import Message
    from app.models.user import User
    from app.models.document_chunk import DocumentChunk
    from app.models.document_folder import DocumentFolder
    from app.models.document_section import DocumentSection
    from app.models.document_summary import DocumentSummary


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_company_doc: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True
    )
    is_embedded: Mapped[bool] = mapped_column(Boolean, default=False)
    graph_status: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, default=None
    )
    # Granular processing status for the new Docling pipeline
    # uploaded / parsing / sectioning / summarizing / embedding / done / failed
    processing_status: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, default="uploaded"
    )
    # Document version (incremented on re-process)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # How many top-level sections were extracted
    sections_count: Mapped[int] = mapped_column(Integer, default=0)
    folder_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("document_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    doc_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    message: Mapped[Optional["Message"]] = relationship(
        "Message", back_populates="attachments"
    )
    user: Mapped[Optional["User"]] = relationship(
        "User", back_populates="attachments"
    )
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="attachment", cascade="all, delete-orphan"
    )
    sections: Mapped[List["DocumentSection"]] = relationship(
        "DocumentSection",
        back_populates="attachment",
        cascade="all, delete-orphan",
    )
    summaries: Mapped[List["DocumentSummary"]] = relationship(
        "DocumentSummary",
        back_populates="attachment",
        cascade="all, delete-orphan",
    )
    folder: Mapped[Optional["DocumentFolder"]] = relationship(
        "DocumentFolder",
        back_populates="documents",
        foreign_keys=[folder_id],
    )

    @property
    def url(self) -> str:
        return f"/api/uploads/{self.filename}"

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    @property
    def is_document(self) -> bool:
        doc_types = {
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/json",
            "text/html",
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument"
            ".presentationml.presentation",
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet",
            "message/rfc822",
            "application/vnd.ms-outlook",
        }
        return (
            self.content_type in doc_types
            or self.content_type.startswith("text/")
        )
