import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

import tutor_api.billing.models  # noqa: F401
from tutor_api.billing.models import LedgerEntry, LedgerEntryType, Wallet, WalletReservation
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.providers.models import FxVersion, PriceVersion, ProviderProfile


@pytest.fixture
def session():
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as database_session:
        user = User(
            email="learner@example.com",
            username="learner",
            password_hash="not-used-by-wallet-tests",
        )
        database_session.add(user)
    with factory() as database_session:
        yield database_session
    engine.dispose()


def usable_profile(session, key: str = "example-model") -> ProviderProfile:
    profile = ProviderProfile(
        profile_key=key,
        provider="example",
        model=f"{key}-model",
        display_name="示例模型",
        supports_usage=True,
        enabled=True,
    )
    session.add(profile)
    session.flush()
    return profile


def test_reserve_creates_a_wallet_and_tracks_available_balance(session) -> None:
    from tutor_api.billing.service import reserve, wallet_balance

    user = session.query(User).filter_by(username="learner").one()
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    session.add(
        LedgerEntry(
            wallet_id=wallet.id,
            amount=Decimal("20.00"),
            entry_type=LedgerEntryType.RECHARGE,
            snapshot={},
        )
    )
    session.flush()
    profile = usable_profile(session, "reserve-model")

    reservation = reserve(session, user.id, "run-1", Decimal("10.00"), profile.id)

    assert reservation.reserved_amount == Decimal("10.00000000")
    assert wallet_balance(session, user.id) == Decimal("20.00000000")


def test_reservation_rejects_insufficient_available_balance(session) -> None:
    from tutor_api.billing.service import InsufficientFundsError, reserve

    user = session.query(User).filter_by(username="learner").one()
    profile = usable_profile(session, "insufficient-model")

    with pytest.raises(InsufficientFundsError):
        reserve(session, user.id, "run-insufficient", Decimal("0.01"), profile.id)

    assert session.query(Wallet).count() == 1


def test_reservation_requires_an_enabled_usage_capable_profile(session) -> None:
    from tutor_api.billing.service import InvalidUsageError, reserve

    user = session.query(User).filter_by(username="learner").one()
    disabled_profile = ProviderProfile(
        profile_key="disabled-model",
        provider="example",
        model="disabled-model",
        display_name="已停用模型",
        supports_usage=True,
        enabled=False,
    )
    session.add(disabled_profile)
    session.flush()

    with pytest.raises(InvalidUsageError, match="enabled usage-capable"):
        reserve(session, user.id, "run-disabled", Decimal("1"), disabled_profile.id)

    assert session.query(WalletReservation).count() == 0


def test_repeated_reservation_request_returns_the_existing_reservation(session) -> None:
    from tutor_api.billing.service import reserve

    user = session.query(User).filter_by(username="learner").one()
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    session.add(
        LedgerEntry(
            wallet_id=wallet.id,
            amount=Decimal("3"),
            entry_type=LedgerEntryType.RECHARGE,
            snapshot={},
        )
    )
    session.flush()
    profile = usable_profile(session, "repeat-model")

    first = reserve(session, user.id, "run-repeat", Decimal("2"), profile.id)
    second = reserve(session, user.id, "run-repeat", Decimal("2"), profile.id)

    assert second.id == first.id
    assert session.query(WalletReservation).filter_by(request_id="run-repeat").count() == 1

    other_user = User(
        email="other@example.com",
        username="other",
        password_hash="not-used-by-wallet-tests",
    )
    session.add(other_user)
    session.flush()
    with pytest.raises(ValueError, match="another wallet"):
        reserve(session, other_user.id, "run-repeat", Decimal("2"), profile.id)


def test_settlement_releases_unused_reservation_and_uses_decimal_snapshots(session) -> None:
    from tutor_api.billing.schemas import VerifiedUsage
    from tutor_api.billing.service import reserve, settle, wallet_balance

    user = session.query(User).filter_by(username="learner").one()
    wallet = Wallet(user_id=user.id)
    session.add_all(
        [
            wallet,
            ProviderProfile(
                profile_key="example-model",
                provider="example",
                model="chat-1",
                display_name="示例模型",
                supports_usage=True,
                enabled=True,
            ),
        ]
    )
    session.flush()
    profile = session.query(ProviderProfile).filter_by(profile_key="example-model").one()
    session.add_all(
        [
            LedgerEntry(
                wallet_id=wallet.id,
                amount=Decimal("10.00"),
                entry_type=LedgerEntryType.RECHARGE,
                snapshot={},
            ),
            PriceVersion(
                provider_profile_id=profile.id,
                effective_at=datetime.now(UTC) - timedelta(minutes=1),
                source_url="https://example.test/pricing",
                currency="CNY",
                input_unit_price=Decimal("1"),
                cached_input_unit_price=Decimal("0"),
                output_unit_price=Decimal("3"),
                unit_size=1000,
            ),
        ]
    )
    session.flush()

    reservation = reserve(session, user.id, "run-settle", Decimal("10.00"), profile.id)
    profile.enabled = False
    session.flush()
    retry_reservation = reserve(session, user.id, "run-settle", Decimal("10.00"), profile.id)
    assert retry_reservation.id == reservation.id
    result = settle(
        session,
        reservation.id,
        VerifiedUsage(
            provider_profile_id=profile.id,
            input_units=1000,
            cached_input_units=0,
            output_units=500,
            verified=True,
        ),
    )

    assert result.charged_amount == Decimal("2.50000000")
    assert wallet_balance(session, user.id) == Decimal("7.50000000")
    retry = settle(
        session,
        reservation.id,
        VerifiedUsage(
            provider_profile_id=profile.id,
            input_units=1000,
            cached_input_units=0,
            output_units=500,
            verified=True,
        ),
    )
    assert retry.ledger_entry_id == result.ledger_entry_id
    reservation_row = session.get(WalletReservation, reservation.id)
    assert reservation_row is not None
    assert reservation_row.state.value == "settled"
    assert reservation_row.price_snapshot["currency"] == "CNY"
    assert reservation_row.provider_profile_id == profile.id


def test_settlement_rejects_usage_for_a_different_profile_than_the_reservation(session) -> None:
    from tutor_api.billing.schemas import VerifiedUsage
    from tutor_api.billing.service import InvalidUsageError, reserve, settle

    user = session.query(User).filter_by(username="learner").one()
    wallet = Wallet(user_id=user.id)
    selected_profile = usable_profile(session, "selected-model")
    supplied_profile = usable_profile(session, "supplied-model")
    session.add(wallet)
    session.flush()
    session.add_all(
        [
            LedgerEntry(
                wallet_id=wallet.id,
                amount=Decimal("2"),
                entry_type=LedgerEntryType.RECHARGE,
                snapshot={},
            ),
            PriceVersion(
                provider_profile_id=supplied_profile.id,
                effective_at=datetime.now(UTC) - timedelta(minutes=1),
                source_url="https://example.test/pricing",
                currency="CNY",
                input_unit_price=Decimal("1"),
                cached_input_unit_price=Decimal("0"),
                output_unit_price=Decimal("0"),
                unit_size=1000,
            ),
        ]
    )
    session.flush()
    reservation = reserve(
        session, user.id, "run-profile-mismatch", Decimal("2"), selected_profile.id
    )

    with pytest.raises(InvalidUsageError, match="reserved provider profile"):
        settle(
            session,
            reservation.id,
            VerifiedUsage(
                provider_profile_id=supplied_profile.id,
                input_units=1000,
                cached_input_units=0,
                output_units=0,
                verified=True,
            ),
        )

    assert session.query(LedgerEntry).filter_by(reservation_id=reservation.id).count() == 0


def test_repeated_settlement_request_is_idempotent(session) -> None:
    from tutor_api.billing.schemas import VerifiedUsage
    from tutor_api.billing.service import reserve, settle

    user = session.query(User).filter_by(username="learner").one()
    wallet = Wallet(user_id=user.id)
    profile = ProviderProfile(
        profile_key="idempotent-model",
        provider="example",
        model="chat-1",
        display_name="示例模型",
        supports_usage=True,
        enabled=True,
    )
    session.add_all([wallet, profile])
    session.flush()
    session.add_all(
        [
            LedgerEntry(
                wallet_id=wallet.id,
                amount=Decimal("5"),
                entry_type=LedgerEntryType.RECHARGE,
                snapshot={},
            ),
            PriceVersion(
                provider_profile_id=profile.id,
                effective_at=datetime.now(UTC) - timedelta(minutes=1),
                source_url="https://example.test/pricing",
                currency="CNY",
                input_unit_price=Decimal("1"),
                cached_input_unit_price=Decimal("0"),
                output_unit_price=Decimal("0"),
                unit_size=1000,
            ),
        ]
    )
    session.flush()
    reservation = reserve(session, user.id, "run-idempotent", Decimal("2"), profile.id)
    usage = VerifiedUsage(
        provider_profile_id=profile.id,
        input_units=1000,
        cached_input_units=0,
        output_units=0,
        verified=True,
    )

    first = settle(session, reservation.id, usage)
    second = settle(session, reservation.id, usage)

    assert second.ledger_entry_id == first.ledger_entry_id
    assert session.query(LedgerEntry).filter_by(reservation_id=reservation.id).count() == 1


def test_release_is_idempotent_and_never_creates_consumption(session) -> None:
    from tutor_api.billing.service import release, reserve

    user = session.query(User).filter_by(username="learner").one()
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    session.add(
        LedgerEntry(
            wallet_id=wallet.id,
            amount=Decimal("2"),
            entry_type=LedgerEntryType.RECHARGE,
            snapshot={},
        )
    )
    session.flush()
    profile = usable_profile(session, "release-model")
    reservation = reserve(session, user.id, "run-release", Decimal("2"), profile.id)

    assert release(session, reservation.id).released is True
    assert release(session, reservation.id).released is True
    assert session.query(LedgerEntry).filter_by(reservation_id=reservation.id).count() == 0


def test_settlement_rejects_usage_not_verified_by_a_provider_adapter(session) -> None:
    from tutor_api.billing.schemas import VerifiedUsage
    from tutor_api.billing.service import InvalidUsageError, reserve, settle

    user = session.query(User).filter_by(username="learner").one()
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    session.add(
        LedgerEntry(
            wallet_id=wallet.id,
            amount=Decimal("1"),
            entry_type=LedgerEntryType.RECHARGE,
            snapshot={},
        )
    )
    session.flush()
    profile = usable_profile(session, "unverified-model")
    reservation = reserve(session, user.id, "run-unverified", Decimal("1"), profile.id)

    with pytest.raises(InvalidUsageError, match="verified"):
        settle(
            session,
            reservation.id,
            VerifiedUsage(
                provider_profile_id=profile.id,
                input_units=0,
                cached_input_units=0,
                output_units=0,
            ),
        )


def test_settlement_converts_current_fx_and_preserves_fx_snapshot(session) -> None:
    from tutor_api.billing.schemas import VerifiedUsage
    from tutor_api.billing.service import reserve, settle

    user = session.query(User).filter_by(username="learner").one()
    wallet = Wallet(user_id=user.id)
    profile = ProviderProfile(
        profile_key="usd-model",
        provider="example",
        model="chat-usd",
        display_name="美元模型",
        supports_usage=True,
        enabled=True,
    )
    session.add_all([wallet, profile])
    session.flush()
    session.add_all(
        [
            LedgerEntry(
                wallet_id=wallet.id,
                amount=Decimal("10"),
                entry_type=LedgerEntryType.RECHARGE,
                snapshot={},
            ),
            PriceVersion(
                provider_profile_id=profile.id,
                effective_at=datetime.now(UTC) - timedelta(minutes=1),
                source_url="https://example.test/usd-pricing",
                currency="USD",
                input_unit_price=Decimal("1"),
                cached_input_unit_price=Decimal("0"),
                output_unit_price=Decimal("0"),
                unit_size=1000,
            ),
            FxVersion(
                base_currency="USD",
                quote_currency="CNY",
                effective_at=datetime.now(UTC) - timedelta(minutes=1),
                rate=Decimal("7.2"),
                source_url="https://example.test/usd-cny",
            ),
        ]
    )
    session.flush()
    reservation = reserve(session, user.id, "run-fx", Decimal("10"), profile.id)

    result = settle(
        session,
        reservation.id,
        VerifiedUsage(
            provider_profile_id=profile.id,
            input_units=1000,
            cached_input_units=0,
            output_units=0,
            verified=True,
        ),
    )

    assert result.charged_amount == Decimal("7.20000000")
    saved = session.get(WalletReservation, reservation.id)
    assert saved is not None
    assert saved.fx_snapshot["rate"] == "7.20000000"


def test_postgres_concurrent_first_wallet_creation_is_idempotent() -> None:
    """Exercise the first-wallet race with two real PostgreSQL transactions when supplied."""

    postgres_url = os.environ.get("TEST_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("TEST_POSTGRES_URL is not configured")

    from tutor_api.billing.service import _wallet_for_update

    engine = create_engine_from_url(postgres_url, app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as database_session:
        user = User(
            email=f"concurrent-{uuid4()}@example.com",
            username=f"concurrent-{uuid4()}",
            password_hash="not-used-by-wallet-tests",
        )
        database_session.add(user)
        database_session.flush()
        user_id = user.id

    insert_barrier = Barrier(2)

    def synchronize_first_insert(*args) -> None:
        statement = args[2]
        if statement.startswith("INSERT INTO wallets"):
            insert_barrier.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", synchronize_first_insert)
    try:
        def create_wallet() -> object:
            with factory.begin() as database_session:
                return _wallet_for_update(database_session, user_id).id

        with ThreadPoolExecutor(max_workers=2) as executor:
            wallet_ids = list(executor.map(lambda _: create_wallet(), range(2)))
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_first_insert)

    with factory() as database_session:
        assert len(set(wallet_ids)) == 1
        assert database_session.query(Wallet).filter_by(user_id=user_id).count() == 1
    engine.dispose()
