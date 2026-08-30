"""persist runtime event timestamps

Revision ID: 0017_agent_event_timestamp
Revises: 0016_agent_workspace
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_agent_event_timestamp"
down_revision: str | Sequence[str] | None = "0016_agent_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_session_events",
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_agent_session_events_timestamp"),
        "agent_session_events",
        ["timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_session_events_timestamp"), table_name="agent_session_events")
    op.drop_column("agent_session_events", "timestamp")
