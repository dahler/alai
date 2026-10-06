from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.middleware.auth import get_current_user, get_session_id
from app.models.user import User
from app.schemas.user import UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

_DEFAULT_FRONTEND = "http://localhost:3000"


def _frontend_url() -> str:
    return settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else _DEFAULT_FRONTEND


@router.get("/login")
@limiter.limit("10/minute")
async def login(request: Request, response: Response):
    session_id = get_session_id(request, response)
    auth_url = AuthService(None).get_microsoft_auth_url(state=session_id)
    return {"auth_url": auth_url}


@router.get("/callback")
@limiter.limit("20/minute")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    base = _frontend_url()

    if error:
        print(f"[AUTH] Microsoft OAuth error: {error} — {error_description}")
        return RedirectResponse(
            url=f"{base}/auth/callback?error={error}"
        )

    if not code:
        return RedirectResponse(
            url=f"{base}/auth/callback?error=missing_code"
        )

    try:
        _, token = await AuthService(db).authenticate_microsoft(
            code=code, state=state
        )
        resp = RedirectResponse(url=f"{base}/auth/callback")
        resp.set_cookie(
            key="auth_token",
            value=token.access_token,
            httponly=True,
            samesite="lax",
            secure=not settings.DEBUG,
            max_age=settings.JWT_EXPIRATION_MINUTES * 60,
            path="/",
        )
        return resp
    except Exception as e:
        print(f"[AUTH] Authentication failed: {e}")
        return RedirectResponse(
            url=f"{base}/auth/callback?error=auth_failed"
        )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("auth_token", path="/")
    response.delete_cookie(settings.ANONYMOUS_SESSION_COOKIE)
    return {"message": "Logged out successfully"}
