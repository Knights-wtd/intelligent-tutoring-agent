from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.core.database import Base


class ClassroomRole(StrEnum):
    OWNER = "owner"
    TEACHER = "teacher"
    STUDENT = "student"


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id"), unique=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )


class ClassroomMembership(Base):
    __tablename__ = "classroom_memberships"
    __table_args__ = (UniqueConstraint("classroom_id", "user_id", name="uq_classroom_membership"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    classroom_id: Mapped[UUID] = mapped_column(ForeignKey("classrooms.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[ClassroomRole] = mapped_column(
        Enum(
            ClassroomRole,
            native_enum=False,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )


class ClassroomInvite(Base):
    __tablename__ = "classroom_invites"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    classroom_id: Mapped[UUID] = mapped_column(ForeignKey("classrooms.id"), index=True)
    code_digest: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[ClassroomRole] = mapped_column(
        Enum(
            ClassroomRole,
            native_enum=False,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        default=ClassroomRole.STUDENT,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
