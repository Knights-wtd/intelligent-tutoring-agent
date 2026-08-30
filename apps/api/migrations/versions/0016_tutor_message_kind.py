"""tag tutor messages with answer/clarify kind

Revision ID: 0016_tutor_message_kind
Revises: 0015_tutor_conversations
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_tutor_message_kind"
down_revision: str | Sequence[str] | None = "0015_tutor_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tutor_messages",
        sa.Column(
            "kind",
            sa.Enum(
                "answer",
                "clarify",
                name="tutor_message_kind",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="answer",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tutor_messages", "kind")
