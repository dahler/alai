"""
Files router — serves generated downloadable files.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.services.file_generation import FileGenerationService

router = APIRouter(prefix="/files", tags=["files"])
_svc = FileGenerationService()


@router.get("/download/{file_id}")
async def download_file(file_id: str):
    """Download a generated file by its ID."""
    result = _svc.get_file(file_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found or expired")

    file_path, original_filename, content_type = result
    return FileResponse(
        path=str(file_path),
        media_type=content_type,
        filename=original_filename,
        headers={"Content-Disposition": f'attachment; filename="{original_filename}"'},
    )
