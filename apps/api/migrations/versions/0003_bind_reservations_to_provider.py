"""bind wallet reservations to selected provider profiles

Revision ID: 0003_reservation_provider
Revises: 0002_provider_wallet
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_reservation_provider"
down_revision: str | Sequence[str] | None = "0002_provider_wallet"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_PROFILE_ID = "00000000-0000-0000-0000-000000000003"
_LEGACY_PROFILE_KEY = "__legacy_reservation_unavailable__"


def upgrade() -> None:
    # Reservations created before this migration have no trustworthy model identity.
    # Preserve their audit trail but make pending authorization unusable: bind them to
    # a dedicated disabled profile and release any active hold before enforcing NOT NULL.
    op.execute(
        sa.text(
            "INSERT INTO provider_profiles "
            "(id, profile_key, provider, model, display_name, supports_usage, enabled) "
            f"VALUES ('{_LEGACY_PROFILE_ID}', '{_LEGACY_PROFILE_KEY}', "
            "'legacy', 'unavailable', '历史预留（不可结算）', false, false) "
            "ON CONFLICT (profile_key) DO NOTHING"
        )
    )
    with op.batch_alter_table("wallet_reservations") as batch_op:
        batch_op.add_column(sa.Column("provider_profile_id", sa.Uuid(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE wallet_reservations "
            f"SET provider_profile_id = '{_LEGACY_PROFILE_ID}' "
            "WHERE provider_profile_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE wallet_reservations "
            "SET state = 'released', released_at = COALESCE(released_at, CURRENT_TIMESTAMP) "
            "WHERE state = 'active'"
        )
    )
    with op.batch_alter_table("wallet_reservations") as batch_op:
        batch_op.alter_column("provider_profile_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_wallet_reservation_provider_profile",
            "provider_profiles",
            ["provider_profile_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_wallet_reservations_provider_profile_id", ["provider_profile_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("wallet_reservations") as batch_op:
        batch_op.drop_index("ix_wallet_reservations_provider_profile_id")
        batch_op.drop_constraint("fk_wallet_reservation_provider_profile", type_="foreignkey")
        batch_op.drop_column("provider_profile_id")
