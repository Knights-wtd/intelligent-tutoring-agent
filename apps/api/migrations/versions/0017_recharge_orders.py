"""create self-service recharge orders for payment gateways

Revision ID: 0017_recharge_orders
Revises: 0016_tutor_message_kind
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_recharge_orders"
down_revision: str | Sequence[str] | None = "0016_tutor_message_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # recharge_orders' composite FK targets recharge_records(id, wallet_id);
    # SQLite requires the parent pair to be uniquely constrained together.
    with op.batch_alter_table("recharge_records") as batch_op:
        batch_op.create_unique_constraint(
            "uq_recharge_record_id_wallet", ["id", "wallet_id"]
        )
    notify_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "recharge_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("wallet_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum(
                "mock",
                "alipay",
                name="payment_provider_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("out_trade_no", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "paid",
                "paid_mismatch",
                "cancelled",
                name="recharge_order_state",
                native_enum=False,
                server_default="pending",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("credited_recharge_record_id", sa.Uuid(), nullable=True),
        sa.Column("gateway_trade_no", sa.String(length=64), nullable=True),
        sa.Column("gateway_notify", notify_type, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_recharge_order_amount_positive"),
        sa.CheckConstraint(
            "state IN ('pending', 'paid', 'paid_mismatch', 'cancelled')",
            name="ck_recharge_order_state",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id"],
            ["wallets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["credited_recharge_record_id", "wallet_id"],
            ["recharge_records.id", "recharge_records.wallet_id"],
            name="fk_recharge_order_credit_record_wallet",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("out_trade_no"),
        sa.UniqueConstraint("credited_recharge_record_id"),
        sa.UniqueConstraint("gateway_trade_no"),
    )
    op.create_index("ix_recharge_orders_user_id", "recharge_orders", ["user_id"])
    op.create_index("ix_recharge_orders_wallet_id", "recharge_orders", ["wallet_id"])


def downgrade() -> None:
    op.drop_index("ix_recharge_orders_wallet_id", table_name="recharge_orders")
    op.drop_index("ix_recharge_orders_user_id", table_name="recharge_orders")
    op.drop_table("recharge_orders")
    with op.batch_alter_table("recharge_records") as batch_op:
        batch_op.drop_constraint("uq_recharge_record_id_wallet", type_="unique")
