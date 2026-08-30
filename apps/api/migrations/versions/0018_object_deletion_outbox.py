"""create durable knowledge object deletion outbox

Revision ID: 0018_object_deletion_outbox
Revises: 0017_agent_event_timestamp
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_object_deletion_outbox"
down_revision: str | Sequence[str] | None = "0017_agent_event_timestamp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_object_deletion_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("state", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_object_deletion_attempt_nonnegative"),
        sa.CheckConstraint(
            "state IN ('pending', 'running', 'retry_wait', 'completed')",
            name="object_deletion_state",
        ),
        sa.CheckConstraint(
            "(state = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_object_deletion_lease_matches_state",
        ),
        sa.CheckConstraint(
            "(state = 'completed' AND completed_at IS NOT NULL) "
            "OR (state <> 'completed' AND completed_at IS NULL)",
            name="ck_object_deletion_completed_at_matches_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_knowledge_object_deletion_key"),
    )
    op.create_index(
        op.f("ix_knowledge_object_deletion_outbox_available_at"),
        "knowledge_object_deletion_outbox",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_object_deletion_outbox_lease_expires_at"),
        "knowledge_object_deletion_outbox",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_object_deletion_outbox_lease_owner"),
        "knowledge_object_deletion_outbox",
        ["lease_owner"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_object_deletion_outbox_state"),
        "knowledge_object_deletion_outbox",
        ["state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_knowledge_object_deletion_outbox_state"),
        table_name="knowledge_object_deletion_outbox",
    )
    op.drop_index(
        op.f("ix_knowledge_object_deletion_outbox_lease_owner"),
        table_name="knowledge_object_deletion_outbox",
    )
    op.drop_index(
        op.f("ix_knowledge_object_deletion_outbox_lease_expires_at"),
        table_name="knowledge_object_deletion_outbox",
    )
    op.drop_index(
        op.f("ix_knowledge_object_deletion_outbox_available_at"),
        table_name="knowledge_object_deletion_outbox",
    )
    op.drop_table("knowledge_object_deletion_outbox")
