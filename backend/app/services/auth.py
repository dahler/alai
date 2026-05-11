from datetime import datetime, timedelta
from jose import jwt, JWTError
import httpx
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.user import UserRepository
from app.repositories.conversation import ConversationRepository
from app.models.user import User
from app.schemas.auth import Token, MicrosoftUserInfo


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.conversation_repo = ConversationRepository(db)

    def create_access_token(self, user_id: int) -> Token:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)
        payload = {
            "sub": str(user_id),
            "exp": expire,
        }
        token = jwt.encode(
            payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        return Token(access_token=token)

    def verify_token(self, token: str) -> int | None:
        try:
            payload = jwt.decode(
                token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
            user_id = int(payload.get("sub"))
            return user_id
        except (JWTError, ValueError):
            return None

    def get_microsoft_auth_url(self, state: str | None = None) -> str:
        params = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "scope": "openid profile email User.Read",
            "response_mode": "query",
        }
        if state:
            params["state"] = state

        base_url = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"
        return f"{base_url}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> dict:
        token_url = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token"

        data = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            return response.json()

    async def get_microsoft_user_info(self, access_token: str) -> MicrosoftUserInfo:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            data = response.json()
            return MicrosoftUserInfo(**data)

    async def authenticate_microsoft(
        self, code: str, anonymous_session_id: str | None = None
    ) -> tuple[User, Token]:
        # Exchange code for Microsoft token
        token_data = await self.exchange_code_for_token(code)
        ms_access_token = token_data.get("access_token")

        # Get user info from Microsoft
        user_info = await self.get_microsoft_user_info(ms_access_token)

        # Get email (prefer mail, fallback to userPrincipalName)
        email = user_info.mail or user_info.userPrincipalName
        if not email:
            raise ValueError("Could not get email from Microsoft account")

        # Create or get user
        user, created = await self.user_repo.get_or_create_by_email(
            email=email,
            name=user_info.displayName,
        )

        # Migrate anonymous conversations if session ID provided
        if anonymous_session_id:
            await self.conversation_repo.migrate_anonymous_to_user(
                anonymous_session_id, user.id
            )

        # Create JWT token
        token = self.create_access_token(user.id)

        return user, token

    async def get_user_by_id(self, user_id: int) -> User | None:
        return await self.user_repo.get_by_id(user_id)
