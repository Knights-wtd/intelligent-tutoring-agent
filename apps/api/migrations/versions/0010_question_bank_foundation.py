"""create tenant-aware immutable question bank persistence schema

Revision ID: 0010_question_bank_foundation
Revises: 0009_candidate_graph_foundation
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_question_bank_foundation"
down_revision: str | Sequence[str] | None = "0009_candidate_graph_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sha256_check(column_name: str) -> str:
    stripped = column_name
    for character in "0123456789abcdef":
        stripped = f"replace({stripped}, '{character}', '')"
    return f"length({column_name}) = 64 AND {stripped} = ''"


def upgrade() -> None:
    keywords_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_question_knowledge_base_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "knowledge_base_id", "space_id", name="uq_question_id_kb_space"),
    )
    for column in ("space_id", "knowledge_base_id", "owner_user_id", "created_by_user_id"):
        op.create_index(f"ix_questions_{column}", "questions", [column])

    op.create_table(
        "question_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("question_type", sa.String(length=6), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        sa.Column("expected_keywords", keywords_type, nullable=True),
        sa.Column("source_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("source_chunk_ordinal", sa.Integer(), nullable=False),
        sa.Column("source_pointer", sa.String(length=2048), nullable=False),
        sa.Column("source_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_index_signature", sa.String(length=512), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version_number > 0", name="ck_question_version_number_positive"),
        sa.CheckConstraint("source_chunk_ordinal >= 0", name="ck_question_version_chunk_ordinal"),
        sa.CheckConstraint(
            _sha256_check("source_content_sha256"), name="ck_question_version_source_sha256"
        ),
        sa.CheckConstraint(
            "question_type IN ('choice', 'short', 'open')", name="question_type"
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["question_id", "knowledge_base_id", "space_id"],
            ["questions.id", "questions.knowledge_base_id", "questions.space_id"],
            name="fk_question_version_question_kb_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "knowledge_base_id", "space_id"],
            [
                "document_versions.id",
                "document_versions.knowledge_base_id",
                "document_versions.space_id",
            ],
            name="fk_question_version_document_version_kb_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "knowledge_base_id", "space_id", name="uq_question_version_id_kb_space"
        ),
        sa.UniqueConstraint("question_id", "version_number", name="uq_question_version_number"),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "question_id",
        "document_version_id",
        "question_type",
        "source_chunk_id",
        "source_content_sha256",
        "created_by_user_id",
    ):
        op.create_index(f"ix_question_versions_{column}", "question_versions", [column])

    op.create_table(
        "question_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("question_version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_key_hash", sa.String(length=64), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            _sha256_check("request_key_hash"), name="ck_question_attempt_request_hash"
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["question_version_id", "knowledge_base_id", "space_id"],
            [
                "question_versions.id",
                "question_versions.knowledge_base_id",
                "question_versions.space_id",
            ],
            name="fk_question_attempt_version_kb_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "question_version_id",
            "request_key_hash",
            name="uq_question_attempt_request_key",
        ),
    )
    for column in ("space_id", "knowledge_base_id", "question_version_id", "user_id"):
        op.create_index(f"ix_question_attempts_{column}", "question_attempts", [column])


def downgrade() -> None:
    for column in ("user_id", "question_version_id", "knowledge_base_id", "space_id"):
        op.drop_index(f"ix_question_attempts_{column}", table_name="question_attempts")
    op.drop_table("question_attempts")

    for column in (
        "created_by_user_id",
        "source_content_sha256",
        "source_chunk_id",
        "question_type",
        "document_version_id",
        "question_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(f"ix_question_versions_{column}", table_name="question_versions")
    op.drop_table("question_versions")

    for column in ("created_by_user_id", "owner_user_id", "knowledge_base_id", "space_id"):
        op.drop_index(f"ix_questions_{column}", table_name="questions")
    op.drop_table("questions")
