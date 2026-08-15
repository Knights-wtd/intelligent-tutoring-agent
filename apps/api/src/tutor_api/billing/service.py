from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from tutor_api.billing.models import (
    LedgerEntry,
    LedgerEntryType,
    Wallet,
    WalletReservation,
    WalletReservationState,
)
from tutor_api.billing.schemas import (
    ReleaseResult,
    ReservationResult,
    SettlementResult,
    VerifiedUsage,
)
from tutor_api.providers.models import FxVersion, PriceVersion


class InsufficientFundsError(ValueError):
    pass


class InvalidUsageError(ValueError):
    pass


def _money(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.00000001"))


def _positive_money(value: Decimal | int | str) -> Decimal:
    amount = _money(value)
    if amount <= Decimal("0"):
        raise ValueError("Reservation amount must be positive")
    return amount


def _wallet_for_update(session: Session, user_id: UUID) -> Wallet:
    wallet = session.scalar(select(Wallet).where(Wallet.user_id == user_id).with_for_update())
    if wallet is not None:
        return wallet

    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        statement = postgresql_insert(Wallet).values(user_id=user_id).on_conflict_do_nothing(
            index_elements=["user_id"]
        )
    elif dialect_name == "sqlite":
        statement = sqlite_insert(Wallet).values(user_id=user_id).on_conflict_do_nothing(
            index_elements=["user_id"]
        )
    else:
        raise RuntimeError("Wallet reservations require PostgreSQL or SQLite")
    # A concurrent first request may insert first. PostgreSQL waits for that
    # transaction and then treats this as a no-op; the following lock reads its row.
    session.execute(statement)
    wallet = session.scalar(select(Wallet).where(Wallet.user_id == user_id).with_for_update())
    if wallet is None:
        raise RuntimeError("Wallet creation did not return a wallet row")
    return wallet


def _ledger_total(session: Session, wallet_id: UUID) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0"))).where(
            LedgerEntry.wallet_id == wallet_id
        )
    )
    return _money(total or Decimal("0"))


def _active_reservations_total(session: Session, wallet_id: UUID) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(WalletReservation.reserved_amount), Decimal("0"))).where(
            WalletReservation.wallet_id == wallet_id,
            WalletReservation.state == WalletReservationState.ACTIVE,
        )
    )
    return _money(total or Decimal("0"))


def wallet_balance(session: Session, user_id: UUID) -> Decimal:
    """Return posted balance; active reservations are intentionally not ledger entries."""

    wallet = session.scalar(select(Wallet).where(Wallet.user_id == user_id))
    return Decimal("0.00000000") if wallet is None else _ledger_total(session, wallet.id)


def available_balance(session: Session, wallet_id: UUID) -> Decimal:
    return _money(
        _ledger_total(session, wallet_id) - _active_reservations_total(session, wallet_id)
    )


def reserve(
    session: Session, user_id: UUID, request_id: str, amount: Decimal | int | str
) -> ReservationResult:
    reserved_amount = _positive_money(amount)
    if not request_id.strip():
        raise ValueError("Request id must not be blank")

    existing = _reservation_for_request(session, request_id)
    if existing is not None:
        _assert_reservation_owner(session, existing, user_id)
        return _reservation_result(existing)

    wallet = _wallet_for_update(session, user_id)
    # The wallet lock serializes same-wallet requests. Recheck after acquiring it
    # so concurrent retries cannot insert a second row for the same request id.
    existing = _reservation_for_request(session, request_id)
    if existing is not None:
        _assert_reservation_owner(session, existing, user_id)
        return _reservation_result(existing)
    if available_balance(session, wallet.id) < reserved_amount:
        raise InsufficientFundsError("Insufficient available balance")

    reservation = WalletReservation(
        wallet_id=wallet.id,
        request_id=request_id,
        reserved_amount=reserved_amount,
        state=WalletReservationState.ACTIVE,
    )
    session.add(reservation)
    session.flush()
    return _reservation_result(reservation)


def _reservation_result(reservation: WalletReservation) -> ReservationResult:
    return ReservationResult(
        id=reservation.id,
        wallet_id=reservation.wallet_id,
        request_id=reservation.request_id,
        reserved_amount=reservation.reserved_amount,
        state=reservation.state.value,
    )


def _reservation_for_request(session: Session, request_id: str) -> WalletReservation | None:
    return session.scalar(
        select(WalletReservation)
        .where(WalletReservation.request_id == request_id)
        .with_for_update()
    )


def _assert_reservation_owner(
    session: Session, reservation: WalletReservation, user_id: UUID
) -> None:
    wallet = session.get(Wallet, reservation.wallet_id)
    if wallet is None or wallet.user_id != user_id:
        raise ValueError("Request id is already associated with another wallet")


def settle(session: Session, reservation_id: UUID, usage: VerifiedUsage) -> SettlementResult:
    reservation = session.scalar(
        select(WalletReservation)
        .where(WalletReservation.id == reservation_id)
        .with_for_update()
    )
    if reservation is None:
        raise ValueError("Reservation was not found")
    existing_entry = session.scalar(
        select(LedgerEntry).where(LedgerEntry.reservation_id == reservation.id)
    )
    if reservation.state == WalletReservationState.SETTLED:
        if existing_entry is None:
            raise RuntimeError("Settled reservation has no ledger entry")
        return SettlementResult(
            reservation_id=reservation.id,
            ledger_entry_id=existing_entry.id,
            charged_amount=_money(-existing_entry.amount),
        )
    if reservation.state == WalletReservationState.RELEASED:
        raise ValueError("Released reservation cannot be settled")
    if not usage.verified:
        raise InvalidUsageError("Usage must be verified before settlement")

    price, fx = _current_pricing(session, usage)
    charged_amount = _usage_charge(usage, price, fx)
    if charged_amount > reservation.reserved_amount:
        raise InsufficientFundsError("Verified usage exceeds the reserved amount")

    price_snapshot = _price_snapshot(price)
    fx_snapshot = _fx_snapshot(fx, price.currency)
    entry = LedgerEntry(
        wallet_id=reservation.wallet_id,
        reservation_id=reservation.id,
        amount=-charged_amount,
        entry_type=LedgerEntryType.CONSUMPTION,
        snapshot={
            "usage": usage.model_dump(mode="json"),
            "price": price_snapshot,
            "fx": fx_snapshot,
        },
    )
    session.add(entry)
    reservation.price_snapshot = price_snapshot
    reservation.fx_snapshot = fx_snapshot
    reservation.state = WalletReservationState.SETTLED
    reservation.settled_at = datetime.now(UTC)
    session.flush()
    return SettlementResult(
        reservation_id=reservation.id,
        ledger_entry_id=entry.id,
        charged_amount=charged_amount,
    )


def release(session: Session, reservation_id: UUID) -> ReleaseResult:
    reservation = session.scalar(
        select(WalletReservation)
        .where(WalletReservation.id == reservation_id)
        .with_for_update()
    )
    if reservation is None:
        raise ValueError("Reservation was not found")
    if reservation.state == WalletReservationState.ACTIVE:
        reservation.state = WalletReservationState.RELEASED
        reservation.released_at = datetime.now(UTC)
        session.flush()
    return ReleaseResult(
        reservation_id=reservation.id,
        released=reservation.state == WalletReservationState.RELEASED,
    )


def _current_pricing(
    session: Session, usage: VerifiedUsage
) -> tuple[PriceVersion, FxVersion | None]:
    now = datetime.now(UTC)
    price = session.scalar(
        select(PriceVersion)
        .where(
            PriceVersion.provider_profile_id == usage.provider_profile_id,
            PriceVersion.effective_at <= now,
        )
        .order_by(PriceVersion.effective_at.desc())
        .limit(1)
    )
    if price is None:
        raise InvalidUsageError("No current price snapshot is available")
    if price.currency == "CNY":
        return price, None
    fx = session.scalar(
        select(FxVersion)
        .where(
            FxVersion.base_currency == price.currency,
            FxVersion.quote_currency == "CNY",
            FxVersion.effective_at <= now,
        )
        .order_by(FxVersion.effective_at.desc())
        .limit(1)
    )
    if fx is None:
        raise InvalidUsageError("No current exchange-rate snapshot is available")
    return price, fx


def _usage_charge(usage: VerifiedUsage, price: PriceVersion, fx: FxVersion | None) -> Decimal:
    source_amount = (
        Decimal(usage.input_units) * price.input_unit_price
        + Decimal(usage.cached_input_units) * price.cached_input_unit_price
        + Decimal(usage.output_units) * price.output_unit_price
    ) / Decimal(price.unit_size)
    exchange_rate = Decimal("1") if fx is None else fx.rate
    return _money(source_amount * exchange_rate)


def _price_snapshot(price: PriceVersion) -> dict[str, str | int]:
    return {
        "id": str(price.id),
        "effective_at": price.effective_at.isoformat(),
        "source_url": price.source_url,
        "currency": price.currency,
        "input_unit_price": str(price.input_unit_price),
        "cached_input_unit_price": str(price.cached_input_unit_price),
        "output_unit_price": str(price.output_unit_price),
        "unit_size": price.unit_size,
    }


def _fx_snapshot(fx: FxVersion | None, source_currency: str) -> dict[str, str]:
    if fx is None:
        return {"base_currency": source_currency, "quote_currency": "CNY", "rate": "1"}
    return {
        "id": str(fx.id),
        "effective_at": fx.effective_at.isoformat(),
        "source_url": fx.source_url,
        "base_currency": fx.base_currency,
        "quote_currency": fx.quote_currency,
        "rate": str(fx.rate),
    }
