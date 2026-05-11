from datetime import datetime
from pydantic import BaseModel

from app.schemas.message import MessageResponse


class ConversationBase(BaseModel):
    title: str = "New Chat"


class ConversationCreate(ConversationBase):
    pass


class ConversationUpdate(BaseModel):
    title: str


class ConversationResponse(ConversationBase):
    id: int
    user_id: int | None = None
    anonymous_session_id: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationWithMessages(ConversationResponse):
    messages: list[MessageResponse] = []

    class Config:
        from_attributes = True
