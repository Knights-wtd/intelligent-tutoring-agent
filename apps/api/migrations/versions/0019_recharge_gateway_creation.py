"""persist gateway creation payload and wechat provider on recharge orders

Revision ID: 0019_recharge_gateway_creation
Revises: 0018_question_generation
Create Date: 2026-08-30

0017 曾在已应用后被直接编辑，导致已部署库缺 gateway_creation 列且
provider CHECK 不含 wechat；本迁移把这两处变化以增量方式补齐。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_recharge_gateway_creation"
down_revision: str | Sequence[str] | None = "0018_question_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND_CHECK = "provider IN ('mock', 'alipay', 'wechat')"
_LEGACY_KIND_CHECK = "provider IN ('mock', 'alipay')"


def upgrade() -> None:
    notify_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column("recharge_orders", sa.Column("gateway_creation", notify_type, nullable=True))
    with op.batch_alter_table("recharge_orders") as batch:
        batch.drop_constraint("payment_provider_kind", type_="check")
        batch.create_check_constraint("payment_provider_kind", _KIND_CHECK)


def downgrade() -> None:
    op.execute("DELETE FROM recharge_orders WHERE provider = 'wechat'")
    with op.batch_alter_table("recharge_orders") as batch:
        batch.drop_constraint("payment_provider_kind", type_="check")
        batch.create_check_constraint("payment_provider_kind", _LEGACY_KIND_CHECK)
    op.drop_column("recharge_orders", "gateway_creation")
