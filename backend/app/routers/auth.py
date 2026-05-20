from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.auth import AuthService
from app.middleware.auth import get_current_user, get_session_id
from app.schemas.auth import LoginResponse
from app.schemas.user import UserResponse
from app.models.user import User
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request, response: Response):
    session_id = get_session_id(request, response)
    auth_service = AuthService(None)
    auth_url = auth_service.get_microsoft_auth_url(state=session_id)
    return {"auth_url": auth_url}


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    frontend_url = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "http://localhost:3000"

    # Microsoft returned an error (e.g. redirect URI mismatch, user cancelled)
    if error:
        print(f"[AUTH] Microsoft OAuth error: {error} — {error_description}")
        return RedirectResponse(
            url=f"{frontend_url}/auth/callback?error={error}&error_description={error_description or ''}"
        )

    if not code:
        return RedirectResponse(
            url=f"{frontend_url}/auth/callback?error=missing_code"
        )

    try:
        auth_service = AuthService(db)
        user, token = await auth_service.authenticate_microsoft(
            code=code,
            state=state,
        )
        return RedirectResponse(url=f"{frontend_url}/auth/callback?token={token.access_token}")
    except Exception as e:
        print(f"[AUTH] Authentication failed: {str(e)}")
        return RedirectResponse(
            url=f"{frontend_url}/auth/callback?error=auth_failed&error_description={str(e)}"
        )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(settings.ANONYMOUS_SESSION_COOKIE)
    return {"message": "Logged out successfully"}
