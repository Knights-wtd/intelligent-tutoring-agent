from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.core.database import Base


class SpaceKind(StrEnum):
    PERSONAL = "personal"
    CLASSROOM = "classroom"


class Space(Base):
    __tablename__ = "spaces"
    __table_args__ = (
        Index(
            "uq_personal_space_owner",
            "owner_id",
            unique=True,
            postgresql_where=text("kind = 'personal'"),
            sqlite_where=text("kind = 'personal'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[SpaceKind] = mapped_column(
        Enum(
            SpaceKind,
            native_enum=False,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )
