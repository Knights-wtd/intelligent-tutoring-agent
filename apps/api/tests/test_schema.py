from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.billing.models import (
    LedgerEntry,
    LedgerEntryType,
    RechargeRecord,
    Wallet,
    WalletReservation,
)
from tutor_api.classrooms.models import Classroom, ClassroomMembership, ClassroomRole
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.providers.models import FxVersion, PriceVersion, ProviderProfile
from tutor_api.spaces.models import Space, SpaceKind


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    active_session = factory()
    try:
        yield active_session
    finally:
        active_session.close()
        engine.dispose()


def usage_profile(session: Session, key: str) -> ProviderProfile:
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


def test_schema_enforces_one_personal_space_per_owner(session: Session) -> None:
    user = User(email="teacher@example.com", username="teacher", password_hash="hash")
    session.add(user)
    session.flush()
    session.add_all(
        [
            Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="我的空间"),
            Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="第二空间"),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_schema_enforces_one_membership_per_classroom_and_user(session: Session) -> None:
    user = User(email="teacher@example.com", username="teacher", password_hash="hash")
    session.add(user)
    session.flush()
    classroom_space = Space(owner_id=user.id, kind=SpaceKind.CLASSROOM, name="七年级数学")
    session.add(classroom_space)
    session.flush()
    classroom = Classroom(owner_id=user.id, space_id=classroom_space.id, name="七年级数学")
    session.add(classroom)
    session.flush()
    session.add_all(
        [
            ClassroomMembership(
                classroom_id=classroom.id, user_id=user.id, role=ClassroomRole.OWNER
            ),
            ClassroomMembership(
                classroom_id=classroom.id, user_id=user.id, role=ClassroomRole.TEACHER
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_wallet_ledger_amounts_are_decimal(session: Session) -> None:
    user = User(email="learner@example.com", username="learner", password_hash="hash")
    session.add(user)
    session.flush()
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    entry = LedgerEntry(
        wallet_id=wallet.id,
        amount=Decimal("10.00"),
        entry_type=LedgerEntryType.RECHARGE,
    )
    session.add(entry)
    session.commit()

    assert entry.amount == Decimal("10.00000000")


def test_reservation_request_id_is_unique(session: Session) -> None:
    user = User(email="learner@example.com", username="learner", password_hash="hash")
    session.add(user)
    session.flush()
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    profile = usage_profile(session, "duplicate-reservation")
    session.add_all(
        [
            WalletReservation(
                wallet_id=wallet.id,
                provider_profile_id=profile.id,
                request_id="request-1",
                reserved_amount=Decimal("1"),
            ),
            WalletReservation(
                wallet_id=wallet.id,
                provider_profile_id=profile.id,
                request_id="request-1",
                reserved_amount=Decimal("1"),
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_reservation_state_rejects_unknown_value(session: Session) -> None:
    user = User(email="learner@example.com", username="learner", password_hash="hash")
    session.add(user)
    session.flush()
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    profile = usage_profile(session, "invalid-reservation-state")
    session.add(
        WalletReservation(
            wallet_id=wallet.id,
            provider_profile_id=profile.id,
            request_id="request-invalid-state",
            reserved_amount=Decimal("1"),
            state="unknown",  # type: ignore[arg-type]
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_ledger_entry_type_rejects_unknown_value(session: Session) -> None:
    user = User(email="learner@example.com", username="learner", password_hash="hash")
    session.add(user)
    session.flush()
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    session.add(
        LedgerEntry(
            wallet_id=wallet.id,
            amount=Decimal("1"),
            entry_type="unknown",  # type: ignore[arg-type]
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_ledger_reservation_must_belong_to_its_wallet(session: Session) -> None:
    first_user = User(email="first@example.com", username="first", password_hash="hash")
    second_user = User(email="second@example.com", username="second", password_hash="hash")
    session.add_all([first_user, second_user])
    session.flush()
    first_wallet = Wallet(user_id=first_user.id)
    second_wallet = Wallet(user_id=second_user.id)
    session.add_all([first_wallet, second_wallet])
    session.flush()
    reservation = WalletReservation(
        wallet_id=first_wallet.id,
        provider_profile_id=usage_profile(session, "cross-wallet").id,
        request_id="cross-wallet",
        reserved_amount=Decimal("1"),
    )
    session.add(reservation)
    session.flush()
    session.add(
        LedgerEntry(
            wallet_id=second_wallet.id,
            reservation_id=reservation.id,
            amount=Decimal("-1"),
            entry_type=LedgerEntryType.CONSUMPTION,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_recharge_ledger_entry_must_belong_to_its_wallet(session: Session) -> None:
    first_user = User(email="first@example.com", username="first", password_hash="hash")
    second_user = User(email="second@example.com", username="second", password_hash="hash")
    session.add_all([first_user, second_user])
    session.flush()
    first_wallet = Wallet(user_id=first_user.id)
    second_wallet = Wallet(user_id=second_user.id)
    session.add_all([first_wallet, second_wallet])
    session.flush()
    entry = LedgerEntry(
        wallet_id=first_wallet.id, amount=Decimal("1"), entry_type=LedgerEntryType.RECHARGE
    )
    session.add(entry)
    session.flush()
    session.add(
        RechargeRecord(
            wallet_id=second_wallet.id,
            ledger_entry_id=entry.id,
            external_reference="cross-wallet-primary",
            reason="test",
            created_by_user_id=first_user.id,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_recharge_reversal_entry_must_belong_to_its_wallet(session: Session) -> None:
    first_user = User(email="first@example.com", username="first", password_hash="hash")
    second_user = User(email="second@example.com", username="second", password_hash="hash")
    session.add_all([first_user, second_user])
    session.flush()
    first_wallet = Wallet(user_id=first_user.id)
    second_wallet = Wallet(user_id=second_user.id)
    session.add_all([first_wallet, second_wallet])
    session.flush()
    primary_entry = LedgerEntry(
        wallet_id=second_wallet.id, amount=Decimal("1"), entry_type=LedgerEntryType.RECHARGE
    )
    reversal_entry = LedgerEntry(
        wallet_id=first_wallet.id, amount=Decimal("-1"), entry_type=LedgerEntryType.REVERSAL
    )
    session.add_all([primary_entry, reversal_entry])
    session.flush()
    session.add(
        RechargeRecord(
            wallet_id=second_wallet.id,
            ledger_entry_id=primary_entry.id,
            reversal_ledger_entry_id=reversal_entry.id,
            external_reference="cross-wallet-reversal",
            reason="test",
            created_by_user_id=second_user.id,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_unit_price", Decimal("-0.00000001")),
        ("cached_input_unit_price", Decimal("-0.00000001")),
        ("output_unit_price", Decimal("-0.00000001")),
        ("unit_size", 0),
    ],
)
def test_price_version_rejects_invalid_price_or_unit_size(
    session: Session, field: str, value: Decimal | int
) -> None:
    profile = ProviderProfile(
        profile_key="openai-gpt", provider="openai", model="gpt-test", display_name="测试模型"
    )
    session.add(profile)
    session.flush()
    price = PriceVersion(
        provider_profile_id=profile.id,
        effective_at=datetime.now(UTC),
        source_url="https://example.test/prices",
        currency="USD",
        input_unit_price=Decimal("1"),
        cached_input_unit_price=Decimal("0.5"),
        output_unit_price=Decimal("2"),
        unit_size=1_000_000,
    )
    setattr(price, field, value)
    session.add(price)

    with pytest.raises(IntegrityError):
        session.commit()


def test_fx_version_rejects_non_positive_rate(session: Session) -> None:
    session.add(
        FxVersion(
            base_currency="USD",
            quote_currency="CNY",
            effective_at=datetime.now(UTC),
            rate=Decimal("0"),
            source_url="https://example.test/fx",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_reservation_rejects_non_positive_amount(session: Session) -> None:
    user = User(email="learner@example.com", username="learner", password_hash="hash")
    session.add(user)
    session.flush()
    wallet = Wallet(user_id=user.id)
    session.add(wallet)
    session.flush()
    profile = usage_profile(session, "zero-reservation")
    session.add(
        WalletReservation(
            wallet_id=wallet.id,
            provider_profile_id=profile.id,
            request_id="zero-reservation",
            reserved_amount=Decimal("0"),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.filterwarnings(
    "ignore:No path_separator found in configuration:DeprecationWarning"
)
def test_migration_upgrade_and_downgrade_preserve_wallet_schema(tmp_path) -> None:
    database_path = tmp_path / "schema.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    inspector = inspect(engine)
    assert {
        "provider_profiles",
        "price_versions",
        "fx_versions",
        "wallets",
        "wallet_reservations",
        "ledger_entries",
        "recharge_records",
    }.issubset(inspector.get_table_names())
    assert {
        "ck_wallet_reservation_state",
        "ck_wallet_reservation_amount_positive",
    }.issubset(
        {
            constraint["name"]
            for constraint in inspector.get_check_constraints("wallet_reservations")
        }
    )
    assert {
        "ck_ledger_entry_type",
    }.issubset(
        {constraint["name"] for constraint in inspector.get_check_constraints("ledger_entries")}
    )
    recharge_checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspector.get_check_constraints("recharge_records")
    }
    assert "ck_recharge_record_reversal_audit_complete" in recharge_checks
    assert "reversal_ledger_entry_id" in recharge_checks[
        "ck_recharge_record_reversal_audit_complete"
    ]
    assert "reversed_at" in recharge_checks["ck_recharge_record_reversal_audit_complete"]
    assert {
        "ck_price_version_input_unit_price_nonnegative",
        "ck_price_version_cached_input_unit_price_nonnegative",
        "ck_price_version_output_unit_price_nonnegative",
        "ck_price_version_unit_size_positive",
    }.issubset(
        {constraint["name"] for constraint in inspector.get_check_constraints("price_versions")}
    )
    assert {"ck_fx_version_rate_positive"}.issubset(
        {constraint["name"] for constraint in inspector.get_check_constraints("fx_versions")}
    )
    assert {
        (
            ("reservation_id", "wallet_id"),
            "wallet_reservations",
            ("id", "wallet_id"),
        ),
    }.issubset(
        {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
            )
            for constraint in inspector.get_foreign_keys("ledger_entries")
        }
    )
    assert {
        (("provider_profile_id",), "provider_profiles", ("id",)),
    }.issubset(
        {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
            )
            for constraint in inspector.get_foreign_keys("wallet_reservations")
        }
    )
    assert {
        (("ledger_entry_id", "wallet_id"), "ledger_entries", ("id", "wallet_id")),
        (("reversal_ledger_entry_id", "wallet_id"), "ledger_entries", ("id", "wallet_id")),
    }.issubset(
        {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
            )
            for constraint in inspector.get_foreign_keys("recharge_records")
        }
    )

    engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    assert not {
        "provider_profiles",
        "price_versions",
        "fx_versions",
        "wallets",
        "wallet_reservations",
        "ledger_entries",
        "recharge_records",
    }.intersection(inspect(engine).get_table_names())
    engine.dispose()


def test_legacy_sqlite_revision_upgrades_to_current_head(tmp_path) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")

    command.upgrade(config, "0003_bind_reservations_to_provider")
    command.upgrade(config, "head")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "0005_reversal_audit_group"
    finally:
        engine.dispose()

@pytest.mark.filterwarnings(
    "ignore:No path_separator found in configuration:DeprecationWarning"
)
def test_migration_backfills_and_releases_historic_unbound_reservations(tmp_path) -> None:
    database_path = tmp_path / "historic-reservations.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "0002_provider_wallet")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    metadata = MetaData()
    metadata.reflect(bind=engine, only=["users", "wallets", "wallet_reservations"])
    user_id, wallet_id, reservation_id = (str(uuid4()), str(uuid4()), str(uuid4()))
    with engine.begin() as connection:
        connection.execute(
            metadata.tables["users"].insert(),
            {
                "id": user_id,
                "email": "historic@example.com",
                "username": "historic",
                "password_hash": "hash",
            },
        )
        connection.execute(
            metadata.tables["wallets"].insert(),
            {"id": wallet_id, "user_id": user_id, "currency": "CNY"},
        )
        connection.execute(
            metadata.tables["wallet_reservations"].insert(),
            {
                "id": reservation_id,
                "wallet_id": wallet_id,
                "request_id": "historic-request",
                "reserved_amount": Decimal("1"),
                "state": "active",
            },
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    upgraded = MetaData()
    upgraded.reflect(bind=engine, only=["provider_profiles", "wallet_reservations"])
    with engine.connect() as connection:
        reservation = connection.execute(
            select(upgraded.tables["wallet_reservations"]).where(
                upgraded.tables["wallet_reservations"].c.id == reservation_id
            )
        ).mappings().one()
        profile = connection.execute(
            select(upgraded.tables["provider_profiles"]).where(
                upgraded.tables["provider_profiles"].c.id == reservation["provider_profile_id"]
            )
        ).mappings().one()

    assert reservation["state"] == "released"
    assert reservation["released_at"] is not None
    assert profile["profile_key"] == "__legacy_reservation_unavailable__"
    assert profile["enabled"] is False
    assert profile["supports_usage"] is False
    engine.dispose()


@pytest.mark.filterwarnings(
    "ignore:No path_separator found in configuration:DeprecationWarning"
)
def test_reversal_audit_migration_round_trip_preserves_0004_contract(tmp_path) -> None:
    database_path = tmp_path / "reversal-audit.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    def audit_check_sql() -> str:
        engine = create_engine(config.get_main_option("sqlalchemy.url"))
        try:
            checks = {
                constraint["name"]: constraint["sqltext"]
                for constraint in inspect(engine).get_check_constraints("recharge_records")
            }
            return checks["ck_recharge_record_reversal_audit_complete"]
        finally:
            engine.dispose()

    command.upgrade(config, "0004_recharge_reversal_audit")
    assert "reversal_ledger_entry_id" not in audit_check_sql()

    command.upgrade(config, "0005_reversal_audit_group")
    assert "reversal_ledger_entry_id" in audit_check_sql()
    assert "reversed_at" in audit_check_sql()

    command.downgrade(config, "0004_recharge_reversal_audit")
    assert "reversal_ledger_entry_id" not in audit_check_sql()


def test_price_version_is_unique_per_profile_and_effective_at(session: Session) -> None:
    profile = ProviderProfile(
        profile_key="openai-gpt",
        provider="openai",
        model="gpt-test",
        display_name="测试模型",
    )
    session.add(profile)
    session.flush()
    effective_at = datetime.now(UTC)
    session.add_all(
        [
            PriceVersion(
                provider_profile_id=profile.id,
                effective_at=effective_at,
                source_url="https://example.test/prices",
                currency="USD",
                input_unit_price=Decimal("1"),
                cached_input_unit_price=Decimal("0.5"),
                output_unit_price=Decimal("2"),
                unit_size=1_000_000,
            ),
            PriceVersion(
                provider_profile_id=profile.id,
                effective_at=effective_at,
                source_url="https://example.test/prices",
                currency="USD",
                input_unit_price=Decimal("1"),
                cached_input_unit_price=Decimal("0.5"),
                output_unit_price=Decimal("2"),
                unit_size=1_000_000,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()
