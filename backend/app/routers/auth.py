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
    code: str,
    state: str | None = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        auth_service = AuthService(db)
        user, token = await auth_service.authenticate_microsoft(
            code=code,
            anonymous_session_id=state,
        )

        # Redirect to frontend with token
        frontend_url = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "http://localhost:3000"
        redirect_url = f"{frontend_url}/auth/callback?token={token.access_token}"

        return RedirectResponse(url=redirect_url)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authentication failed: {str(e)}",
        )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(settings.ANONYMOUS_SESSION_COOKIE)
    return {"message": "Logged out successfully"}
