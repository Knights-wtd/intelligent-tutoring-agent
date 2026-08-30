from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.tutor.models import TutorConversation, TutorMessage


def list_legacy_sessions(db: Session, user_id: UUID) -> list[dict[str, Any]]:
    conversations = db.scalars(
        select(TutorConversation)
        .where(TutorConversation.user_id == user_id)
        .order_by(TutorConversation.updated_at.desc())
    ).all()
    return [
        {
            "id": str(item.id),
            "knowledge_base_id": str(item.knowledge_base_id),
            "space_id": str(item.space_id),
            "title": item.title,
            "state": "archived",
            "legacy": True,
            "read_only": True,
            "can_resume": False,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in conversations
    ]


def get_legacy_session(db: Session, user_id: UUID, conversation_id: UUID) -> dict[str, Any] | None:
    conversation = db.scalar(
        select(TutorConversation).where(
            TutorConversation.id == conversation_id, TutorConversation.user_id == user_id
        )
    )
    if conversation is None:
        return None
    messages = db.scalars(
        select(TutorMessage)
        .where(TutorMessage.conversation_id == conversation.id)
        .order_by(TutorMessage.created_at, TutorMessage.id)
    ).all()
    return {
        "id": str(conversation.id),
        "knowledge_base_id": str(conversation.knowledge_base_id),
        "space_id": str(conversation.space_id),
        "title": conversation.title,
        "legacy": True,
        "read_only": True,
        "can_resume": False,
        "messages": [
            {
                "id": str(message.id),
                "role": message.role.value,
                "content": message.content,
                "citations": message.citations,
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }
