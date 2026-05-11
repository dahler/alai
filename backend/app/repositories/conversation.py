from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation
from app.models.message import Message
from app.repositories.base import BaseRepository


class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self, db: AsyncSession):
        super().__init__(Conversation, db)

    async def get_by_user_id(self, user_id: int) -> list[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_anonymous_session(self, session_id: str) -> list[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.anonymous_session_id == session_id)
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_for_user_or_session(
        self, user_id: int | None, session_id: str | None
    ) -> list[Conversation]:
        conditions = []
        if user_id:
            conditions.append(Conversation.user_id == user_id)
        if session_id:
            conditions.append(Conversation.anonymous_session_id == session_id)

        if not conditions:
            return []

        result = await self.db.execute(
            select(Conversation)
            .where(or_(*conditions))
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_with_messages(self, conversation_id: int) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(
                selectinload(Conversation.messages).selectinload(Message.attachments)
            )
        )
        return result.scalar_one_or_none()

    async def migrate_anonymous_to_user(
        self, session_id: str, user_id: int
    ) -> int:
        conversations = await self.get_by_anonymous_session(session_id)
        count = 0
        for conv in conversations:
            conv.user_id = user_id
            conv.anonymous_session_id = None
            count += 1
        await self.db.commit()
        return count
