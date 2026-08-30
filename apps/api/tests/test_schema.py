from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import tutor_api.agent.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
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
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.providers.models import FxVersion, PriceVersion, ProviderProfile
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.tutor.models import TutorConversation, TutorMessage, TutorMessageRole


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


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
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
    assert (
        "reversal_ledger_entry_id" in recharge_checks["ck_recharge_record_reversal_audit_complete"]
    )
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
        assert version == "0016_agent_workspace"
    finally:
        engine.dispose()


def test_short_lived_task7_revision_upgrades_to_current_head(tmp_path) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    database_path = tmp_path / "short-lived.db"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "0003_bind_reservations_to_provider")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num = '0003_reservation_provider'")
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "0016_agent_workspace"
    finally:
        engine.dispose()


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
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
        reservation = (
            connection.execute(
                select(upgraded.tables["wallet_reservations"]).where(
                    upgraded.tables["wallet_reservations"].c.id == reservation_id
                )
            )
            .mappings()
            .one()
        )
        profile = (
            connection.execute(
                select(upgraded.tables["provider_profiles"]).where(
                    upgraded.tables["provider_profiles"].c.id == reservation["provider_profile_id"]
                )
            )
            .mappings()
            .one()
        )

    assert reservation["state"] == "released"
    assert reservation["released_at"] is not None
    assert profile["profile_key"] == "__legacy_reservation_unavailable__"
    assert profile["enabled"] is False
    assert profile["supports_usage"] is False
    engine.dispose()


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
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


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_versioned_knowledge_migration_round_trip(tmp_path) -> None:
    database_path = tmp_path / "versioned-knowledge.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    knowledge_tables = {
        "knowledge_bases",
        "documents",
        "document_versions",
        "pages",
        "blocks",
        "index_versions",
        "chunks",
        "ingestion_jobs",
        "knowledge_upload_requests",
    }

    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        inspector = inspect(engine)
        assert knowledge_tables.issubset(inspector.get_table_names())
        assert "uq_active_index_per_knowledge_base" in {
            index["name"] for index in inspector.get_indexes("index_versions")
        }
        assert {
            "ck_chunk_embedding_dimension_sqlite",
            "ck_chunk_sha256",
        }.issubset({constraint["name"] for constraint in inspector.get_check_constraints("chunks")})
        assert {
            "ck_ingestion_attempt_within_limit",
            "ck_ingestion_lease_matches_state",
            "ck_ingestion_completed_at_matches_state",
            "ck_ingestion_started_at_matches_state",
            "ck_ingestion_target_matches_kind",
            "ck_ingestion_checkpoint_object_sqlite",
        }.issubset(
            {constraint["name"] for constraint in inspector.get_check_constraints("ingestion_jobs")}
        )
        chunk_foreign_keys = {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
                constraint["options"].get("ondelete"),
            )
            for constraint in inspector.get_foreign_keys("chunks")
        }
        assert (
            (
                "index_version_id",
                "knowledge_base_id",
                "space_id",
                "embedding_dimension",
                "index_signature",
            ),
            "index_versions",
            (
                "id",
                "knowledge_base_id",
                "space_id",
                "embedding_dimension",
                "index_signature",
            ),
            "CASCADE",
        ) in chunk_foreign_keys
        assert (
            ("document_version_id", "knowledge_base_id", "space_id"),
            "document_versions",
            ("id", "knowledge_base_id", "space_id"),
            "CASCADE",
        ) in chunk_foreign_keys
        columns = {column["name"]: column for column in inspector.get_columns("chunks")}
        assert columns["knowledge_base_id"]["nullable"] is False
        assert "JSON" in str(columns["embedding"]["type"]).upper()
        assert columns["embedding"]["nullable"] is False
        version_columns = {
            column["name"]: column for column in inspector.get_columns("document_versions")
        }
        assert version_columns["knowledge_base_id"]["nullable"] is False
        job_columns = {column["name"]: column for column in inspector.get_columns("ingestion_jobs")}
        assert job_columns["page_id"]["nullable"] is True
        assert "JSON" in str(job_columns["checkpoint"]["type"]).upper()
        assert job_columns["checkpoint"]["nullable"] is False
        with engine.connect() as connection:
            trigger_names = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                )
            }
            assert "trg_chunks_validate_embedding_insert" in trigger_names
            assert "trg_chunks_validate_embedding_update" in trigger_names
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
                "0016_agent_workspace"
            )
    finally:
        engine.dispose()

    command.downgrade(config, "0005_reversal_audit_group")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        assert not knowledge_tables.intersection(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
                "0005_reversal_audit_group"
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        assert knowledge_tables.issubset(inspect(engine).get_table_names())
        with engine.connect() as connection:
            trigger_names = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                )
            }
        assert "trg_chunks_validate_embedding_insert" in trigger_names
        assert "trg_chunks_validate_embedding_update" in trigger_names
    finally:
        engine.dispose()


def _normalized_sql(sql: str) -> str:
    return " ".join(sql.lower().split()).rstrip(";")


def _sqlite_embedding_contract(engine) -> tuple[dict[str, str], dict[str, str]]:
    inspector = inspect(engine)
    checks = {
        constraint["name"]: _normalized_sql(constraint["sqltext"])
        for constraint in inspector.get_check_constraints("chunks")
        if constraint["name"].startswith("ck_chunk_embedding_dimension")
    }
    with engine.connect() as connection:
        triggers = {
            row.name: _normalized_sql(row.sql)
            for row in connection.execute(
                text(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type = 'trigger' "
                    "AND name LIKE 'trg_chunks_validate_embedding_%'"
                )
            )
        }
    return checks, triggers


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_create_all_and_migrated_sqlite_embedding_contracts_match(tmp_path) -> None:
    create_all_engine = create_engine("sqlite://")
    Base.metadata.create_all(create_all_engine)
    migration_path = tmp_path / "embedding-contract.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{migration_path.as_posix()}")
    command.upgrade(config, "head")
    migrated_engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        create_all_checks, create_all_triggers = _sqlite_embedding_contract(create_all_engine)
        migrated_checks, migrated_triggers = _sqlite_embedding_contract(migrated_engine)

        assert (
            create_all_checks
            == migrated_checks
            == {
                "ck_chunk_embedding_dimension_sqlite": (
                    "json_valid(embedding) and json_type(embedding) = 'array' "
                    "and json_array_length(embedding) = embedding_dimension"
                )
            }
        )
        assert (
            set(create_all_triggers)
            == set(migrated_triggers)
            == {
                "trg_chunks_validate_embedding_insert",
                "trg_chunks_validate_embedding_update",
            }
        )
        assert create_all_triggers == migrated_triggers
        assert all(
            "abs(cast(value as real)) > 1.7976931348623157e308" in sql
            for sql in create_all_triggers.values()
        )
    finally:
        create_all_engine.dispose()
        migrated_engine.dispose()


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_postgresql_offline_sql_enables_pgvector_and_uses_vector_type() -> None:
    output = StringIO()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"), output_buffer=output)
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://offline:offline@localhost:5432/offline",
    )

    command.upgrade(config, "head", sql=True)

    sql = " ".join(output.getvalue().lower().split())
    assert "create extension if not exists vector" in sql
    assert "embedding vector not null" in sql
    assert "vector_dims(embedding) = embedding_dimension" in sql
    assert "constraint ck_chunk_embedding_dimension_postgresql" in sql
    assert "checkpoint jsonb not null" in sql
    assert "jsonb_typeof(checkpoint) = 'object'" in sql
    assert (
        "foreign key(index_version_id, knowledge_base_id, space_id, "
        "embedding_dimension, index_signature)"
    ) in sql
    assert (
        "references index_versions (id, knowledge_base_id, space_id, "
        "embedding_dimension, index_signature)"
    ) in sql
    assert ("foreign key(document_version_id, knowledge_base_id, space_id)") in sql
    assert "create trigger trg_chunks_validate_embedding" not in sql


def _raw_migrated_chunk_insert(connection, embedding_json: str, *, ordinal: int) -> str:
    chunk_id = uuid4().hex
    connection.exec_driver_sql(
        """
        INSERT INTO chunks (
            id, space_id, knowledge_base_id, index_version_id,
            document_version_id, ordinal, source_pointer, content_sha256,
            content, embedding_dimension, index_signature, embedding
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk_id,
            uuid4().hex,
            uuid4().hex,
            uuid4().hex,
            uuid4().hex,
            ordinal,
            f"raw-migrated:{uuid4()}",
            "a" * 64,
            "raw migrated embedding",
            8,
            "raw:index:v1",
            embedding_json,
        ),
    )
    return chunk_id


@pytest.mark.parametrize(
    "embedding_json",
    ["[1e309,0,0,0,0,0,0,0]", "[-1e999,0,0,0,0,0,0,0]"],
)
@pytest.mark.parametrize("operation", ["insert", "update"])
@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_migrated_sqlite_raw_sql_rejects_non_finite_embeddings(
    tmp_path, embedding_json: str, operation: str
) -> None:
    database_path = tmp_path / f"raw-infinite-{operation}-{uuid4().hex}.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 0
            finite_chunk_id = _raw_migrated_chunk_insert(
                connection, "[1e300,0,0,0,0,0,0,0]", ordinal=0
            )
            if operation == "insert":
                with pytest.raises(IntegrityError, match="invalid embedding element"):
                    _raw_migrated_chunk_insert(connection, embedding_json, ordinal=1)
            else:
                connection.exec_driver_sql(
                    "UPDATE chunks SET embedding = ? WHERE id = ?",
                    ("[-1e300,0,0,0,0,0,0,0]", finite_chunk_id),
                )
                with pytest.raises(IntegrityError, match="invalid embedding element"):
                    connection.exec_driver_sql(
                        "UPDATE chunks SET embedding = ? WHERE id = ?",
                        (embedding_json, finite_chunk_id),
                    )
                assert (
                    connection.exec_driver_sql(
                        "SELECT embedding FROM chunks WHERE id = ?",
                        (finite_chunk_id,),
                    )
                    .scalar()
                    .startswith("[-1e300")
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize("integer_value", [-9223372036854775808, 9223372036854775807])
@pytest.mark.parametrize("operation", ["insert", "update"])
@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_migrated_sqlite_raw_sql_accepts_integer_embedding_boundaries(
    tmp_path, integer_value: int, operation: str
) -> None:
    database_path = tmp_path / f"raw-integer-{operation}-{uuid4().hex}.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 0
            embedding_json = f"[{integer_value},0,0,0,0,0,0,0]"
            if operation == "insert":
                chunk_id = _raw_migrated_chunk_insert(connection, embedding_json, ordinal=0)
            else:
                chunk_id = _raw_migrated_chunk_insert(connection, "[0,0,0,0,0,0,0,0]", ordinal=0)
                connection.exec_driver_sql(
                    "UPDATE chunks SET embedding = ? WHERE id = ?",
                    (embedding_json, chunk_id),
                )
            stored_embedding = connection.exec_driver_sql(
                "SELECT embedding FROM chunks WHERE id = ?", (chunk_id,)
            ).scalar()
            assert str(integer_value) in stored_embedding
    finally:
        engine.dispose()


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_migrated_sqlite_rejects_cross_knowledge_base_chunks(tmp_path) -> None:
    database_path = tmp_path / "cross-kb-chunks.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    metadata = MetaData()
    metadata.reflect(engine)
    assert "knowledge_base_id" in metadata.tables["document_versions"].c
    assert "knowledge_base_id" in metadata.tables["chunks"].c

    user_id = uuid4().hex
    space_id = uuid4().hex
    first_kb_id = uuid4().hex
    second_kb_id = uuid4().hex
    first_document_id = uuid4().hex
    second_document_id = uuid4().hex
    first_version_id = uuid4().hex
    second_version_id = uuid4().hex
    first_page_id = uuid4().hex
    second_page_id = uuid4().hex
    first_block_id = uuid4().hex
    second_block_id = uuid4().hex
    index_id = uuid4().hex
    tables = metadata.tables
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(
            tables["users"].insert(),
            {
                "id": user_id,
                "email": "migrated-cross-kb@example.com",
                "username": "migrated-cross-kb",
                "password_hash": "hash",
            },
        )
        connection.execute(
            tables["spaces"].insert(),
            {
                "id": space_id,
                "owner_id": user_id,
                "kind": "personal",
                "name": "migrated cross KB",
            },
        )
        for knowledge_base_id, name in (
            (first_kb_id, "first"),
            (second_kb_id, "second"),
        ):
            connection.execute(
                tables["knowledge_bases"].insert(),
                {
                    "id": knowledge_base_id,
                    "space_id": space_id,
                    "owner_user_id": user_id,
                    "created_by_user_id": user_id,
                    "name": name,
                    "state": "active",
                },
            )
        for document_id, knowledge_base_id, suffix in (
            (first_document_id, first_kb_id, "first"),
            (second_document_id, second_kb_id, "second"),
        ):
            connection.execute(
                tables["documents"].insert(),
                {
                    "id": document_id,
                    "space_id": space_id,
                    "knowledge_base_id": knowledge_base_id,
                    "owner_user_id": user_id,
                    "created_by_user_id": user_id,
                    "title": f"{suffix}.pdf",
                    "source_kind": "upload",
                    "source_key": f"uploads/{suffix}.pdf",
                    "state": "active",
                },
            )
        for version_id, document_id, knowledge_base_id, hash_character in (
            (first_version_id, first_document_id, first_kb_id, "a"),
            (second_version_id, second_document_id, second_kb_id, "b"),
        ):
            connection.execute(
                tables["document_versions"].insert(),
                {
                    "id": version_id,
                    "space_id": space_id,
                    "knowledge_base_id": knowledge_base_id,
                    "document_id": document_id,
                    "version_number": 1,
                    "content_sha256": hash_character * 64,
                    "object_key": f"objects/{version_id}",
                    "content_type": "application/pdf",
                    "state": "ready",
                    "created_by_user_id": user_id,
                },
            )
        for page_id, version_id, hash_character in (
            (first_page_id, first_version_id, "c"),
            (second_page_id, second_version_id, "d"),
        ):
            connection.execute(
                tables["pages"].insert(),
                {
                    "id": page_id,
                    "space_id": space_id,
                    "document_version_id": version_id,
                    "page_number": 1,
                    "source_pointer": "page:1",
                    "content_sha256": hash_character * 64,
                    "source_metadata": {},
                },
            )
        for block_id, page_id, hash_character in (
            (first_block_id, first_page_id, "e"),
            (second_block_id, second_page_id, "f"),
        ):
            connection.execute(
                tables["blocks"].insert(),
                {
                    "id": block_id,
                    "space_id": space_id,
                    "page_id": page_id,
                    "ordinal": 0,
                    "kind": "paragraph",
                    "source_pointer": "page:1/block:0",
                    "content_sha256": hash_character * 64,
                    "text": "content",
                },
            )
        connection.execute(
            tables["index_versions"].insert(),
            {
                "id": index_id,
                "space_id": space_id,
                "knowledge_base_id": first_kb_id,
                "version_number": 1,
                "state": "ready",
                "parser_signature": "parser:v1",
                "ocr_signature": "ocr:none",
                "chunking_signature": "chunk:v1",
                "embedding_backend": "hash",
                "embedding_model": "hash-v1",
                "embedding_dimension": 8,
                "embedding_contract_signature": "embedding:v1",
                "index_signature": "index:v1",
                "created_by_user_id": user_id,
            },
        )
        connection.execute(
            tables["chunks"].insert(),
            {
                "id": uuid4().hex,
                "space_id": space_id,
                "knowledge_base_id": first_kb_id,
                "index_version_id": index_id,
                "document_version_id": first_version_id,
                "page_id": first_page_id,
                "block_id": first_block_id,
                "ordinal": 0,
                "source_pointer": "first:chunk:0",
                "content_sha256": "1" * 64,
                "content": "valid same-KB chunk",
                "embedding_dimension": 8,
                "index_signature": "index:v1",
                "embedding": [0.0] * 8,
            },
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                tables["chunks"].insert(),
                {
                    "id": uuid4().hex,
                    "space_id": space_id,
                    "knowledge_base_id": first_kb_id,
                    "index_version_id": index_id,
                    "document_version_id": second_version_id,
                    "page_id": second_page_id,
                    "block_id": second_block_id,
                    "ordinal": 1,
                    "source_pointer": "second:chunk:0",
                    "content_sha256": "2" * 64,
                    "content": "invalid cross-KB chunk",
                    "embedding_dimension": 8,
                    "index_signature": "index:v1",
                    "embedding": [0.0] * 8,
                },
            )
    engine.dispose()


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_migrated_knowledge_base_names_are_unique_per_space(tmp_path) -> None:
    database_path = tmp_path / "knowledge-base-name-uniqueness.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    metadata = MetaData()
    metadata.reflect(engine)
    tables = metadata.tables

    unique_constraints = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints("knowledge_bases")
    }
    assert unique_constraints["uq_knowledge_base_name_in_space"] == ("space_id", "name")

    first_user_id = uuid4().hex
    second_user_id = uuid4().hex
    first_space_id = uuid4().hex
    second_space_id = uuid4().hex
    with engine.begin() as connection:
        for user_id, suffix in (
            (first_user_id, "first"),
            (second_user_id, "second"),
        ):
            connection.execute(
                tables["users"].insert(),
                {
                    "id": user_id,
                    "email": f"kb-name-{suffix}@example.com",
                    "username": f"kb-name-{suffix}",
                    "password_hash": "hash",
                },
            )
        for space_id, owner_id, suffix in (
            (first_space_id, first_user_id, "first"),
            (second_space_id, second_user_id, "second"),
        ):
            connection.execute(
                tables["spaces"].insert(),
                {
                    "id": space_id,
                    "owner_id": owner_id,
                    "kind": "personal",
                    "name": f"KB name {suffix}",
                },
            )
        connection.execute(
            tables["knowledge_bases"].insert(),
            {
                "id": uuid4().hex,
                "space_id": first_space_id,
                "owner_user_id": first_user_id,
                "created_by_user_id": first_user_id,
                "name": "shared-name",
                "state": "active",
            },
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                tables["knowledge_bases"].insert(),
                {
                    "id": uuid4().hex,
                    "space_id": first_space_id,
                    "owner_user_id": first_user_id,
                    "created_by_user_id": first_user_id,
                    "name": "shared-name",
                    "state": "active",
                },
            )

    with engine.begin() as connection:
        connection.execute(
            tables["knowledge_bases"].insert(),
            {
                "id": uuid4().hex,
                "space_id": second_space_id,
                "owner_user_id": second_user_id,
                "created_by_user_id": second_user_id,
                "name": "shared-name",
                "state": "active",
            },
        )

    engine.dispose()


def create_identity_and_knowledge_base(
    session: Session, *, suffix: str | None = None
) -> tuple[User, Space, KnowledgeBase]:
    identity_suffix = suffix or uuid4().hex
    user = User(
        email=f"tutor-{identity_suffix}@example.com",
        username=f"tutor-{identity_suffix}"[:32],
        password_hash="hash",
    )
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name=f"Tutor {identity_suffix}")
    session.add(space)
    session.flush()
    knowledge_base = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name=f"Tutor KB {identity_suffix}",
    )
    session.add(knowledge_base)
    session.flush()
    return user, space, knowledge_base


def test_tutor_conversation_accepts_scoped_user_message(session: Session) -> None:
    user, space, knowledge_base = create_identity_and_knowledge_base(session)
    conversation = TutorConversation(
        user_id=user.id,
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        title="路径损耗",
    )
    session.add(conversation)
    session.flush()
    session.add(
        TutorMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            role=TutorMessageRole.USER,
            content="解释路径损耗",
        )
    )
    session.flush()

    assert conversation.messages[0].role is TutorMessageRole.USER
    assert conversation.messages[0].citations == []


@pytest.mark.parametrize("mismatched_field", ["user_id", "space_id", "knowledge_base_id"])
def test_tutor_message_must_match_all_conversation_scope_fields(
    session: Session, mismatched_field: str
) -> None:
    first_user, first_space, first_knowledge_base = create_identity_and_knowledge_base(
        session, suffix=f"first-{mismatched_field}"
    )
    second_user, second_space, second_knowledge_base = create_identity_and_knowledge_base(
        session, suffix=f"second-{mismatched_field}"
    )
    conversation = TutorConversation(
        user_id=first_user.id,
        space_id=first_space.id,
        knowledge_base_id=first_knowledge_base.id,
        title="租户隔离",
    )
    session.add(conversation)
    session.flush()
    message_fields = {
        "conversation_id": conversation.id,
        "user_id": first_user.id,
        "space_id": first_space.id,
        "knowledge_base_id": first_knowledge_base.id,
        "role": TutorMessageRole.USER,
        "content": "越界消息",
    }
    message_fields[mismatched_field] = {
        "user_id": second_user.id,
        "space_id": second_space.id,
        "knowledge_base_id": second_knowledge_base.id,
    }[mismatched_field]
    session.add(TutorMessage(**message_fields))

    with pytest.raises(IntegrityError):
        session.flush()


def test_tutor_conversation_knowledge_base_must_belong_to_space(session: Session) -> None:
    first_user, first_space, _ = create_identity_and_knowledge_base(session, suffix="first-space")
    _, _, second_knowledge_base = create_identity_and_knowledge_base(session, suffix="second-space")
    session.add(
        TutorConversation(
            user_id=first_user.id,
            space_id=first_space.id,
            knowledge_base_id=second_knowledge_base.id,
            title="跨空间会话",
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_tutor_conversation_cascades_messages(session: Session) -> None:
    user, space, knowledge_base = create_identity_and_knowledge_base(session)
    conversation = TutorConversation(
        user_id=user.id,
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        title="级联删除",
    )
    message = TutorMessage(
        conversation=conversation,
        user_id=user.id,
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        role=TutorMessageRole.ASSISTANT,
        content="回答",
    )
    session.add(conversation)
    session.flush()
    message_id = message.id

    session.delete(conversation)
    session.flush()

    assert session.scalar(select(TutorMessage).where(TutorMessage.id == message_id)) is None


@pytest.mark.parametrize("title", ["", "   "])
def test_tutor_conversation_rejects_empty_title(session: Session, title: str) -> None:
    user, space, knowledge_base = create_identity_and_knowledge_base(session)
    session.add(
        TutorConversation(
            user_id=user.id,
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            title=title,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    ("overrides", "content"),
    [
        ({}, ""),
        ({}, "   "),
        ({"prompt_tokens": -1}, "问题"),
        ({"completion_tokens": -1}, "回答"),
    ],
)
def test_tutor_message_rejects_empty_content_or_negative_usage(
    session: Session, overrides: dict[str, int], content: str
) -> None:
    user, space, knowledge_base = create_identity_and_knowledge_base(session)
    conversation = TutorConversation(
        user_id=user.id,
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        title="约束",
    )
    session.add(conversation)
    session.flush()
    session.add(
        TutorMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            role=TutorMessageRole.USER,
            content=content,
            **overrides,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_tutor_migration_matches_model_metadata(tmp_path) -> None:
    database_path = tmp_path / "tutor-schema.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        inspector = inspect(engine)
        assert {"tutor_conversations", "tutor_messages"}.issubset(inspector.get_table_names())
        assert {
            "agent_sessions",
            "agent_turns",
            "agent_session_events",
            "agent_workspace_grants",
            "agent_audit_events",
            "agent_provider_settings",
            "agent_usage_records",
            "vault_files",
            "vault_change_sets",
            "vault_change_entries",
            "vault_sync_cursors",
            "semantic_index_plans",
        }.issubset(inspector.get_table_names())
        assert {
            "vault_file_id",
            "vault_relative_path",
            "content_hash",
            "sync_state",
            "last_change_set_id",
            "is_tombstoned",
            "tombstoned_at",
        }.issubset({column["name"] for column in inspector.get_columns("markdown_notes")})
        assert {
            "change_set_id",
            "agent_session_id",
            "agent_turn_id",
            "tool_call_id",
            "change_source",
            "before_hash",
            "after_hash",
        }.issubset({column["name"] for column in inspector.get_columns("markdown_revisions")})
        assert {
            "planner_provider",
            "planner_model",
            "planner_schema_version",
            "planner_prompt_hash",
            "source_change_set_id",
            "source_snapshot_hash",
            "activation_status",
        }.issubset({column["name"] for column in inspector.get_columns("index_versions")})
        message_foreign_keys = {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in inspector.get_foreign_keys("tutor_messages")
        }
        assert (
            (
                "conversation_id",
                "user_id",
                "space_id",
                "knowledge_base_id",
            ),
            "tutor_conversations",
            ("id", "user_id", "space_id", "knowledge_base_id"),
            "CASCADE",
        ) in message_foreign_keys
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
                "0016_agent_workspace"
            )
    finally:
        engine.dispose()
