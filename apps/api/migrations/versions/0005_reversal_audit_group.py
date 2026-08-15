"""require complete reversal audit groups

Revision ID: 0005_reversal_audit_group
Revises: 0004_recharge_reversal_audit
Create Date: 2026-08-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_reversal_audit_group"
down_revision: str | Sequence[str] | None = "0004_recharge_reversal_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_GROUP_CHECK = (
    "(reversal_ledger_entry_id IS NULL AND reversed_at IS NULL AND "
    "reversed_by_user_id IS NULL AND reversal_reason IS NULL) OR "
    "(reversal_ledger_entry_id IS NOT NULL AND reversed_at IS NOT NULL AND "
    "reversed_by_user_id IS NOT NULL AND reversal_reason IS NOT NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table("recharge_records") as batch_op:
        batch_op.drop_constraint("ck_recharge_record_reversal_audit_complete", type_="check")
        batch_op.create_check_constraint(
            "ck_recharge_record_reversal_audit_complete", _AUDIT_GROUP_CHECK
        )


def downgrade() -> None:
    with op.batch_alter_table("recharge_records") as batch_op:
        batch_op.drop_constraint("ck_recharge_record_reversal_audit_complete", type_="check")
        batch_op.create_check_constraint(
            "ck_recharge_record_reversal_audit_complete", _AUDIT_GROUP_CHECK
        )
