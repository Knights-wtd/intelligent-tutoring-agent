"""record the administrator and reason for recharge reversals

Revision ID: 0004_recharge_reversal_audit
Revises: 0003_bind_reservations_to_provider
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_recharge_reversal_audit"
down_revision: str | Sequence[str] | None = "0003_bind_reservations_to_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recharge_records") as batch_op:
        batch_op.add_column(sa.Column("reversed_by_user_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("reversal_reason", sa.String(length=1000), nullable=True))
        batch_op.create_foreign_key(
            "fk_recharge_record_reversed_by_user",
            "users",
            ["reversed_by_user_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_recharge_records_reversed_by_user_id", ["reversed_by_user_id"]
        )
        batch_op.create_check_constraint(
            "ck_recharge_record_reversal_audit_complete",
            "(reversal_ledger_entry_id IS NULL AND reversed_at IS NULL AND "
            "reversed_by_user_id IS NULL AND reversal_reason IS NULL) OR "
            "(reversal_ledger_entry_id IS NOT NULL AND reversed_at IS NOT NULL AND "
            "reversed_by_user_id IS NOT NULL AND reversal_reason IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("recharge_records") as batch_op:
        batch_op.drop_constraint("ck_recharge_record_reversal_audit_complete", type_="check")
        batch_op.drop_index("ix_recharge_records_reversed_by_user_id")
        batch_op.drop_constraint("fk_recharge_record_reversed_by_user", type_="foreignkey")
        batch_op.drop_column("reversal_reason")
        batch_op.drop_column("reversed_by_user_id")
