from datetime import datetime
from pydantic import BaseModel
from typing import Literal


class AttachmentInfo(BaseModel):
    id: int
    filename: str
    original_filename: str
    content_type: str
    file_size: int
    url: str
    is_image: bool

    class Config:
        from_attributes = True


class MessageBase(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class MessageCreate(MessageBase):
    pass


class MessageResponse(MessageBase):
    id: int
    conversation_id: int
    created_at: datetime
    attachments: list[AttachmentInfo] = []

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    content: str
    attachment_ids: list[int] = []
