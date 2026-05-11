from pydantic import BaseModel

from app.schemas.user import UserResponse


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    exp: int


class LoginResponse(BaseModel):
    user: UserResponse
    token: Token


class MicrosoftUserInfo(BaseModel):
    id: str
    displayName: str | None = None
    mail: str | None = None
    userPrincipalName: str | None = None
