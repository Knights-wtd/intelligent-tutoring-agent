"""persist reviewable Markdown drafts and explicit wikilinks

Revision ID: 0012_markdown_drafts_links
Revises: 0011_question_attempt_assessment
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_markdown_drafts_links"
down_revision: str | Sequence[str] | None = "0011_question_attempt_assessment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sha256_check(column_name: str) -> str:
    stripped = column_name
    for character in "0123456789abcdef":
        stripped = f"replace({stripped}, '{character}', '')"
    return f"length({column_name}) = 64 AND {stripped} = ''"


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
    source_markers = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "markdown_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("state", sa.String(length=9), server_default="draft", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "state IN ('draft', 'published', 'archived')", name="markdown_note_state"
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_markdown_note_knowledge_base_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id", "knowledge_base_id", "space_id"],
            ["documents.id", "documents.knowledge_base_id", "documents.space_id"],
            name="fk_markdown_note_source_document_kb_space",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_markdown_note_id_space"),
        sa.UniqueConstraint(
            "id", "knowledge_base_id", "space_id", name="uq_markdown_note_id_kb_space"
        ),
        sa.UniqueConstraint(
            "knowledge_base_id", "normalized_title", name="uq_markdown_note_title_in_kb"
        ),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "source_document_id",
        "state",
        "created_by_user_id",
    ):
        op.create_index(f"ix_markdown_notes_{column}", "markdown_notes", [column])

    op.create_table(
        "markdown_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_version_id", sa.Uuid(), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=12), server_default="processing", nullable=False),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_markers", source_markers, server_default="[]", nullable=False),
        sa.Column("generation_provider", sa.String(length=100), nullable=True),
        sa.Column("generation_model", sa.String(length=255), nullable=True),
        sa.Column("generation_request_id", sa.String(length=255), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("revision_number > 0", name="ck_markdown_revision_number_positive"),
        sa.CheckConstraint(
            "content_sha256 IS NULL OR " + _sha256_check("content_sha256"),
            name="ck_markdown_revision_sha256",
        ),
        sa.CheckConstraint(
            "state IN ('processing', 'draft', 'needs_review', 'published', 'failed')",
            name="markdown_revision_state",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["note_id", "knowledge_base_id", "space_id"],
            ["markdown_notes.id", "markdown_notes.knowledge_base_id", "markdown_notes.space_id"],
            name="fk_markdown_revision_note_kb_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_version_id", "source_document_id", "knowledge_base_id", "space_id"],
            [
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.knowledge_base_id",
                "document_versions.space_id",
            ],
            name="fk_markdown_revision_source_version_document_kb_space",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "space_id", name="uq_markdown_revision_id_space"),
        sa.UniqueConstraint(
            "id",
            "note_id",
            "knowledge_base_id",
            "space_id",
            name="uq_markdown_revision_id_note_kb_space",
        ),
        sa.UniqueConstraint("note_id", "revision_number", name="uq_markdown_revision_number"),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "note_id",
        "source_document_id",
        "source_document_version_id",
        "state",
        "content_sha256",
        "created_by_user_id",
    ):
        op.create_index(f"ix_markdown_revisions_{column}", "markdown_revisions", [column])
    op.create_index(
        "uq_published_markdown_revision_per_note",
        "markdown_revisions",
        ["note_id"],
        unique=True,
        postgresql_where=sa.text("state = 'published'"),
        sqlite_where=sa.text("state = 'published'"),
    )

    op.create_table(
        "markdown_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("source_note_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("target_note_id", sa.Uuid(), nullable=True),
        sa.Column("target_title", sa.String(length=500), nullable=False),
        sa.Column("target_heading", sa.String(length=500), nullable=True),
        sa.Column("alias", sa.String(length=500), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("ordinal >= 0", name="ck_markdown_link_ordinal_nonnegative"),
        sa.CheckConstraint("length(target_title) > 0", name="ck_markdown_link_target_title"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_note_id", "knowledge_base_id", "space_id"],
            ["markdown_notes.id", "markdown_notes.knowledge_base_id", "markdown_notes.space_id"],
            name="fk_markdown_link_source_note_kb_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id", "source_note_id", "knowledge_base_id", "space_id"],
            [
                "markdown_revisions.id",
                "markdown_revisions.note_id",
                "markdown_revisions.knowledge_base_id",
                "markdown_revisions.space_id",
            ],
            name="fk_markdown_link_source_revision_note_kb_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_note_id", "knowledge_base_id", "space_id"],
            ["markdown_notes.id", "markdown_notes.knowledge_base_id", "markdown_notes.space_id"],
            name="fk_markdown_link_target_note_kb_space",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_revision_id", "ordinal", name="uq_markdown_link_revision_ordinal"
        ),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "source_note_id",
        "source_revision_id",
        "target_note_id",
        "target_title",
    ):
        op.create_index(f"ix_markdown_links_{column}", "markdown_links", [column])


def downgrade() -> None:
    for column in (
        "target_title",
        "target_note_id",
        "source_revision_id",
        "source_note_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(f"ix_markdown_links_{column}", table_name="markdown_links")
    op.drop_table("markdown_links")
    op.drop_index("uq_published_markdown_revision_per_note", table_name="markdown_revisions")
    for column in (
        "created_by_user_id",
        "content_sha256",
        "state",
        "source_document_version_id",
        "source_document_id",
        "note_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(f"ix_markdown_revisions_{column}", table_name="markdown_revisions")
    op.drop_table("markdown_revisions")
    for column in (
        "created_by_user_id",
        "state",
        "source_document_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(f"ix_markdown_notes_{column}", table_name="markdown_notes")
    op.drop_table("markdown_notes")
