from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    email: EmailStr
    name: str | None = None
    avatar_url: str | None = None


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    name: str | None = None
    avatar_url: str | None = None


class UserResponse(UserBase):
    id: int
    is_admin: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
