from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.message import MessageRepository
from app.models.message import Message
from app.models.attachment import Attachment


class MessageService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MessageRepository(db)

    async def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        attachment_ids: list[int] | None = None,
        sources: list | None = None,
    ) -> Message:
        # Create message
        message = await self.repo.add_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources=sources,
        )

        # Link attachments to message
        if attachment_ids:
            result = await self.db.execute(
                select(Attachment).where(Attachment.id.in_(attachment_ids))
            )
            attachments = result.scalars().all()
            for attachment in attachments:
                attachment.message_id = message.id
            await self.db.commit()

        return message

    async def get_conversation_messages(
        self, conversation_id: int, limit: int | None = None
    ) -> list[Message]:
        return await self.repo.get_by_conversation(conversation_id, limit)

    async def get_recent_context(
        self, conversation_id: int, limit: int = 20
    ) -> list[Message]:
        return await self.repo.get_recent_messages(conversation_id, limit)
