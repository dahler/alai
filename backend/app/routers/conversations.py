from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.conversation import ConversationService
from app.middleware.auth import get_optional_user, get_session_id
from app.schemas.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    ConversationWithMessages,
)
from app.models.user import User

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = get_session_id(request, response) if not user else None
    service = ConversationService(db)
    return await service.get_user_conversations(user, session_id)


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate,
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = get_session_id(request, response) if not user else None
    service = ConversationService(db)
    return await service.create(
        user=user,
        anonymous_session_id=session_id,
        title=data.title,
    )


@router.get("/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(
    conversation_id: int,
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = get_session_id(request, response) if not user else None
    service = ConversationService(db)

    conversation = await service.get_with_messages(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if not await service.can_access(conversation, user, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return conversation


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int,
    data: ConversationUpdate,
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = get_session_id(request, response) if not user else None
    service = ConversationService(db)

    conversation = await service.get_by_id(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if not await service.can_access(conversation, user, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    updated = await service.update_title(conversation_id, data.title)
    return updated


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: int,
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = get_session_id(request, response) if not user else None
    service = ConversationService(db)

    conversation = await service.get_by_id(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if not await service.can_access(conversation, user, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    await service.delete(conversation_id)
