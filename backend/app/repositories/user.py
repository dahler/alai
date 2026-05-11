from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db: AsyncSession):
        super().__init__(User, db)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_or_create_by_email(
        self, email: str, name: str | None = None, avatar_url: str | None = None
    ) -> tuple[User, bool]:
        user = await self.get_by_email(email)
        if user:
            return user, False

        user = await self.create(email=email, name=name, avatar_url=avatar_url)
        return user, True
