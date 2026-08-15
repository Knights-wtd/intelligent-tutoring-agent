from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.core.database import Base


class WalletReservationState(StrEnum):
    ACTIVE = "active"
    SETTLED = "settled"
    RELEASED = "released"


class LedgerEntryType(StrEnum):
    RECHARGE = "recharge"
    REVERSAL = "reversal"
    CONSUMPTION = "consumption"


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WalletReservation(Base):
    __tablename__ = "wallet_reservations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('active', 'settled', 'released')", name="ck_wallet_reservation_state"
        ),
        CheckConstraint("reserved_amount > 0", name="ck_wallet_reservation_amount_positive"),
        UniqueConstraint("id", "wallet_id", name="uq_wallet_reservation_id_wallet"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    wallet_id: Mapped[UUID] = mapped_column(ForeignKey("wallets.id"), index=True)
    provider_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_profiles.id"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(255), unique=True)
    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    state: Mapped[WalletReservationState] = mapped_column(
        Enum(
            WalletReservationState,
            native_enum=False,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        default=WalletReservationState.ACTIVE,
    )
    price_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fx_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('recharge', 'consumption', 'reversal')", name="ck_ledger_entry_type"
        ),
        ForeignKeyConstraint(
            ["reservation_id", "wallet_id"],
            ["wallet_reservations.id", "wallet_reservations.wallet_id"],
            name="fk_ledger_entry_reservation_wallet",
        ),
        UniqueConstraint("id", "wallet_id", name="uq_ledger_entry_id_wallet"),
        UniqueConstraint("reservation_id", name="uq_ledger_entry_reservation"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    wallet_id: Mapped[UUID] = mapped_column(ForeignKey("wallets.id"), index=True)
    reservation_id: Mapped[UUID | None] = mapped_column()
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        Enum(
            LedgerEntryType,
            native_enum=False,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        )
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RechargeRecord(Base):
    __tablename__ = "recharge_records"
    __table_args__ = (
        CheckConstraint(
            "(reversed_by_user_id IS NULL AND reversal_reason IS NULL) OR "
            "(reversed_by_user_id IS NOT NULL AND reversal_reason IS NOT NULL)",
            name="ck_recharge_record_reversal_audit_complete",
        ),
        ForeignKeyConstraint(
            ["ledger_entry_id", "wallet_id"],
            ["ledger_entries.id", "ledger_entries.wallet_id"],
            name="fk_recharge_record_primary_ledger_wallet",
        ),
        ForeignKeyConstraint(
            ["reversal_ledger_entry_id", "wallet_id"],
            ["ledger_entries.id", "ledger_entries.wallet_id"],
            name="fk_recharge_record_reversal_ledger_wallet",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    wallet_id: Mapped[UUID] = mapped_column(ForeignKey("wallets.id"), index=True)
    ledger_entry_id: Mapped[UUID] = mapped_column(unique=True)
    reversal_ledger_entry_id: Mapped[UUID | None] = mapped_column(unique=True)
    external_reference: Mapped[str] = mapped_column(String(255), unique=True)
    reason: Mapped[str] = mapped_column(String(1000))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    reversal_reason: Mapped[str | None] = mapped_column(String(1000))
