from datetime import datetime
from pydantic import BaseModel, ConfigDict


class AttachmentBase(BaseModel):
    filename: str
    original_filename: str
    content_type: str
    file_size: int


class AttachmentCreate(AttachmentBase):
    file_path: str


class AttachmentResponse(AttachmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: int | None = None
    created_at: datetime
    url: str | None = None


class UploadResponse(BaseModel):
    id: int
    filename: str
    original_filename: str
    content_type: str
    file_size: int
    url: str
    is_image: bool
