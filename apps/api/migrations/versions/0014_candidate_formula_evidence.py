"""persist candidate formula verification and external evidence

Revision ID: 0014_candidate_formula_evidence
Revises: 0013_markdown_job_kinds
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_candidate_formula_evidence"
down_revision: str | Sequence[str] | None = "0013_markdown_job_kinds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    formula_verification = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    external_sources = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column(
        "knowledge_candidate_notes",
        sa.Column("formula_verification", formula_verification, nullable=True),
    )
    op.add_column(
        "knowledge_candidate_notes",
        sa.Column(
            "external_sources",
            external_sources,
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_candidate_notes", "external_sources")
    op.drop_column("knowledge_candidate_notes", "formula_verification")
