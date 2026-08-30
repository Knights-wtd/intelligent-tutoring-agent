from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_readable_knowledge_base
from tutor_api.tutor.models import TutorConversation, TutorMessage
from tutor_api.tutor.schemas import TutorConversationResponse, TutorMessageResponse


class LegacyTutorConversationNotFound(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def serialize_legacy_tutor_conversation(
    session: Session,
    conversation: TutorConversation,
) -> TutorConversationResponse:
    messages = session.scalars(
        select(TutorMessage)
        .where(TutorMessage.conversation_id == conversation.id)
        .order_by(TutorMessage.created_at, TutorMessage.id)
    ).all()
    return TutorConversationResponse(
        id=conversation.id,
        knowledge_base_id=conversation.knowledge_base_id,
        title=conversation.title,
        messages=[
            TutorMessageResponse(
                id=message.id,
                role=message.role.value,
                content=message.content,
                citations=message.citations,
                created_at=_utc(message.created_at),
            )
            for message in messages
        ],
        created_at=_utc(conversation.created_at),
        updated_at=_utc(conversation.updated_at),
    )


def get_legacy_tutor_conversation(
    session: Session,
    current_user: User,
    conversation_id: UUID,
    *,
    knowledge_base_id: UUID | None = None,
) -> TutorConversationResponse:
    conversation = session.get(TutorConversation, conversation_id)
    if conversation is None or conversation.user_id != current_user.id:
        raise LegacyTutorConversationNotFound
    if knowledge_base_id is not None and conversation.knowledge_base_id != knowledge_base_id:
        raise LegacyTutorConversationNotFound
    try:
        knowledge_base = get_readable_knowledge_base(
            session,
            current_user,
            conversation.knowledge_base_id,
        )
    except HTTPException as error:
        if error.status_code == status.HTTP_404_NOT_FOUND:
            raise LegacyTutorConversationNotFound from None
        raise
    if conversation.space_id != knowledge_base.space_id:
        raise LegacyTutorConversationNotFound
    return serialize_legacy_tutor_conversation(session, conversation)


def list_legacy_tutor_conversations(
    session: Session,
    current_user: User,
    *,
    knowledge_base_id: UUID | None = None,
) -> list[TutorConversationResponse]:
    statement = select(TutorConversation).where(TutorConversation.user_id == current_user.id)
    if knowledge_base_id is not None:
        knowledge_base = get_readable_knowledge_base(session, current_user, knowledge_base_id)
        statement = statement.where(
            TutorConversation.knowledge_base_id == knowledge_base.id,
            TutorConversation.space_id == knowledge_base.space_id,
        )
    rows = session.scalars(
        statement.order_by(TutorConversation.updated_at.desc(), TutorConversation.id)
    ).all()
    if knowledge_base_id is not None:
        return [serialize_legacy_tutor_conversation(session, row) for row in rows]

    readable: list[TutorConversationResponse] = []
    for row in rows:
        try:
            get_readable_knowledge_base(session, current_user, row.knowledge_base_id)
        except HTTPException as error:
            if error.status_code == status.HTTP_404_NOT_FOUND:
                continue
            raise
        readable.append(serialize_legacy_tutor_conversation(session, row))
    return readable
