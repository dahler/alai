from datetime import datetime
from sqlalchemy import Integer, ForeignKey, DateTime, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, Optional

from app.database import Base

if TYPE_CHECKING:
    from app.models.attachment import Attachment


class DocumentConnection(Base):
    """Explicit reference from one document to another detected during ingestion."""

    __tablename__ = "document_connections"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", name="uq_doc_connection"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("attachments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    target_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("attachments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source: Mapped[Optional["Attachment"]] = relationship(
        "Attachment", foreign_keys=[source_id]
    )
    target: Mapped[Optional["Attachment"]] = relationship(
        "Attachment", foreign_keys=[target_id]
    )
