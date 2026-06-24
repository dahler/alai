from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, Optional

from app.database import Base

if TYPE_CHECKING:
    from app.models.attachment import Attachment
    from app.models.document_section import DocumentSection


class DocumentSummary(Base):
    """Stores AI-generated summaries for documents and individual sections."""
    __tablename__ = "document_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    attachment_id: Mapped[int] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), index=True
    )
    # Null means this is a document-level summary; set means section-level summary
    section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("document_sections.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # 'document' | 'section'
    summary_type: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    attachment: Mapped["Attachment"] = relationship("Attachment", back_populates="summaries")
    section: Mapped[Optional["DocumentSection"]] = relationship(
        "DocumentSection", back_populates="summaries"
    )
