from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class ReportTemplate(Base):
    __tablename__ = "report_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # pdf, docx, xlsx, pptx
    format: Mapped[str] = mapped_column(String(10))
    # JSON array of section definitions
    sections_json: Mapped[str] = mapped_column(Text)
    # comma-separated trigger keywords for auto-selection
    keywords: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # Path to the original uploaded template file (DOCX/XLSX/PPTX) for style-preserving generation
    template_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Admin-published templates visible to every user in the organisation
    is_company_wide: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User | None"] = relationship("User", back_populates="report_templates")
