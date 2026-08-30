from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tutor_api.core.database import Base


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [member.value for member in values],
    )


class TutorMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class TutorMessageKind(StrEnum):
    """助手消息形态:answer 为正式作答,clarify 为 grill 式追问轮。"""

    ANSWER = "answer"
    CLARIFY = "clarify"


class TutorConversation(Base):
    __tablename__ = "tutor_conversations"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "user_id",
            "space_id",
            "knowledge_base_id",
            name="uq_tutor_conversation_scope",
        ),
        CheckConstraint("length(trim(title)) > 0", name="ck_tutor_conversation_title_nonempty"),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_tutor_conversation_knowledge_base_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_tutor_conversation_user", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", name="fk_tutor_conversation_space", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    messages: Mapped[list["TutorMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by=lambda: (TutorMessage.created_at, TutorMessage.id),
    )


class TutorMessage(Base):
    __tablename__ = "tutor_messages"
    __table_args__ = (
        CheckConstraint("length(trim(content)) > 0", name="ck_tutor_message_content_nonempty"),
        CheckConstraint("prompt_tokens >= 0", name="ck_tutor_message_prompt_tokens_nonnegative"),
        CheckConstraint(
            "completion_tokens >= 0", name="ck_tutor_message_completion_tokens_nonnegative"
        ),
        ForeignKeyConstraint(
            ["conversation_id", "user_id", "space_id", "knowledge_base_id"],
            [
                "tutor_conversations.id",
                "tutor_conversations.user_id",
                "tutor_conversations.space_id",
                "tutor_conversations.knowledge_base_id",
            ],
            name="fk_tutor_message_conversation_scope",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    space_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    role: Mapped[TutorMessageRole] = mapped_column(
        _enum(TutorMessageRole, "tutor_message_role"), nullable=False
    )
    kind: Mapped[TutorMessageKind] = mapped_column(
        _enum(TutorMessageKind, "tutor_message_kind"),
        nullable=False,
        default=TutorMessageKind.ANSWER,
        server_default=TutorMessageKind.ANSWER.value,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, object]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
        server_default="[]",
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    conversation: Mapped[TutorConversation] = relationship(back_populates="messages")
