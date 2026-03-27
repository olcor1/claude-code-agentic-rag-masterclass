from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.chat import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
    StreamMessageRequest,
)
from app.services.auth import get_current_user
from app.services.chat import create_conversation, get_conversation_or_404, list_conversations, stream_conversation_reply


router = APIRouter()


@router.get("", response_model=list[ConversationResponse])
def get_conversations(db: Session = Depends(get_db), user=Depends(get_current_user)) -> list[ConversationResponse]:
    items = list_conversations(db, user.id)
    return [ConversationResponse.model_validate(item) for item in items]


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def post_conversation(
    payload: ConversationCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> ConversationResponse:
    conversation = create_conversation(db, user.id, payload.title)
    return ConversationResponse.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(conversation_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)) -> ConversationDetailResponse:
    conversation = get_conversation_or_404(db, conversation_id, user.id)
    ordered_messages = sorted(conversation.messages, key=lambda item: item.created_at)
    return ConversationDetailResponse(
        id=conversation.id,
        user_id=conversation.user_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.model_validate(message) for message in ordered_messages],
    )


@router.post("/{conversation_id}/messages/stream")
def stream_message(
    conversation_id: str,
    payload: StreamMessageRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> StreamingResponse:
    get_conversation_or_404(db, conversation_id, user.id)
    generator = stream_conversation_reply(
        conversation_id=conversation_id,
        user_id=str(user.id),
        content=payload.content,
        metadata_filters=payload.metadata_filters.model_dump() if payload.metadata_filters else None,
    )
    return StreamingResponse(generator, media_type="text/event-stream")
