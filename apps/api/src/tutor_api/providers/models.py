from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.core.database import Base


class ProviderProfile(Base):
    __tablename__ = "provider_profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_key: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    model: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    supports_usage: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PriceVersion(Base):
    __tablename__ = "price_versions"
    __table_args__ = (
        UniqueConstraint(
            "provider_profile_id", "effective_at", name="uq_price_version_profile_effective_at"
        ),
        CheckConstraint(
            "input_unit_price >= 0", name="ck_price_version_input_unit_price_nonnegative"
        ),
        CheckConstraint(
            "cached_input_unit_price >= 0",
            name="ck_price_version_cached_input_unit_price_nonnegative",
        ),
        CheckConstraint(
            "output_unit_price >= 0", name="ck_price_version_output_unit_price_nonnegative"
        ),
        CheckConstraint("unit_size > 0", name="ck_price_version_unit_size_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_profiles.id"), index=True
    )
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(String(2048))
    currency: Mapped[str] = mapped_column(String(3))
    input_unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    cached_input_unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    output_unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    unit_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FxVersion(Base):
    __tablename__ = "fx_versions"
    __table_args__ = (
        UniqueConstraint(
            "base_currency",
            "quote_currency",
            "effective_at",
            name="uq_fx_version_pair_effective_at",
        ),
        CheckConstraint("rate > 0", name="ck_fx_version_rate_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    base_currency: Mapped[str] = mapped_column(String(3))
    quote_currency: Mapped[str] = mapped_column(String(3))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    source_url: Mapped[str] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
