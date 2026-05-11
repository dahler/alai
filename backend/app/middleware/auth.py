import secrets
from fastapi import Depends, HTTPException, status, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.auth import AuthService
from app.models.user import User
from app.config import settings

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    auth_service = AuthService(db)
    user_id = auth_service.verify_token(credentials.credentials)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = await auth_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not credentials:
        return None

    auth_service = AuthService(db)
    user_id = auth_service.verify_token(credentials.credentials)

    if not user_id:
        return None

    return await auth_service.get_user_by_id(user_id)


def get_session_id(request: Request, response: Response) -> str:
    session_id = request.cookies.get(settings.ANONYMOUS_SESSION_COOKIE)

    if not session_id:
        session_id = secrets.token_hex(32)
        response.set_cookie(
            key=settings.ANONYMOUS_SESSION_COOKIE,
            value=session_id,
            max_age=60 * 60 * 24 * 365,  # 1 year
            httponly=True,
            samesite="lax",
        )

    return session_id
