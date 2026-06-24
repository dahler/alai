from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List, Optional

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.attachment import Attachment


class DocumentFolder(Base):
    __tablename__ = "document_folders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    is_company_folder: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[Optional["User"]] = relationship("User")
    documents: Mapped[List["Attachment"]] = relationship(
        "Attachment", back_populates="folder", foreign_keys="Attachment.folder_id"
    )
