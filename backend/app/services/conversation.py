from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.conversation import ConversationRepository
from app.models.conversation import Conversation
from app.models.user import User


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConversationRepository(db)

    async def create(
        self,
        user: User | None = None,
        anonymous_session_id: str | None = None,
        title: str = "New Chat",
    ) -> Conversation:
        return await self.repo.create(
            title=title,
            user_id=user.id if user else None,
            anonymous_session_id=anonymous_session_id if not user else None,
        )

    async def get_by_id(self, conversation_id: int) -> Conversation | None:
        return await self.repo.get_by_id(conversation_id)

    async def get_with_messages(self, conversation_id: int) -> Conversation | None:
        return await self.repo.get_with_messages(conversation_id)

    async def get_user_conversations(
        self, user: User | None, session_id: str | None
    ) -> list[Conversation]:
        return await self.repo.get_for_user_or_session(
            user_id=user.id if user else None,
            session_id=session_id,
        )

    async def update_title(
        self, conversation_id: int, title: str
    ) -> Conversation | None:
        conversation = await self.repo.get_by_id(conversation_id)
        if not conversation:
            return None
        return await self.repo.update(conversation, title=title)

    async def delete(self, conversation_id: int) -> bool:
        return await self.repo.delete(conversation_id)

    async def can_access(
        self,
        conversation: Conversation,
        user: User | None,
        session_id: str | None,
    ) -> bool:
        if user and conversation.user_id == user.id:
            return True
        if session_id and conversation.anonymous_session_id == session_id:
            return True
        return False
