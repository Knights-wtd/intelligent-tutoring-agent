from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tutor_api.identity.models import User
from tutor_api.knowledge.access import (
    get_readable_knowledge_base,
    require_space_read_access,
    require_space_write_access,
)
from tutor_api.knowledge.models import KnowledgeBase

_KNOWLEDGE_BASE_NAME_CONSTRAINT = "uq_knowledge_base_name_in_space"


def _is_name_conflict(error: IntegrityError) -> bool:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == _KNOWLEDGE_BASE_NAME_CONSTRAINT:
        return True
    message = str(original)
    return (
        _KNOWLEDGE_BASE_NAME_CONSTRAINT in message
        or "knowledge_bases.space_id, knowledge_bases.name" in message
    )


def create_knowledge_base(
    session: Session,
    user: User,
    space_id: UUID,
    name: str,
) -> KnowledgeBase:
    require_space_write_access(session, user, space_id)
    knowledge_base = KnowledgeBase(
        space_id=space_id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name=name,
    )
    try:
        with session.begin_nested():
            session.add(knowledge_base)
            session.flush()
    except IntegrityError as error:
        if _is_name_conflict(error):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="知识库名称已存在",
            ) from None
        raise
    return knowledge_base


def list_knowledge_bases(
    session: Session, user: User, space_id: UUID
) -> list[KnowledgeBase]:
    require_space_read_access(session, user, space_id)
    return list(
        session.scalars(
            select(KnowledgeBase)
            .where(KnowledgeBase.space_id == space_id)
            .order_by(KnowledgeBase.created_at, KnowledgeBase.id)
        )
    )


def get_knowledge_base(
    session: Session, user: User, knowledge_base_id: UUID
) -> KnowledgeBase:
    return get_readable_knowledge_base(session, user, knowledge_base_id)
