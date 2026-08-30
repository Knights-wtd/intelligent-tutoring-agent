"""add self-service recharge orders and payment gateway payloads

Revision ID: 0019_recharge_orders_payment
Revises: 0018_object_deletion_outbox
Create Date: 2026-08-30

This migration is intentionally based on the current stable head.  qyw211's
payment migrations used revision ids that overlap with the current knowledge and
agent migrations, so they cannot be copied into this branch unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_recharge_orders_payment"
down_revision: str | Sequence[str] | None = "0018_object_deletion_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PROVIDER_CHECK = "provider IN ('mock', 'alipay', 'wechat')"


def upgrade() -> None:
    # recharge_orders uses a composite FK to recharge_records so that a credit
    # can never be attached to a different wallet.  SQLite requires the parent
    # key pair to have an explicit unique constraint.
    with op.batch_alter_table("recharge_records") as batch:
        batch.create_unique_constraint("uq_recharge_record_id_wallet", ["id", "wallet_id"])

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
                "wechat",
                name="payment_provider_kind",
                native_enum=False,
                create_constraint=False,
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
                create_constraint=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("credited_recharge_record_id", sa.Uuid(), nullable=True),
        sa.Column("gateway_trade_no", sa.String(length=64), nullable=True),
        sa.Column("gateway_notify", notify_type, nullable=True),
        sa.Column("gateway_creation", notify_type, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_recharge_order_amount_positive"),
        sa.CheckConstraint(_PROVIDER_CHECK, name="payment_provider_kind"),
        sa.CheckConstraint(
            "state IN ('pending', 'paid', 'paid_mismatch', 'cancelled')",
            name="ck_recharge_order_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
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
    with op.batch_alter_table("recharge_records") as batch:
        batch.drop_constraint("uq_recharge_record_id_wallet", type_="unique")
