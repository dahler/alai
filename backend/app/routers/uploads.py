import io
import zipfile
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.services.storage import StorageService
from app.models.attachment import Attachment
from app.schemas.attachment import UploadResponse
from app.config import settings

router = APIRouter(prefix="/uploads", tags=["uploads"])
storage_service = StorageService()


@router.post("", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    # Validate file size
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE // (1024*1024)}MB",
        )

    # Reset file position
    await file.seek(0)

    # Validate file type
    if not storage_service.is_allowed_type(file.content_type):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type {file.content_type} is not allowed",
        )

    # Save file
    file_info = await storage_service.save_file(file)

    # Create attachment record (without message_id - will be linked later)
    attachment = Attachment(
        filename=file_info["filename"],
        original_filename=file_info["original_filename"],
        content_type=file_info["content_type"],
        file_size=file_info["file_size"],
        file_path=file_info["file_path"],
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    return UploadResponse(
        id=attachment.id,
        filename=attachment.filename,
        original_filename=attachment.original_filename,
        content_type=attachment.content_type,
        file_size=attachment.file_size,
        url=f"/api/uploads/{attachment.filename}",
        is_image=storage_service.is_image(attachment.content_type),
    )


@router.get("/{filename}")
async def get_file(filename: str):
    file_path = storage_service.get_file_path(filename)

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    return FileResponse(
        path=file_path,
        filename=filename,
    )


@router.delete("/{attachment_id}")
async def delete_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    attachment = result.scalar_one_or_none()

    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    # Delete file from storage
    storage_service.delete_file(attachment.filename)

    # Delete from database
    await db.delete(attachment)
    await db.commit()

    return {"message": "Attachment deleted"}


@router.get("")
async def list_all_files(db: AsyncSession = Depends(get_db)):
    """List all uploaded files"""
    result = await db.execute(
        select(Attachment).order_by(Attachment.created_at.desc())
    )
    attachments = result.scalars().all()

    return [
        {
            "id": att.id,
            "filename": att.filename,
            "original_filename": att.original_filename,
            "content_type": att.content_type,
            "file_size": att.file_size,
            "url": f"/api/uploads/{att.filename}",
            "is_image": att.content_type.startswith("image/"),
            "created_at": att.created_at.isoformat() if att.created_at else None,
        }
        for att in attachments
    ]


@router.get("/download/all")
async def download_all_files(db: AsyncSession = Depends(get_db)):
    """Download all uploaded files as a zip archive"""
    result = await db.execute(select(Attachment))
    attachments = result.scalars().all()

    if not attachments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No files found",
        )

    # Create zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for att in attachments:
            file_path = storage_service.get_file_path(att.filename)
            if file_path.exists():
                # Use original filename in the zip
                zip_file.write(file_path, att.original_filename)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=all_uploads.zip"
        }
    )
