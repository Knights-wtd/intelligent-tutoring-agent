from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.billing.models import LedgerEntry, LedgerEntryType, Wallet, WalletReservation
from tutor_api.classrooms.models import Classroom, ClassroomMembership, ClassroomRole
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.providers.models import PriceVersion, ProviderProfile
from tutor_api.spaces.models import Space, SpaceKind


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    active_session = factory()
    try:
        yield active_session
    finally:
        active_session.close()
        engine.dispose()


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
    session.add_all(
        [
            WalletReservation(
                wallet_id=wallet.id,
                request_id="request-1",
                reserved_amount=Decimal("1"),
            ),
            WalletReservation(
                wallet_id=wallet.id,
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
    session.add(
        WalletReservation(
            wallet_id=wallet.id,
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
