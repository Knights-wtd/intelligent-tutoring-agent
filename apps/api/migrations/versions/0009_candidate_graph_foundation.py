"""persist review-only knowledge candidates

Revision ID: 0009_candidate_graph_foundation
Revises: 0008_embedding_contract
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_candidate_graph_foundation"
down_revision: str | Sequence[str] | None = "0008_embedding_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    source_pointers = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "knowledge_candidate_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("generation_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=12), server_default="processing", nullable=False),
        sa.Column("generation_provider", sa.String(length=100), nullable=True),
        sa.Column("generation_model", sa.String(length=255), nullable=True),
        sa.Column("generation_request_id", sa.String(length=255), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("generation_number > 0", name="ck_candidate_batch_generation_positive"),
        sa.CheckConstraint(
            "state IN ('processing', 'needs_review', 'confirmed', 'rejected', 'failed')",
            name="candidate_batch_state",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_candidate_batch_knowledge_base_space",
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
            name="fk_candidate_batch_source_version_document_kb_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "knowledge_base_id", "space_id", name="uq_candidate_batch_id_kb_space"
        ),
        sa.UniqueConstraint(
            "document_version_id",
            "generation_number",
            name="uq_candidate_batch_version_generation",
        ),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "document_id",
        "document_version_id",
        "state",
        "created_by_user_id",
    ):
        op.create_index(
            f"ix_knowledge_candidate_batches_{column}",
            "knowledge_candidate_batches",
            [column],
        )

    op.create_table(
        "knowledge_candidate_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("candidate_key", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("parent_key", sa.String(length=200), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("source_pointers", source_pointers, nullable=False),
        sa.Column("review_state", sa.String(length=8), server_default="pending", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("ordinal >= 0", name="ck_candidate_note_ordinal_nonnegative"),
        sa.CheckConstraint("length(candidate_key) > 0", name="ck_candidate_note_key_nonempty"),
        sa.CheckConstraint(
            "kind IN ('chapter', 'section', 'subsection', 'concept', 'property', 'formula', "
            "'method', 'example')",
            name="candidate_note_kind",
        ),
        sa.CheckConstraint(
            "review_state IN ('pending', 'accepted', 'rejected')",
            name="candidate_note_review_state",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["batch_id", "knowledge_base_id", "space_id"],
            [
                "knowledge_candidate_batches.id",
                "knowledge_candidate_batches.knowledge_base_id",
                "knowledge_candidate_batches.space_id",
            ],
            name="fk_candidate_note_batch_kb_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "parent_key"],
            ["knowledge_candidate_notes.batch_id", "knowledge_candidate_notes.candidate_key"],
            name="fk_candidate_note_parent_in_batch",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "ordinal", name="uq_candidate_note_batch_ordinal"),
        sa.UniqueConstraint("batch_id", "candidate_key", name="uq_candidate_note_batch_key"),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "batch_id",
        "normalized_title",
        "kind",
        "review_state",
    ):
        op.create_index(
            f"ix_knowledge_candidate_notes_{column}", "knowledge_candidate_notes", [column]
        )

    op.create_table(
        "knowledge_candidate_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=9), nullable=False),
        sa.Column("relation", sa.String(length=100), nullable=False),
        sa.Column("source_key", sa.String(length=200), nullable=False),
        sa.Column("target_key", sa.String(length=200), nullable=False),
        sa.Column("source_pointer", sa.String(length=1024), nullable=False),
        sa.Column("occurrence", sa.String(length=500), nullable=True),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("review_state", sa.String(length=8), server_default="pending", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("ordinal >= 0", name="ck_candidate_link_ordinal_nonnegative"),
        sa.CheckConstraint("kind IN ('structure', 'term')", name="candidate_link_kind"),
        sa.CheckConstraint(
            "kind <> 'term' OR occurrence IS NOT NULL",
            name="ck_candidate_term_link_occurrence",
        ),
        sa.CheckConstraint(
            "review_state IN ('pending', 'accepted', 'rejected')",
            name="candidate_link_review_state",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["batch_id", "knowledge_base_id", "space_id"],
            [
                "knowledge_candidate_batches.id",
                "knowledge_candidate_batches.knowledge_base_id",
                "knowledge_candidate_batches.space_id",
            ],
            name="fk_candidate_link_batch_kb_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "source_key"],
            ["knowledge_candidate_notes.batch_id", "knowledge_candidate_notes.candidate_key"],
            name="fk_candidate_link_source_in_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "target_key"],
            ["knowledge_candidate_notes.batch_id", "knowledge_candidate_notes.candidate_key"],
            name="fk_candidate_link_target_in_batch",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "ordinal", name="uq_candidate_link_batch_ordinal"),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "batch_id",
        "kind",
        "source_key",
        "target_key",
        "review_state",
    ):
        op.create_index(
            f"ix_knowledge_candidate_links_{column}", "knowledge_candidate_links", [column]
        )


def downgrade() -> None:
    for column in (
        "review_state",
        "target_key",
        "source_key",
        "kind",
        "batch_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(
            f"ix_knowledge_candidate_links_{column}", table_name="knowledge_candidate_links"
        )
    op.drop_table("knowledge_candidate_links")
    for column in (
        "review_state",
        "kind",
        "normalized_title",
        "batch_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(
            f"ix_knowledge_candidate_notes_{column}", table_name="knowledge_candidate_notes"
        )
    op.drop_table("knowledge_candidate_notes")
    for column in (
        "created_by_user_id",
        "state",
        "document_version_id",
        "document_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(
            f"ix_knowledge_candidate_batches_{column}", table_name="knowledge_candidate_batches"
        )
    op.drop_table("knowledge_candidate_batches")
