from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column

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


def _json() -> JSON:
    return JSON().with_variant(JSONB(), "postgresql")


def _sha256_check(column_name: str) -> str:
    stripped = column_name
    for character in "0123456789abcdef":
        stripped = f"replace({stripped}, '{character}', '')"
    return f"length({column_name}) = 64 AND {stripped} = ''"


class AgentSessionState(StrEnum):
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    STOPPED = "stopped"
    FAILED = "failed"
    ARCHIVED = "archived"


class AgentTurnState(StrEnum):
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_agent_session_owner"),
        UniqueConstraint(
            "id",
            "user_id",
            "space_id",
            "knowledge_base_id",
            name="uq_agent_session_scope",
        ),
        CheckConstraint(
            "last_event_sequence >= 0", name="ck_agent_session_last_sequence_nonnegative"
        ),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_agent_session_knowledge_base_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_agent_session_user", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", name="fk_agent_session_space", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    provider: Mapped[str] = mapped_column(
        String(100), nullable=False, default="claude", server_default="claude"
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    permission_mode: Mapped[str] = mapped_column(
        String(100), nullable=False, default="bypassPermissions", server_default="bypassPermissions"
    )
    native_session_id: Mapped[str | None] = mapped_column(String(512), index=True)
    state: Mapped[AgentSessionState] = mapped_column(
        _enum(AgentSessionState, "agent_session_state"),
        nullable=False,
        default=AgentSessionState.RUNNING,
        server_default=AgentSessionState.RUNNING.value,
        index=True,
    )
    parent_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_sessions.id", name="fk_agent_session_parent", ondelete="SET NULL"),
        index=True,
    )
    forked_from_turn_id: Mapped[UUID | None] = mapped_column(index=True)
    rewind_checkpoint_id: Mapped[str | None] = mapped_column(String(512))
    last_event_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recovery: Mapped[dict[str, Any]] = mapped_column(
        _json(), nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentTurn(Base):
    __tablename__ = "agent_turns"
    __table_args__ = (
        CheckConstraint("input_tokens >= 0", name="ck_agent_turn_input_tokens_nonnegative"),
        CheckConstraint("output_tokens >= 0", name="ck_agent_turn_output_tokens_nonnegative"),
        CheckConstraint("cache_tokens >= 0", name="ck_agent_turn_cache_tokens_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", name="fk_agent_turn_session", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    response_summary: Mapped[str | None] = mapped_column(Text)
    state: Mapped[AgentTurnState] = mapped_column(
        _enum(AgentTurnState, "agent_turn_state"),
        nullable=False,
        default=AgentTurnState.RUNNING,
        server_default=AgentTurnState.RUNNING.value,
        index=True,
    )
    model: Mapped[str | None] = mapped_column(String(255))
    context_statistics: Mapped[dict[str, Any]] = mapped_column(
        _json(), nullable=False, default=dict, server_default="{}"
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cache_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    source_kind: Mapped[str | None] = mapped_column(String(50))
    source_turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_turns.id", name="fk_agent_turn_source", ondelete="SET NULL"), index=True
    )
    native_turn_id: Mapped[str | None] = mapped_column(String(512), index=True)
    native_session_id: Mapped[str | None] = mapped_column(String(512), index=True)
    rewind_checkpoint_id: Mapped[str | None] = mapped_column(String(512))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentSessionEvent(Base):
    __tablename__ = "agent_session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_agent_event_session_sequence"),
        UniqueConstraint("event_id", name="uq_agent_event_id"),
        UniqueConstraint("idempotency_key", name="uq_agent_event_idempotency_key"),
        CheckConstraint("sequence > 0", name="ck_agent_event_sequence_positive"),
        CheckConstraint("length(trim(event_type)) > 0", name="ck_agent_event_type_nonempty"),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0", name="ck_agent_event_idempotency_nonempty"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", name="fk_agent_event_session", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        _json(), nullable=False, default=dict, server_default="{}"
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_turns.id", name="fk_agent_event_turn", ondelete="SET NULL"), index=True
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(512), index=True)
    subagent_id: Mapped[str | None] = mapped_column(String(512), index=True)
    completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    sidecar_reference: Mapped[str | None] = mapped_column(String(2048))
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class AgentWorkspaceGrant(Base):
    __tablename__ = "agent_workspace_grants"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "knowledge_base_id", name="uq_agent_workspace_grant_session_kb"
        ),
        UniqueConstraint("nonce", name="uq_agent_workspace_grant_nonce"),
        CheckConstraint("expires_at > issued_at", name="ck_agent_workspace_grant_expiry"),
        ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["agent_sessions.id", "agent_sessions.user_id"],
            name="fk_agent_workspace_grant_session_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_agent_workspace_grant_knowledge_base_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    space_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    can_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    can_write: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    can_delete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    tool_categories: Mapped[list[str]] = mapped_column(
        _json(), nullable=False, default=list, server_default="[]"
    )
    vault_root: Mapped[str] = mapped_column(String(2048), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    nonce: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    signature: Mapped[str] = mapped_column(String(512), nullable=False)
    capability_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="1.0", server_default="1.0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentAuditEvent(Base):
    __tablename__ = "agent_audit_events"
    __table_args__ = (
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_audit_duration_nonnegative"
        ),
        CheckConstraint(
            "before_hash IS NULL OR " + _sha256_check("before_hash"),
            name="ck_agent_audit_before_hash",
        ),
        CheckConstraint(
            "after_hash IS NULL OR " + _sha256_check("after_hash"),
            name="ck_agent_audit_after_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_agent_audit_user", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_sessions.id", name="fk_agent_audit_session", ondelete="SET NULL"),
        index=True,
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_turns.id", name="fk_agent_audit_turn", ondelete="SET NULL"), index=True
    )
    change_set_id: Mapped[UUID | None] = mapped_column(index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tool_name: Mapped[str | None] = mapped_column(String(255), index=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(512), index=True)
    command: Mapped[str | None] = mapped_column(Text)
    file_operation: Mapped[str | None] = mapped_column(String(100))
    source_path: Mapped[str | None] = mapped_column(String(2048))
    target_path: Mapped[str | None] = mapped_column(String(2048))
    url: Mapped[str | None] = mapped_column(String(4096))
    mcp_server: Mapped[str | None] = mapped_column(String(255))
    mcp_tool: Mapped[str | None] = mapped_column(String(255))
    skill_name: Mapped[str | None] = mapped_column(String(255))
    subagent_id: Mapped[str | None] = mapped_column(String(512))
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(100), nullable=False, default="completed", server_default="completed"
    )
    result_summary: Mapped[str | None] = mapped_column(Text)
    sidecar_reference: Mapped[str | None] = mapped_column(String(2048))
    arguments_summary: Mapped[dict[str, Any]] = mapped_column(
        _json(), nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class AgentProviderSetting(Base):
    __tablename__ = "agent_provider_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_agent_provider_setting_user_provider"),
        CheckConstraint("context_window > 0", name="ck_agent_provider_context_positive"),
        CheckConstraint("config_version > 0", name="ck_agent_provider_config_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_agent_provider_setting_user", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False)
    available_tools: Mapped[list[str]] = mapped_column(
        _json(), nullable=False, default=list, server_default="[]"
    )
    endpoint_metadata: Mapped[dict[str, Any]] = mapped_column(
        _json(), nullable=False, default=dict, server_default="{}"
    )
    secret_reference: Mapped[str | None] = mapped_column(String(1024))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    health_status: Mapped[str] = mapped_column(
        String(100), nullable=False, default="unknown", server_default="unknown", index=True
    )
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentUsageRecord(Base):
    __tablename__ = "agent_usage_records"
    __table_args__ = tuple(
        CheckConstraint(f"{column} >= 0", name=f"ck_agent_usage_{column}_nonnegative")
        for column in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "compaction_count",
            "tool_call_count",
            "web_request_count",
            "file_read_bytes",
            "command_duration_ms",
            "sidecar_bytes",
            "session_duration_ms",
        )
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", name="fk_agent_usage_session", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_turns.id", name="fk_agent_usage_turn", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cache_read_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cache_write_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    compaction_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    tool_call_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    web_request_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    file_read_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    command_duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    sidecar_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    session_duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    provider_error: Mapped[str | None] = mapped_column(String(255), index=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
