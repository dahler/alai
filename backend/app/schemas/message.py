from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, field_validator


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
    sources: list = []

    @field_validator('sources', mode='before')
    @classmethod
    def coerce_none(cls, v: Any) -> list:
        return v if v is not None else []

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    content: str
    attachment_ids: list[int] = []
