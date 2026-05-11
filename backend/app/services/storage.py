import os
import uuid
import aiofiles
from pathlib import Path
from fastapi import UploadFile

from app.config import settings


class StorageService:
    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR).resolve()
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_extension(self, filename: str) -> str:
        return Path(filename).suffix.lower()

    def _generate_unique_filename(self, original_filename: str) -> str:
        ext = self._get_file_extension(original_filename)
        unique_id = uuid.uuid4().hex[:16]
        return f"{unique_id}{ext}"

    async def save_file(self, file: UploadFile) -> dict:
        """Save uploaded file and return file info"""
        unique_filename = self._generate_unique_filename(file.filename)
        file_path = self.upload_dir / unique_filename

        # Read and save file
        content = await file.read()
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(content)

        return {
            "filename": unique_filename,
            "original_filename": file.filename,
            "content_type": file.content_type or "application/octet-stream",
            "file_size": len(content),
            "file_path": str(file_path),
        }

    def get_file_path(self, filename: str) -> Path:
        """Get full path to a file"""
        return self.upload_dir / filename

    def delete_file(self, filename: str) -> bool:
        """Delete a file"""
        file_path = self.upload_dir / filename
        if file_path.exists():
            os.remove(file_path)
            return True
        return False

    def is_image(self, content_type: str) -> bool:
        """Check if file is an image"""
        return content_type.startswith("image/")

    def is_allowed_type(self, content_type: str) -> bool:
        """Check if file type is allowed"""
        allowed_types = [
            # Images
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            # Documents
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            # Code
            "text/javascript",
            "text/css",
            "text/html",
            "application/json",
            "application/xml",
        ]
        return content_type in allowed_types
