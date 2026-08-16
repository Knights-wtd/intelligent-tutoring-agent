"""create versioned knowledge and immutable index schema

Revision ID: 0006_versioned_knowledge
Revises: 0005_reversal_audit_group
Create Date: 2026-08-16
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision: str = "0006_versioned_knowledge"
down_revision: str | Sequence[str] | None = "0005_reversal_audit_group"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _PostgreSQLVector(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "VECTOR"


def _sha256_check(column_name: str) -> str:
    stripped = column_name
    for character in "0123456789abcdef":
        stripped = f"replace({stripped}, '{character}', '')"
    return f"length({column_name}) = 64 AND {stripped} = ''"


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    embedding_type: sa.types.TypeEngine = (
        _PostgreSQLVector() if dialect_name == "postgresql" else sa.JSON()
    )
    checkpoint_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    embedding_dimension_check = (
        "vector_dims(embedding) = embedding_dimension"
        if dialect_name == "postgresql"
        else "json_valid(embedding) AND json_type(embedding) = 'array' "
        "AND json_array_length(embedding) = embedding_dimension"
    )
    embedding_dimension_constraint_name = (
        "ck_chunk_embedding_dimension_postgresql"
        if dialect_name == "postgresql"
        else "ck_chunk_embedding_dimension_sqlite"
    )
    checkpoint_object_check = (
        "jsonb_typeof(checkpoint) = 'object'"
        if dialect_name == "postgresql"
        else "json_type(checkpoint) = 'object'"
    )
    checkpoint_object_constraint_name = (
        "ck_ingestion_checkpoint_object_postgresql"
        if dialect_name == "postgresql"
        else "ck_ingestion_checkpoint_object_sqlite"
    )

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=8), server_default="active", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            _enum_check("state", ("active", "archived")), name="knowledge_base_state"
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_knowledge_base_id_space"),
    )
    op.create_index("ix_knowledge_bases_space_id", "knowledge_bases", ["space_id"])
    op.create_index("ix_knowledge_bases_owner_user_id", "knowledge_bases", ["owner_user_id"])
    op.create_index(
        "ix_knowledge_bases_created_by_user_id", "knowledge_bases", ["created_by_user_id"]
    )
    op.create_index("ix_knowledge_bases_state", "knowledge_bases", ["state"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_key", sa.String(length=1024), nullable=False),
        sa.Column("state", sa.String(length=8), server_default="active", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(_enum_check("state", ("active", "archived")), name="document_state"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_document_knowledge_base_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_document_id_space"),
        sa.UniqueConstraint("id", "knowledge_base_id", "space_id", name="uq_document_id_kb_space"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "source_kind",
            "source_key",
            name="uq_document_source_in_knowledge_base",
        ),
    )
    for column in ("space_id", "knowledge_base_id", "owner_user_id", "created_by_user_id", "state"):
        op.create_index(f"ix_documents_{column}", "documents", [column])

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=8), server_default="uploaded", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("version_number > 0", name="ck_document_version_number_positive"),
        sa.CheckConstraint(_sha256_check("content_sha256"), name="ck_document_version_sha256"),
        sa.CheckConstraint(
            _enum_check("state", ("uploaded", "parsing", "ready", "failed")),
            name="document_version_state",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["document_id", "knowledge_base_id", "space_id"],
            ["documents.id", "documents.knowledge_base_id", "documents.space_id"],
            name="fk_document_version_document_kb_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_document_version_id_space"),
        sa.UniqueConstraint(
            "id", "knowledge_base_id", "space_id", name="uq_document_version_id_kb_space"
        ),
        sa.UniqueConstraint(
            "id",
            "document_id",
            "knowledge_base_id",
            "space_id",
            name="uq_document_version_id_document_kb_space",
        ),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),
        sa.UniqueConstraint("document_id", "content_sha256", name="uq_document_content_hash"),
        sa.UniqueConstraint("object_key", name="uq_document_version_object_key"),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "document_id",
        "content_sha256",
        "state",
        "created_by_user_id",
    ):
        op.create_index(f"ix_document_versions_{column}", "document_versions", [column])

    op.create_table(
        "pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("source_pointer", sa.String(length=1024), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("text_object_key", sa.String(length=1024), nullable=True),
        sa.Column("image_object_key", sa.String(length=1024), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("page_number > 0", name="ck_page_number_positive"),
        sa.CheckConstraint(_sha256_check("content_sha256"), name="ck_page_sha256"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id", "space_id"],
            ["document_versions.id", "document_versions.space_id"],
            name="fk_page_document_version_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_page_id_space"),
        sa.UniqueConstraint(
            "id", "document_version_id", "space_id", name="uq_page_id_version_space"
        ),
        sa.UniqueConstraint("document_version_id", "page_number", name="uq_page_number"),
        sa.UniqueConstraint("document_version_id", "source_pointer", name="uq_page_source_pointer"),
    )
    for column in ("space_id", "document_version_id", "content_sha256"):
        op.create_index(f"ix_pages_{column}", "pages", [column])

    op.create_table(
        "blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=13), nullable=False),
        sa.Column("source_pointer", sa.String(length=1024), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("bounding_box", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("ordinal >= 0", name="ck_block_ordinal_nonnegative"),
        sa.CheckConstraint(_sha256_check("content_sha256"), name="ck_block_sha256"),
        sa.CheckConstraint(
            _enum_check(
                "kind",
                (
                    "title",
                    "paragraph",
                    "formula",
                    "table",
                    "image_caption",
                    "example",
                    "question",
                    "answer",
                ),
            ),
            name="block_kind",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["page_id", "space_id"],
            ["pages.id", "pages.space_id"],
            name="fk_block_page_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_block_id_space"),
        sa.UniqueConstraint("id", "page_id", "space_id", name="uq_block_id_page_space"),
        sa.UniqueConstraint("page_id", "ordinal", name="uq_block_ordinal"),
        sa.UniqueConstraint("page_id", "source_pointer", name="uq_block_source_pointer"),
    )
    for column in ("space_id", "page_id", "content_sha256"):
        op.create_index(f"ix_blocks_{column}", "blocks", [column])

    op.create_table(
        "index_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=8), server_default="building", nullable=False),
        sa.Column("parser_signature", sa.String(length=255), nullable=False),
        sa.Column("ocr_signature", sa.String(length=255), nullable=False),
        sa.Column("chunking_signature", sa.String(length=255), nullable=False),
        sa.Column("embedding_backend", sa.String(length=100), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("index_signature", sa.String(length=512), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("version_number > 0", name="ck_index_version_number_positive"),
        sa.CheckConstraint(
            "embedding_dimension BETWEEN 8 AND 4096", name="ck_index_embedding_dimension_range"
        ),
        sa.CheckConstraint(
            _enum_check("state", ("building", "ready", "active", "failed", "retired")),
            name="index_version_state",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_index_knowledge_base_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_index_version_id_space"),
        sa.UniqueConstraint(
            "id", "knowledge_base_id", "space_id", name="uq_index_version_id_kb_space"
        ),
        sa.UniqueConstraint(
            "id",
            "knowledge_base_id",
            "space_id",
            "embedding_dimension",
            "index_signature",
            name="uq_index_embedding_contract",
        ),
        sa.UniqueConstraint("knowledge_base_id", "version_number", name="uq_index_version_number"),
        sa.UniqueConstraint("knowledge_base_id", "index_signature", name="uq_index_signature"),
    )
    for column in ("space_id", "knowledge_base_id", "state", "created_by_user_id"):
        op.create_index(f"ix_index_versions_{column}", "index_versions", [column])
    op.create_index(
        "uq_active_index_per_knowledge_base",
        "index_versions",
        ["knowledge_base_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
        sqlite_where=sa.text("state = 'active'"),
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("index_version_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=True),
        sa.Column("block_id", sa.Uuid(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_pointer", sa.String(length=1024), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("index_signature", sa.String(length=512), nullable=False),
        sa.Column("embedding", embedding_type, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("ordinal >= 0", name="ck_chunk_ordinal_nonnegative"),
        sa.CheckConstraint(_sha256_check("content_sha256"), name="ck_chunk_sha256"),
        sa.CheckConstraint(
            "block_id IS NULL OR page_id IS NOT NULL", name="ck_chunk_block_requires_page"
        ),
        sa.CheckConstraint(
            embedding_dimension_check, name=embedding_dimension_constraint_name
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            [
                "index_version_id",
                "knowledge_base_id",
                "space_id",
                "embedding_dimension",
                "index_signature",
            ],
            [
                "index_versions.id",
                "index_versions.knowledge_base_id",
                "index_versions.space_id",
                "index_versions.embedding_dimension",
                "index_versions.index_signature",
            ],
            name="fk_chunk_index_embedding_contract",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "knowledge_base_id", "space_id"],
            [
                "document_versions.id",
                "document_versions.knowledge_base_id",
                "document_versions.space_id",
            ],
            name="fk_chunk_document_version_kb_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "document_version_id", "space_id"],
            ["pages.id", "pages.document_version_id", "pages.space_id"],
            name="fk_chunk_page_version_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["block_id", "page_id", "space_id"],
            ["blocks.id", "blocks.page_id", "blocks.space_id"],
            name="fk_chunk_block_page_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_chunk_id_space"),
        sa.UniqueConstraint("index_version_id", "ordinal", name="uq_chunk_ordinal"),
        sa.UniqueConstraint("index_version_id", "source_pointer", name="uq_chunk_source_pointer"),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "index_version_id",
        "document_version_id",
        "page_id",
        "block_id",
        "content_sha256",
    ):
        op.create_index(f"ix_chunks_{column}", "chunks", [column])

    if dialect_name == "sqlite":
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_chunks_validate_embedding_insert
                BEFORE INSERT ON chunks
                WHEN EXISTS (
                    SELECT 1 FROM json_each(NEW.embedding)
                    WHERE type NOT IN ('integer', 'real')
                       OR value != value
                       OR abs(CAST(value AS REAL)) > 1.7976931348623157e308
                )
                BEGIN
                    SELECT RAISE(ABORT, 'invalid embedding element');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_chunks_validate_embedding_update
                BEFORE UPDATE OF embedding, embedding_dimension ON chunks
                WHEN EXISTS (
                    SELECT 1 FROM json_each(NEW.embedding)
                    WHERE type NOT IN ('integer', 'real')
                       OR value != value
                       OR abs(CAST(value AS REAL)) > 1.7976931348623157e308
                )
                BEGIN
                    SELECT RAISE(ABORT, 'invalid embedding element');
                END
                """
            )
        )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("page_id", sa.Uuid(), nullable=True),
        sa.Column("index_version_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=14), nullable=False),
        sa.Column("state", sa.String(length=10), server_default="queued", nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint", checkpoint_type, nullable=False),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_detail", sa.String(length=1000), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ingestion_attempt_nonnegative"),
        sa.CheckConstraint("max_attempts > 0", name="ck_ingestion_max_attempts_positive"),
        sa.CheckConstraint(
            "attempt_count <= max_attempts", name="ck_ingestion_attempt_within_limit"
        ),
        sa.CheckConstraint(
            "state <> 'retry_wait' OR attempt_count > 0",
            name="ck_ingestion_retry_wait_has_attempt",
        ),
        sa.CheckConstraint(
            "(state = 'running' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'running' AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_ingestion_lease_matches_state",
        ),
        sa.CheckConstraint(
            "(state IN ('completed', 'failed', 'cancelled') "
            "AND completed_at IS NOT NULL) OR "
            "(state NOT IN ('completed', 'failed', 'cancelled') "
            "AND completed_at IS NULL)",
            name="ck_ingestion_completed_at_matches_state",
        ),
        sa.CheckConstraint(
            "(state = 'queued' AND started_at IS NULL) OR "
            "(state IN ('running', 'retry_wait', 'completed', 'failed') "
            "AND started_at IS NOT NULL) OR state = 'cancelled'",
            name="ck_ingestion_started_at_matches_state",
        ),
        sa.CheckConstraint(
            "(kind = 'parse_document' AND document_id IS NOT NULL "
            "AND document_version_id IS NOT NULL AND page_id IS NULL "
            "AND index_version_id IS NULL) OR "
            "(kind = 'ocr_page' AND document_id IS NOT NULL "
            "AND document_version_id IS NOT NULL AND page_id IS NOT NULL "
            "AND index_version_id IS NULL) OR "
            "(kind = 'build_index' AND document_id IS NULL "
            "AND document_version_id IS NULL AND page_id IS NULL "
            "AND index_version_id IS NOT NULL)",
            name="ck_ingestion_target_matches_kind",
        ),
        sa.CheckConstraint(
            checkpoint_object_check,
            name=checkpoint_object_constraint_name,
        ),
        sa.CheckConstraint(
            _enum_check("kind", ("parse_document", "ocr_page", "build_index")),
            name="ingestion_job_kind",
        ),
        sa.CheckConstraint(
            _enum_check(
                "state", ("queued", "running", "retry_wait", "completed", "failed", "cancelled")
            ),
            name="ingestion_job_state",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_ingestion_knowledge_base_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "knowledge_base_id", "space_id"],
            ["documents.id", "documents.knowledge_base_id", "documents.space_id"],
            name="fk_ingestion_document_kb_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "document_id", "knowledge_base_id", "space_id"],
            [
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.knowledge_base_id",
                "document_versions.space_id",
            ],
            name="fk_ingestion_version_document_kb_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "document_version_id", "space_id"],
            ["pages.id", "pages.document_version_id", "pages.space_id"],
            name="fk_ingestion_page_version_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["index_version_id", "knowledge_base_id", "space_id"],
            [
                "index_versions.id",
                "index_versions.knowledge_base_id",
                "index_versions.space_id",
            ],
            name="fk_ingestion_index_kb_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_ingestion_job_id_space"),
        sa.UniqueConstraint(
            "knowledge_base_id", "idempotency_key", name="uq_ingestion_job_idempotency"
        ),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "document_id",
        "document_version_id",
        "page_id",
        "index_version_id",
        "kind",
        "state",
        "available_at",
        "lease_owner",
        "lease_expires_at",
        "created_by_user_id",
    ):
        op.create_index(f"ix_ingestion_jobs_{column}", "ingestion_jobs", [column])


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_chunks_validate_embedding_update"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_chunks_validate_embedding_insert"))
    for column in (
        "created_by_user_id",
        "lease_expires_at",
        "lease_owner",
        "available_at",
        "state",
        "kind",
        "index_version_id",
        "page_id",
        "document_version_id",
        "document_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(f"ix_ingestion_jobs_{column}", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")

    for column in (
        "content_sha256",
        "block_id",
        "page_id",
        "document_version_id",
        "index_version_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(f"ix_chunks_{column}", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("uq_active_index_per_knowledge_base", table_name="index_versions")
    for column in ("created_by_user_id", "state", "knowledge_base_id", "space_id"):
        op.drop_index(f"ix_index_versions_{column}", table_name="index_versions")
    op.drop_table("index_versions")

    for column in ("content_sha256", "page_id", "space_id"):
        op.drop_index(f"ix_blocks_{column}", table_name="blocks")
    op.drop_table("blocks")

    for column in ("content_sha256", "document_version_id", "space_id"):
        op.drop_index(f"ix_pages_{column}", table_name="pages")
    op.drop_table("pages")

    for column in (
        "created_by_user_id",
        "state",
        "content_sha256",
        "document_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(f"ix_document_versions_{column}", table_name="document_versions")
    op.drop_table("document_versions")

    for column in ("state", "created_by_user_id", "owner_user_id", "knowledge_base_id", "space_id"):
        op.drop_index(f"ix_documents_{column}", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_knowledge_bases_state", table_name="knowledge_bases")
    op.drop_index("ix_knowledge_bases_created_by_user_id", table_name="knowledge_bases")
    op.drop_index("ix_knowledge_bases_owner_user_id", table_name="knowledge_bases")
    op.drop_index("ix_knowledge_bases_space_id", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
