"""persist tenant-scoped tutor conversations

Revision ID: 0015_tutor_conversations
Revises: 0014_candidate_formula_evidence
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_tutor_conversations"
down_revision: str | Sequence[str] | None = "0014_candidate_formula_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    citations_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "tutor_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0", name="ck_tutor_conversation_title_nonempty"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_tutor_conversation_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name="fk_tutor_conversation_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_tutor_conversation_knowledge_base_space",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "user_id",
            "space_id",
            "knowledge_base_id",
            name="uq_tutor_conversation_scope",
        ),
    )
    for column in ("user_id", "space_id", "knowledge_base_id"):
        op.create_index(
            f"ix_tutor_conversations_{column}", "tutor_conversations", [column]
        )

    op.create_table(
        "tutor_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "assistant",
                name="tutor_message_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", citations_type, server_default="[]", nullable=False),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0", name="ck_tutor_message_content_nonempty"
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0", name="ck_tutor_message_prompt_tokens_nonnegative"
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0",
            name="ck_tutor_message_completion_tokens_nonnegative",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("conversation_id", "user_id", "space_id", "knowledge_base_id"):
        op.create_index(f"ix_tutor_messages_{column}", "tutor_messages", [column])


def downgrade() -> None:
    for column in ("knowledge_base_id", "space_id", "user_id", "conversation_id"):
        op.drop_index(f"ix_tutor_messages_{column}", table_name="tutor_messages")
    op.drop_table("tutor_messages")
    for column in ("knowledge_base_id", "space_id", "user_id"):
        op.drop_index(f"ix_tutor_conversations_{column}", table_name="tutor_conversations")
    op.drop_table("tutor_conversations")
