from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.classrooms.models import Classroom, ClassroomMembership
from tutor_api.identity.models import User
from tutor_api.spaces.models import Space, SpaceKind


def list_spaces(session: Session, user: User) -> list[Space]:
    personal = session.scalar(
        select(Space).where(Space.owner_id == user.id, Space.kind == SpaceKind.PERSONAL)
    )
    classroom_spaces = list(
        session.scalars(
            select(Space)
            .join(Classroom, Classroom.space_id == Space.id)
            .join(ClassroomMembership, ClassroomMembership.classroom_id == Classroom.id)
            .where(ClassroomMembership.user_id == user.id)
            .order_by(Classroom.created_at, Classroom.id)
        )
    )
    return ([personal] if personal is not None else []) + classroom_spaces
