import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.classrooms.models import (
    Classroom,
    ClassroomInvite,
    ClassroomMembership,
    ClassroomRole,
)
from tutor_api.identity.models import User
from tutor_api.spaces.models import Space, SpaceKind


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")


def _new_invite_code() -> tuple[str, str]:
    code = secrets.token_urlsafe(24)
    return code, hashlib.sha256(code.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def create_classroom(
    session: Session, user: User, name: str
) -> tuple[Classroom, Space, ClassroomMembership, str]:
    space = Space(owner_id=user.id, kind=SpaceKind.CLASSROOM, name=name)
    session.add(space)
    session.flush()
    classroom = Classroom(owner_id=user.id, space_id=space.id, name=name)
    session.add(classroom)
    session.flush()
    membership = ClassroomMembership(
        classroom_id=classroom.id, user_id=user.id, role=ClassroomRole.OWNER
    )
    session.add(membership)
    code, code_digest = _new_invite_code()
    session.add(
        ClassroomInvite(
            classroom_id=classroom.id,
            code_digest=code_digest,
            role=ClassroomRole.STUDENT,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            max_uses=1,
        )
    )
    session.flush()
    return classroom, space, membership, code


def join_classroom(
    session: Session, user: User, code: str
) -> tuple[Classroom, Space, ClassroomMembership]:
    invite = session.scalar(
        select(ClassroomInvite)
        .where(ClassroomInvite.code_digest == hashlib.sha256(code.encode()).hexdigest())
        .with_for_update()
    )
    if invite is None:
        raise _forbidden()
    existing = session.scalar(
        select(ClassroomMembership).where(
            ClassroomMembership.classroom_id == invite.classroom_id,
            ClassroomMembership.user_id == user.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已加入该班级")
    if (
        invite.revoked_at is not None
        or _utc(invite.expires_at) <= datetime.now(UTC)
        or invite.use_count >= invite.max_uses
    ):
        raise _forbidden()
    classroom = session.get(Classroom, invite.classroom_id)
    if classroom is None:
        raise _forbidden()
    space = session.get(Space, classroom.space_id)
    if space is None:
        raise _forbidden()
    membership = ClassroomMembership(
        classroom_id=classroom.id, user_id=user.id, role=invite.role
    )
    session.add(membership)
    invite.use_count += 1
    session.flush()
    return classroom, space, membership


def get_member_classroom(
    session: Session, user: User, classroom_id: UUID
) -> tuple[Classroom, Space, ClassroomMembership]:
    membership = session.scalar(
        select(ClassroomMembership).where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise _not_found()
    classroom = session.get(Classroom, classroom_id)
    if classroom is None:
        raise _not_found()
    space = session.get(Space, classroom.space_id)
    if space is None:
        raise _not_found()
    return classroom, space, membership


def update_member(
    session: Session, actor: User, classroom_id: UUID, user_id: UUID, role: str | None, remove: bool
) -> ClassroomMembership | None:
    _, _, actor_membership = get_member_classroom(session, actor, classroom_id)
    if actor_membership.role != ClassroomRole.OWNER:
        raise _forbidden()
    target = session.scalar(
        select(ClassroomMembership).where(
            ClassroomMembership.classroom_id == classroom_id, ClassroomMembership.user_id == user_id
        )
    )
    if target is None:
        raise _not_found()
    if target.role == ClassroomRole.OWNER:
        raise _forbidden()
    if remove:
        session.delete(target)
        return None
    target.role = ClassroomRole(role)
    session.flush()
    return target


def create_invite(
    session: Session, actor: User, classroom_id: UUID, expires_in_hours: int, max_uses: int
) -> tuple[str, ClassroomInvite]:
    _, _, membership = get_member_classroom(session, actor, classroom_id)
    if membership.role not in {ClassroomRole.OWNER, ClassroomRole.TEACHER}:
        raise _forbidden()
    code, code_digest = _new_invite_code()
    invite = ClassroomInvite(
        classroom_id=classroom_id,
        code_digest=code_digest,
        role=ClassroomRole.STUDENT,
        expires_at=datetime.now(UTC) + timedelta(hours=expires_in_hours),
        max_uses=max_uses,
    )
    session.add(invite)
    session.flush()
    return code, invite
