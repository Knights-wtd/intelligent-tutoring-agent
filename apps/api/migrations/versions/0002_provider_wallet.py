"""create provider catalog and wallet schema

Revision ID: 0002_provider_wallet
Revises: 0001_identity
Create Date: 2026-08-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_provider_wallet"
down_revision: str | Sequence[str] | None = "0001_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_key", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("supports_usage", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_key"),
    )
    op.create_index("ix_provider_profiles_provider", "provider_profiles", ["provider"])
    op.create_table(
        "price_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_profile_id", sa.Uuid(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("input_unit_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("cached_input_unit_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("output_unit_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("unit_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["provider_profile_id"], ["provider_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "input_unit_price >= 0", name="ck_price_version_input_unit_price_nonnegative"
        ),
        sa.CheckConstraint(
            "cached_input_unit_price >= 0",
            name="ck_price_version_cached_input_unit_price_nonnegative",
        ),
        sa.CheckConstraint(
            "output_unit_price >= 0", name="ck_price_version_output_unit_price_nonnegative"
        ),
        sa.CheckConstraint("unit_size > 0", name="ck_price_version_unit_size_positive"),
        sa.UniqueConstraint(
            "provider_profile_id", "effective_at", name="uq_price_version_profile_effective_at"
        ),
    )
    op.create_index("ix_price_versions_provider_profile_id", "price_versions", ["provider_profile_id"])
    op.create_table(
        "fx_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rate", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("rate > 0", name="ck_fx_version_rate_positive"),
        sa.UniqueConstraint(
            "base_currency", "quote_currency", "effective_at", name="uq_fx_version_pair_effective_at"
        ),
    )
    op.create_table(
        "wallets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "wallet_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("wallet_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("state", sa.String(length=8), nullable=False),
        sa.Column("price_snapshot", sa.JSON(), nullable=True),
        sa.Column("fx_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "state IN ('active', 'settled', 'released')", name="ck_wallet_reservation_state"
        ),
        sa.CheckConstraint("reserved_amount > 0", name="ck_wallet_reservation_amount_positive"),
        sa.UniqueConstraint("request_id"),
        sa.UniqueConstraint("id", "wallet_id", name="uq_wallet_reservation_id_wallet"),
    )
    op.create_index("ix_wallet_reservations_wallet_id", "wallet_reservations", ["wallet_id"])
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("wallet_id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("entry_type", sa.String(length=11), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id", "wallet_id"],
            ["wallet_reservations.id", "wallet_reservations.wallet_id"],
            name="fk_ledger_entry_reservation_wallet",
        ),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "entry_type IN ('recharge', 'consumption', 'reversal')", name="ck_ledger_entry_type"
        ),
        sa.UniqueConstraint("id", "wallet_id", name="uq_ledger_entry_id_wallet"),
        sa.UniqueConstraint("reservation_id", name="uq_ledger_entry_reservation"),
    )
    op.create_index("ix_ledger_entries_wallet_id", "ledger_entries", ["wallet_id"])
    op.create_table(
        "recharge_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("wallet_id", sa.Uuid(), nullable=False),
        sa.Column("ledger_entry_id", sa.Uuid(), nullable=False),
        sa.Column("reversal_ledger_entry_id", sa.Uuid(), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["ledger_entry_id", "wallet_id"],
            ["ledger_entries.id", "ledger_entries.wallet_id"],
            name="fk_recharge_record_primary_ledger_wallet",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_ledger_entry_id", "wallet_id"],
            ["ledger_entries.id", "ledger_entries.wallet_id"],
            name="fk_recharge_record_reversal_ledger_wallet",
        ),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ledger_entry_id"),
        sa.UniqueConstraint("reversal_ledger_entry_id"),
        sa.UniqueConstraint("external_reference"),
    )
    op.create_index("ix_recharge_records_wallet_id", "recharge_records", ["wallet_id"])
    op.create_index("ix_recharge_records_created_by_user_id", "recharge_records", ["created_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_recharge_records_created_by_user_id", table_name="recharge_records")
    op.drop_index("ix_recharge_records_wallet_id", table_name="recharge_records")
    op.drop_table("recharge_records")
    op.drop_index("ix_ledger_entries_wallet_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_wallet_reservations_wallet_id", table_name="wallet_reservations")
    op.drop_table("wallet_reservations")
    op.drop_table("wallets")
    op.drop_table("fx_versions")
    op.drop_index("ix_price_versions_provider_profile_id", table_name="price_versions")
    op.drop_table("price_versions")
    op.drop_index("ix_provider_profiles_provider", table_name="provider_profiles")
    op.drop_table("provider_profiles")
