"""
Files router — serves generated downloadable files.
"""

import time

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.services.file_generation import FileGenerationService, GENERATED_DIR

router = APIRouter(prefix="/files", tags=["files"])


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] [FILES] {msg}", flush=True)


@router.get("/download/{file_id}")
async def download_file(file_id: str):
    """Download a generated file by its ID."""
    log(f"Download: {file_id}")
    log(f"Dir: {GENERATED_DIR.resolve()}")

    svc = FileGenerationService()
    result = svc.get_file(file_id)
    if not result:
        log(f"File not found: {file_id}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found or expired")

    file_path, original_filename, content_type = result
    log(f"Serving: {file_path} ({content_type})")
    return FileResponse(
        path=str(file_path),
        media_type=content_type,
        filename=original_filename,
    )
