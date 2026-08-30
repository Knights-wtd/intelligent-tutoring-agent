"""Wallet ledger primitives: reserve/settle/release plus manual recharge and reversal.

DELIBERATE FREEZE (2026-08-27): ``reserve``/``settle``/``release`` are intentionally
NOT reachable from any HTTP route. Tutor conversations currently cost nothing, and
settlement would price reservations at the latest snapshot at settle time instead of
locking a quote at reserve time. Wiring metering into the tutor path is a product
decision that must land together with quote locking; do not expose these functions
from routers until that decision is made.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from tutor_api.billing.gateways import order_reference_for_provider
from tutor_api.billing.models import (
    LedgerEntry,
    LedgerEntryType,
    PaymentProviderKind,
    RechargeOrder,
    RechargeOrderState,
    RechargeRecord,
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
from tutor_api.identity.models import User
from tutor_api.providers.models import FxVersion, PriceVersion, ProviderProfile


class InsufficientFundsError(ValueError):
    pass


class InvalidUsageError(ValueError):
    pass


class RechargeAlreadyReversedError(ValueError):
    pass


class RechargeCannotBeReversedError(ValueError):
    pass


class DuplicateExternalReferenceError(ValueError):
    pass


class RechargeTargetUserNotFoundError(ValueError):
    pass


class RechargeOrderNotFoundError(LookupError):
    pass


class RechargeOrderAmountError(ValueError):
    pass


# 积分与人民币 1:1:订单金额即入账积分,单位为元,保留两位小数。
MIN_RECHARGE_ORDER_AMOUNT = Decimal("1.00")
MAX_RECHARGE_ORDER_AMOUNT = Decimal("10000.00")
_SUPPORTED_RECHARGE_PROVIDERS = frozenset(
    {PaymentProviderKind.MOCK.value, PaymentProviderKind.ALIPAY.value, "wechat"}
)


def _cents_money(value: Decimal | int | str) -> Decimal:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    return amount


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


def _wallet_by_id_for_update(session: Session, wallet_id: UUID) -> Wallet:
    wallet = session.scalar(select(Wallet).where(Wallet.id == wallet_id).with_for_update())
    if wallet is None:
        raise RuntimeError("Wallet was not found")
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


def create_manual_recharge(
    session: Session,
    *,
    user_id: UUID,
    amount: Decimal | int | str,
    external_reference: str,
    reason: str,
    created_by_user_id: UUID,
) -> RechargeRecord:
    recharge_amount = _positive_money(amount)
    if not external_reference.strip() or not reason.strip():
        raise ValueError("Recharge reference and reason must not be blank")
    if session.get(User, user_id) is None:
        raise RechargeTargetUserNotFoundError("User was not found")
    if session.scalar(
        select(RechargeRecord).where(RechargeRecord.external_reference == external_reference)
    ) is not None:
        raise DuplicateExternalReferenceError("External reference has already been used")
    wallet = _wallet_for_update(session, user_id)
    # Same-wallet writes are serialized by the wallet lock. Recheck after it so
    # concurrent retries of the same external reference do not add a second ledger row.
    if session.scalar(
        select(RechargeRecord).where(RechargeRecord.external_reference == external_reference)
    ) is not None:
        raise DuplicateExternalReferenceError("External reference has already been used")
    entry = LedgerEntry(
        wallet_id=wallet.id,
        amount=recharge_amount,
        entry_type=LedgerEntryType.RECHARGE,
        snapshot={
            "external_reference": external_reference,
            "reason": reason,
            "created_by_user_id": str(created_by_user_id),
        },
    )
    session.add(entry)
    session.flush()
    record = RechargeRecord(
        wallet_id=wallet.id,
        ledger_entry_id=entry.id,
        external_reference=external_reference,
        reason=reason,
        created_by_user_id=created_by_user_id,
    )
    session.add(record)
    session.flush()
    return record


def reverse_manual_recharge(
    session: Session, *, recharge_record_id: UUID, reason: str, reversed_by_user_id: UUID
) -> LedgerEntry:
    if not reason.strip():
        raise ValueError("Reversal reason must not be blank")
    record = session.scalar(
        select(RechargeRecord)
        .where(RechargeRecord.id == recharge_record_id)
        .with_for_update()
    )
    if record is None:
        raise LookupError("Recharge record was not found")
    if record.reversal_ledger_entry_id is not None:
        raise RechargeAlreadyReversedError("Recharge has already been reversed")
    original_entry = session.get(LedgerEntry, record.ledger_entry_id)
    if original_entry is None or original_entry.wallet_id != record.wallet_id:
        raise RuntimeError("Recharge audit record is invalid")
    wallet = _wallet_by_id_for_update(session, record.wallet_id)
    original_amount = _money(original_entry.amount)
    if original_amount <= Decimal("0"):
        raise RuntimeError("Recharge ledger entry must be positive")
    if available_balance(session, wallet.id) < original_amount:
        raise RechargeCannotBeReversedError("Recharge funds are no longer available")
    entry = LedgerEntry(
        wallet_id=record.wallet_id,
        amount=-original_amount,
        entry_type=LedgerEntryType.REVERSAL,
        snapshot={
            "reversal_of_recharge_record_id": str(record.id),
            "reversal_of_ledger_entry_id": str(original_entry.id),
            "reason": reason,
            "reversed_by_user_id": str(reversed_by_user_id),
        },
    )
    session.add(entry)
    session.flush()
    record.reversal_ledger_entry_id = entry.id
    record.reversed_at = datetime.now(UTC)
    record.reversed_by_user_id = reversed_by_user_id
    record.reversal_reason = reason
    session.flush()
    return entry


def create_recharge_order(
    session: Session,
    *,
    user_id: UUID,
    provider: str,
    amount: Decimal | int | str,
) -> RechargeOrder:
    """Open a pending gateway recharge order for the user's wallet."""

    if provider not in _SUPPORTED_RECHARGE_PROVIDERS:
        raise RechargeOrderAmountError("Unsupported payment provider")
    order_amount = _cents_money(amount)
    if order_amount < MIN_RECHARGE_ORDER_AMOUNT or order_amount > MAX_RECHARGE_ORDER_AMOUNT:
        raise RechargeOrderAmountError(
            "Recharge amount is outside the supported range "
            f"[{MIN_RECHARGE_ORDER_AMOUNT}, {MAX_RECHARGE_ORDER_AMOUNT}]"
        )
    wallet = _wallet_for_update(session, user_id)
    order = RechargeOrder(
        user_id=user_id,
        wallet_id=wallet.id,
        provider=PaymentProviderKind(provider),
        amount=order_amount,
        out_trade_no=f"R{uuid4().hex}",
        state=RechargeOrderState.PENDING,
    )
    session.add(order)
    session.flush()
    return order


def confirm_recharge_payment(
    session: Session,
    *,
    out_trade_no: str,
    gateway_trade_no: str,
    paid_amount: Decimal | int | str,
    notify_payload: dict[str, str],
) -> RechargeOrder:
    """Credit a paid gateway order exactly once, idempotent across retries.

    Amount mismatches are never auto-credited: the order moves to
    ``paid_mismatch`` and stays untouched for manual reconciliation, because
    silently posting a different amount would corrupt the 1:1 points contract.
    """

    order = session.scalar(
        select(RechargeOrder).where(RechargeOrder.out_trade_no == out_trade_no).with_for_update()
    )
    if order is None:
        raise RechargeOrderNotFoundError("Recharge order was not found")
    if order.state != RechargeOrderState.PENDING:
        return order
    paid = _cents_money(paid_amount)
    now = datetime.now(UTC)
    order.gateway_notify = notify_payload
    order.gateway_trade_no = gateway_trade_no
    if paid != order.amount:
        order.state = RechargeOrderState.PAID_MISMATCH
        order.paid_at = now
        session.flush()
        return order
    record = create_manual_recharge(
        session,
        user_id=order.user_id,
        amount=order.amount,
        external_reference=order_reference_for_provider(order.provider.value, gateway_trade_no),
        reason=f"在线充值：{order.provider.value} 订单 {order.out_trade_no}",
        created_by_user_id=order.user_id,
    )
    order.credited_recharge_record_id = record.id
    order.state = RechargeOrderState.PAID
    order.paid_at = now
    session.flush()
    return order


def recharge_order_for_user(
    session: Session, order_id: UUID, *, user_id: UUID
) -> RechargeOrder:
    order = session.get(RechargeOrder, order_id)
    if order is None or order.user_id != user_id:
        raise RechargeOrderNotFoundError("Recharge order was not found")
    return order


def billing_entries(
    session: Session, user_id: UUID, *, limit: int, offset: int
) -> tuple[Decimal, str, list[LedgerEntry], int]:
    wallet = session.scalar(select(Wallet).where(Wallet.user_id == user_id))
    if wallet is None:
        return Decimal("0.00000000"), "CNY", [], 0
    total = session.scalar(
        select(func.count()).select_from(LedgerEntry).where(LedgerEntry.wallet_id == wallet.id)
    )
    entries = list(
        session.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.wallet_id == wallet.id)
            .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return _ledger_total(session, wallet.id), wallet.currency, entries, total or 0


def reserve(
    session: Session,
    user_id: UUID,
    request_id: str,
    amount: Decimal | int | str,
    provider_profile_id: UUID,
) -> ReservationResult:
    reserved_amount = _positive_money(amount)
    if not request_id.strip():
        raise ValueError("Request id must not be blank")

    existing = _reservation_for_request(session, request_id)
    if existing is not None:
        _assert_reservation_owner(session, existing, user_id)
        _assert_reservation_profile(existing, provider_profile_id)
        return _reservation_result(existing)

    wallet = _wallet_for_update(session, user_id)
    # The wallet lock serializes same-wallet requests. Recheck after acquiring it
    # so concurrent retries cannot insert a second row for the same request id.
    existing = _reservation_for_request(session, request_id)
    if existing is not None:
        _assert_reservation_owner(session, existing, user_id)
        _assert_reservation_profile(existing, provider_profile_id)
        return _reservation_result(existing)
    _enabled_usage_profile(session, provider_profile_id)
    if available_balance(session, wallet.id) < reserved_amount:
        raise InsufficientFundsError("Insufficient available balance")

    reservation = WalletReservation(
        wallet_id=wallet.id,
        provider_profile_id=provider_profile_id,
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


def _assert_reservation_profile(
    reservation: WalletReservation, provider_profile_id: UUID
) -> None:
    if reservation.provider_profile_id != provider_profile_id:
        raise ValueError("Request id is already associated with another provider profile")


def _enabled_usage_profile(session: Session, provider_profile_id: UUID) -> ProviderProfile:
    profile = session.scalar(
        select(ProviderProfile)
        .where(
            ProviderProfile.id == provider_profile_id,
            ProviderProfile.enabled.is_(True),
            ProviderProfile.supports_usage.is_(True),
        )
        .with_for_update()
    )
    if profile is None:
        raise InvalidUsageError("Selected profile is not enabled usage-capable")
    return profile


def _bound_profile(session: Session, provider_profile_id: UUID) -> ProviderProfile:
    profile = session.scalar(
        select(ProviderProfile)
        .where(ProviderProfile.id == provider_profile_id)
        .with_for_update()
    )
    if profile is None:
        raise InvalidUsageError("Reserved provider profile no longer exists")
    return profile


def settle(session: Session, reservation_id: UUID, usage: VerifiedUsage) -> SettlementResult:
    reservation = session.scalar(
        select(WalletReservation)
        .where(WalletReservation.id == reservation_id)
        .with_for_update()
    )
    if reservation is None:
        raise ValueError("Reservation was not found")
    _wallet_by_id_for_update(session, reservation.wallet_id)
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
    if usage.provider_profile_id != reservation.provider_profile_id:
        raise InvalidUsageError(
            "Usage provider profile does not match the reserved provider profile"
        )
    _bound_profile(session, reservation.provider_profile_id)

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
