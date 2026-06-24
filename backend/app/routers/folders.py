"""
Document folder CRUD endpoints.
Folders let users group their documents in the knowledge base.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.attachment import Attachment
from app.models.document_folder import DocumentFolder
from app.models.user import User

router = APIRouter(prefix="/folders", tags=["folders"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FolderCreate(BaseModel):
    name: str
    is_company_folder: bool = False


class FolderRename(BaseModel):
    name: str


class FolderOut(BaseModel):
    id: int
    name: str
    is_company_folder: bool
    document_count: int
    created_at: str


class MoveDocumentIn(BaseModel):
    folder_id: Optional[int] = None  # None = remove from folder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_folder(folder_id: int, user: User, db: AsyncSession) -> DocumentFolder:
    result = await db.execute(
        select(DocumentFolder).where(DocumentFolder.id == folder_id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    if folder.user_id != user.id and not folder.is_company_folder:
        raise HTTPException(status_code=403, detail="Access denied")
    return folder


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[FolderOut])
async def list_folders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return folders visible to this user: own + company-wide."""
    result = await db.execute(
        select(DocumentFolder).where(
            or_(
                DocumentFolder.user_id == current_user.id,
                DocumentFolder.is_company_folder == True,  # noqa: E712
            )
        ).order_by(DocumentFolder.is_company_folder, DocumentFolder.name)
    )
    folders = result.scalars().all()

    # Count documents per folder
    count_result = await db.execute(
        select(Attachment.folder_id, func.count(Attachment.id))
        .where(Attachment.folder_id.in_([f.id for f in folders]))
        .group_by(Attachment.folder_id)
    )
    counts = {row[0]: row[1] for row in count_result.all()}

    return [
        FolderOut(
            id=f.id,
            name=f.name,
            is_company_folder=f.is_company_folder,
            document_count=counts.get(f.id, 0),
            created_at=f.created_at.isoformat(),
        )
        for f in folders
    ]


@router.post("", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: FolderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be empty")
    folder = DocumentFolder(
        name=name,
        user_id=current_user.id,
        is_company_folder=body.is_company_folder,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return FolderOut(
        id=folder.id,
        name=folder.name,
        is_company_folder=folder.is_company_folder,
        document_count=0,
        created_at=folder.created_at.isoformat(),
    )


@router.patch("/{folder_id}", response_model=FolderOut)
async def rename_folder(
    folder_id: int,
    body: FolderRename,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await _get_folder(folder_id, current_user, db)
    if folder.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can rename this folder")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be empty")
    folder.name = name
    await db.commit()
    await db.refresh(folder)

    count_result = await db.execute(
        select(func.count(Attachment.id)).where(Attachment.folder_id == folder.id)
    )
    count = count_result.scalar() or 0
    return FolderOut(
        id=folder.id,
        name=folder.name,
        is_company_folder=folder.is_company_folder,
        document_count=count,
        created_at=folder.created_at.isoformat(),
    )


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete folder. Documents inside are moved to no folder (not deleted)."""
    folder = await _get_folder(folder_id, current_user, db)
    if folder.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete this folder")
    await db.delete(folder)
    await db.commit()
