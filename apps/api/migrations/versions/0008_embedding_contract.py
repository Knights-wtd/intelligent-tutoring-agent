"""persist complete embedding contract signatures

Revision ID: 0008_embedding_contract
Revises: 0007_chunk_lexical_terms
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_embedding_contract"
down_revision: str | Sequence[str] | None = "0007_chunk_lexical_terms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("index_versions") as batch_op:
        batch_op.add_column(
            sa.Column("embedding_contract_signature", sa.String(length=512), nullable=True)
        )

    op.execute(
        sa.text(
            "UPDATE index_versions SET embedding_contract_signature = "
            "'tutor:embedding:legacy:v1:' || embedding_backend || ':' || "
            "embedding_model || ':' || CAST(embedding_dimension AS VARCHAR)"
        )
    )

    with op.batch_alter_table("index_versions") as batch_op:
        batch_op.alter_column(
            "embedding_contract_signature",
            existing_type=sa.String(length=512),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("index_versions") as batch_op:
        batch_op.drop_column("embedding_contract_signature")
