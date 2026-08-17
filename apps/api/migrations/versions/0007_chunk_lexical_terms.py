"""persist normalized lexical terms on immutable chunks

Revision ID: 0007_chunk_lexical_terms
Revises: 0006_versioned_knowledge
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_chunk_lexical_terms"
down_revision: str | Sequence[str] | None = "0006_versioned_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    lexical_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    with op.batch_alter_table("chunks") as batch_op:
        batch_op.add_column(
            sa.Column("lexical_terms", lexical_type, nullable=False, server_default="[]")
        )


def downgrade() -> None:
    with op.batch_alter_table("chunks") as batch_op:
        batch_op.drop_column("lexical_terms")
