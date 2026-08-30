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


def _optional_sha256_check(column_name: str) -> str:
    return f"{column_name} IS NULL OR " + _sha256_check(column_name)


class VaultFileKind(StrEnum):
    MARKDOWN = "markdown"
    ATTACHMENT = "attachment"
    SIDECAR = "sidecar"
    OTHER = "other"


class VaultSyncState(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    CONFLICT = "conflict"
    FAILED = "failed"
    TOMBSTONED = "tombstoned"


class VaultChangeSource(StrEnum):
    AGENT = "agent"
    SHELL = "shell"
    GIT = "git"
    EXTERNAL_EDITOR = "external_editor"
    API = "api"
    INITIAL_MIGRATION = "initial_migration"
    CONFLICT_BACKUP = "conflict_backup"


class VaultChangeSetState(StrEnum):
    PENDING = "pending"
    APPLYING = "applying"
    COMMITTED = "committed"
    CONFLICTED = "conflicted"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class VaultChangeOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    MOVE = "move"
    RENAME = "rename"
    DELETE = "delete"


class SemanticIndexPlanState(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    VALIDATED = "validated"
    STALE = "stale"
    APPLIED = "applied"
    FAILED = "failed"


class VaultChangeSet(Base):
    __tablename__ = "vault_change_sets"
    __table_args__ = (
        UniqueConstraint("id", "knowledge_base_id", "space_id", name="uq_vault_change_set_scope"),
        CheckConstraint("retry_count >= 0", name="ck_vault_change_set_retry_nonnegative"),
        CheckConstraint(
            _optional_sha256_check("before_snapshot_hash"),
            name="ck_vault_change_set_before_snapshot_hash",
        ),
        CheckConstraint(
            _optional_sha256_check("after_snapshot_hash"),
            name="ck_vault_change_set_after_snapshot_hash",
        ),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_vault_change_set_knowledge_base_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", name="fk_vault_change_set_space", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    source: Mapped[VaultChangeSource] = mapped_column(
        _enum(VaultChangeSource, "vault_change_source"), nullable=False, index=True
    )
    state: Mapped[VaultChangeSetState] = mapped_column(
        _enum(VaultChangeSetState, "vault_change_set_state"),
        nullable=False,
        default=VaultChangeSetState.PENDING,
        server_default=VaultChangeSetState.PENDING.value,
        index=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_sessions.id", name="fk_vault_change_set_session", ondelete="SET NULL"),
        index=True,
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_turns.id", name="fk_vault_change_set_turn", ondelete="SET NULL"),
        index=True,
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(512), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    before_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    after_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_code: Mapped[str | None] = mapped_column(String(100), index=True)
    failure_message: Mapped[str | None] = mapped_column(Text)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conflicted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class VaultFile(Base):
    __tablename__ = "vault_files"
    __table_args__ = (
        UniqueConstraint("id", "knowledge_base_id", "space_id", name="uq_vault_file_scope"),
        UniqueConstraint(
            "knowledge_base_id", "relative_path", name="uq_vault_file_path_in_knowledge_base"
        ),
        CheckConstraint("length(relative_path) > 0", name="ck_vault_file_path_nonempty"),
        CheckConstraint("relative_path = trim(relative_path)", name="ck_vault_file_path_trimmed"),
        CheckConstraint("substr(relative_path, 1, 1) <> '/'", name="ck_vault_file_path_relative"),
        CheckConstraint(
            "relative_path NOT LIKE '%\\%' ESCAPE '!'",
            name="ck_vault_file_path_posix",
        ),
        CheckConstraint(
            "relative_path <> '..' AND relative_path NOT LIKE '../%' "
            "AND relative_path NOT LIKE '%/../%' AND relative_path NOT LIKE '%/..'",
            name="ck_vault_file_path_no_parent",
        ),
        CheckConstraint(
            "relative_path <> '.' AND relative_path NOT LIKE './%' "
            "AND relative_path NOT LIKE '%/./%' AND relative_path NOT LIKE '%/.'",
            name="ck_vault_file_path_normalized",
        ),
        CheckConstraint(_sha256_check("content_hash"), name="ck_vault_file_content_hash"),
        CheckConstraint("size_bytes >= 0", name="ck_vault_file_size_nonnegative"),
        CheckConstraint("revision >= 0", name="ck_vault_file_revision_nonnegative"),
        CheckConstraint(
            "(is_tombstoned = false AND tombstoned_at IS NULL) OR is_tombstoned = true",
            name="ck_vault_file_tombstone_timestamp",
        ),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_vault_file_knowledge_base_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", name="fk_vault_file_space", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    relative_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_kind: Mapped[VaultFileKind] = mapped_column(
        _enum(VaultFileKind, "vault_file_kind"), nullable=False, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    filesystem_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_identity: Mapped[str | None] = mapped_column(String(1024), index=True)
    sync_state: Mapped[VaultSyncState] = mapped_column(
        _enum(VaultSyncState, "vault_sync_state"),
        nullable=False,
        default=VaultSyncState.PENDING,
        server_default=VaultSyncState.PENDING.value,
        index=True,
    )
    last_change_set_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "vault_change_sets.id", name="fk_vault_file_last_change_set", ondelete="SET NULL"
        ),
        index=True,
    )
    is_tombstoned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_index_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("index_versions.id", name="fk_vault_file_last_index", ondelete="SET NULL"),
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class VaultChangeEntry(Base):
    __tablename__ = "vault_change_entries"
    __table_args__ = (
        UniqueConstraint("change_set_id", "ordinal", name="uq_vault_change_entry_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_vault_change_entry_ordinal_nonnegative"),
        CheckConstraint(
            _optional_sha256_check("before_hash"), name="ck_vault_change_entry_before_hash"
        ),
        CheckConstraint(
            _optional_sha256_check("after_hash"), name="ck_vault_change_entry_after_hash"
        ),
        CheckConstraint(
            "size_delta_bytes IS NULL OR size_delta_bytes >= -9223372036854775807",
            name="ck_vault_change_entry_size_delta",
        ),
        ForeignKeyConstraint(
            ["change_set_id", "knowledge_base_id", "space_id"],
            [
                "vault_change_sets.id",
                "vault_change_sets.knowledge_base_id",
                "vault_change_sets.space_id",
            ],
            name="fk_vault_change_entry_change_set_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["vault_file_id", "knowledge_base_id", "space_id"],
            ["vault_files.id", "vault_files.knowledge_base_id", "vault_files.space_id"],
            name="fk_vault_change_entry_file_scope",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    change_set_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    vault_file_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    space_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[VaultChangeOperation] = mapped_column(
        _enum(VaultChangeOperation, "vault_change_operation"), nullable=False, index=True
    )
    before_path: Mapped[str | None] = mapped_column(String(2048))
    after_path: Mapped[str | None] = mapped_column(String(2048))
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    size_delta_bytes: Mapped[int | None] = mapped_column(Integer)
    audit_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "agent_audit_events.id", name="fk_vault_change_entry_audit", ondelete="SET NULL"
        ),
        index=True,
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        _json(), nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VaultSyncCursor(Base):
    __tablename__ = "vault_sync_cursors"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", name="uq_vault_sync_cursor_knowledge_base"),
        CheckConstraint("pending_count >= 0", name="ck_vault_sync_cursor_pending_nonnegative"),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_vault_sync_cursor_knowledge_base_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", name="fk_vault_sync_cursor_space", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    watcher_cursor: Mapped[str | None] = mapped_column(String(2048))
    database_cursor: Mapped[str | None] = mapped_column(String(2048))
    index_cursor: Mapped[str | None] = mapped_column(String(2048))
    pending_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    requires_full_scan: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SemanticIndexPlan(Base):
    __tablename__ = "semantic_index_plans"
    __table_args__ = (
        UniqueConstraint(
            "vault_file_id",
            "input_hash",
            "schema_version",
            "prompt_hash",
            name="uq_semantic_index_plan_input_contract",
        ),
        CheckConstraint(_sha256_check("input_hash"), name="ck_semantic_index_plan_input_hash"),
        CheckConstraint(_sha256_check("prompt_hash"), name="ck_semantic_index_plan_prompt_hash"),
        CheckConstraint("retry_count >= 0", name="ck_semantic_index_plan_retry_nonnegative"),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_semantic_index_plan_knowledge_base_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["vault_file_id", "knowledge_base_id", "space_id"],
            ["vault_files.id", "vault_files.knowledge_base_id", "vault_files.space_id"],
            name="fk_semantic_index_plan_file_scope",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    vault_file_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    change_set_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "vault_change_sets.id", name="fk_semantic_index_plan_change_set", ondelete="SET NULL"
        ),
        index=True,
    )
    index_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("index_versions.id", name="fk_semantic_index_plan_index", ondelete="SET NULL"),
        index=True,
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(_json())
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[SemanticIndexPlanState] = mapped_column(
        _enum(SemanticIndexPlanState, "semantic_index_plan_state"),
        nullable=False,
        default=SemanticIndexPlanState.PENDING,
        server_default=SemanticIndexPlanState.PENDING.value,
        index=True,
    )
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(
        _json(), nullable=False, default=list, server_default="[]"
    )
    raw_sidecar_reference: Mapped[str | None] = mapped_column(String(2048))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_code: Mapped[str | None] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
