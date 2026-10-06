from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.schemas.message import MessageResponse


class ConversationBase(BaseModel):
    title: str = "New Chat"


class ConversationCreate(ConversationBase):
    pass


class ConversationUpdate(BaseModel):
    title: str


class ConversationResponse(ConversationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    anonymous_session_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationWithMessages(ConversationResponse):
    messages: list[MessageResponse] = []
