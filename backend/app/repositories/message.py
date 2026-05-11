from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    def __init__(self, db: AsyncSession):
        super().__init__(Message, db)

    async def get_by_conversation(
        self, conversation_id: int, limit: int | None = None
    ) -> list[Message]:
        query = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        if limit:
            query = query.limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_recent_messages(
        self, conversation_id: int, limit: int = 20
    ) -> list[Message]:
        # Get the last N messages for context
        subquery = (
            select(Message.id)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )

        result = await self.db.execute(
            select(Message)
            .where(Message.id.in_(subquery))
            .order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())

    async def add_message(
        self, conversation_id: int, role: str, content: str
    ) -> Message:
        return await self.create(
            conversation_id=conversation_id,
            role=role,
            content=content
        )
