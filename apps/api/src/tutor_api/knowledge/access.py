from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.classrooms.models import Classroom, ClassroomMembership, ClassroomRole
from tutor_api.identity.models import User
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.spaces.models import Space, SpaceKind


@dataclass(frozen=True)
class SpaceAccess:
    space: Space
    classroom_role: ClassroomRole | None = None


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")


def require_space_read_access(session: Session, user: User, space_id: UUID) -> SpaceAccess:
    personal_space = session.scalar(
        select(Space).where(
            Space.id == space_id,
            Space.kind == SpaceKind.PERSONAL,
            Space.owner_id == user.id,
        )
    )
    if personal_space is not None:
        return SpaceAccess(space=personal_space)

    classroom_access = session.execute(
        select(Space, ClassroomMembership.role)
        .join(Classroom, Classroom.space_id == Space.id)
        .join(
            ClassroomMembership,
            ClassroomMembership.classroom_id == Classroom.id,
        )
        .where(
            Space.id == space_id,
            Space.kind == SpaceKind.CLASSROOM,
            ClassroomMembership.user_id == user.id,
        )
    ).one_or_none()
    if classroom_access is None:
        raise _not_found()
    space, role = classroom_access
    return SpaceAccess(space=space, classroom_role=role)


def require_space_write_access(session: Session, user: User, space_id: UUID) -> SpaceAccess:
    access = require_space_read_access(session, user, space_id)
    if access.classroom_role is not None and access.classroom_role not in {
        ClassroomRole.OWNER,
        ClassroomRole.TEACHER,
    }:
        raise _forbidden()
    return access


def get_readable_knowledge_base(
    session: Session, user: User, knowledge_base_id: UUID
) -> KnowledgeBase:
    personal_knowledge_base = session.scalar(
        select(KnowledgeBase)
        .join(Space, Space.id == KnowledgeBase.space_id)
        .where(
            KnowledgeBase.id == knowledge_base_id,
            Space.kind == SpaceKind.PERSONAL,
            Space.owner_id == user.id,
        )
    )
    if personal_knowledge_base is not None:
        return personal_knowledge_base

    classroom_knowledge_base = session.scalar(
        select(KnowledgeBase)
        .join(Space, Space.id == KnowledgeBase.space_id)
        .join(Classroom, Classroom.space_id == Space.id)
        .join(
            ClassroomMembership,
            ClassroomMembership.classroom_id == Classroom.id,
        )
        .where(
            KnowledgeBase.id == knowledge_base_id,
            Space.kind == SpaceKind.CLASSROOM,
            ClassroomMembership.user_id == user.id,
        )
    )
    if classroom_knowledge_base is None:
        raise _not_found()
    return classroom_knowledge_base


def get_writable_knowledge_base(
    session: Session, user: User, knowledge_base_id: UUID
) -> KnowledgeBase:
    personal_knowledge_base = session.scalar(
        select(KnowledgeBase)
        .join(Space, Space.id == KnowledgeBase.space_id)
        .where(
            KnowledgeBase.id == knowledge_base_id,
            Space.kind == SpaceKind.PERSONAL,
            Space.owner_id == user.id,
        )
    )
    if personal_knowledge_base is not None:
        return personal_knowledge_base

    classroom_access = session.execute(
        select(KnowledgeBase, ClassroomMembership.role)
        .join(Space, Space.id == KnowledgeBase.space_id)
        .join(Classroom, Classroom.space_id == Space.id)
        .join(ClassroomMembership, ClassroomMembership.classroom_id == Classroom.id)
        .where(
            KnowledgeBase.id == knowledge_base_id,
            Space.kind == SpaceKind.CLASSROOM,
            ClassroomMembership.user_id == user.id,
        )
    ).one_or_none()
    if classroom_access is None:
        raise _not_found()
    knowledge_base, role = classroom_access
    if role not in {ClassroomRole.OWNER, ClassroomRole.TEACHER}:
        raise _forbidden()
    return knowledge_base
