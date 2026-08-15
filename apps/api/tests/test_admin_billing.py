import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import tutor_api.billing.models  # noqa: F401
from tutor_api.billing.models import LedgerEntry, LedgerEntryType, RechargeRecord
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.main import create_app


def make_client() -> tuple[TestClient, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    settings = Settings(
        app_env="test",
        platform_admin_emails=("admin@example.com",),
    )
    return TestClient(create_app(settings, sessionmaker(bind=engine))), engine


def register(client: TestClient, username: str, email: str | None = None) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email or f"{username}@example.com",
            "username": username,
            "password": "Correct horse battery staple 9",
        },
    )
    assert response.status_code == 201
    return response.json()["user"]


def login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Correct horse battery staple 9"},
    )
    assert response.status_code == 200


def test_admin_recharge_requires_authentication_and_platform_allowlist(client_and_engine) -> None:
    client, _ = client_and_engine
    learner = register(client, "learner")
    payload = {
        "user_id": learner["id"],
        "amount": "20.00",
        "external_reference": "manual-001",
        "reason": "人工充值",
    }

    client.cookies.clear()
    assert client.post("/api/v1/admin/recharges", json=payload).status_code == 401
    register(client, "not-admin")
    assert client.post("/api/v1/admin/recharges", json=payload).status_code == 403


def test_platform_admin_recharge_creates_append_only_audit_records(client_and_engine) -> None:
    client, engine = client_and_engine
    learner = register(client, "learner")
    client.cookies.clear()
    admin = register(client, "admin")

    response = client.post(
        "/api/v1/admin/recharges",
        json={
            "user_id": learner["id"],
            "amount": "20.00",
            "external_reference": "manual-001",
            "reason": "人工充值",
        },
    )

    assert response.status_code == 201
    assert response.json()["amount"] == "20.00000000"
    assert response.json()["external_reference"] == "manual-001"
    factory = sessionmaker(bind=engine)
    with factory() as session:
        record = session.query(RechargeRecord).one()
        entry = session.get(LedgerEntry, record.ledger_entry_id)
        assert entry is not None
        assert entry.entry_type == LedgerEntryType.RECHARGE
        assert entry.amount == Decimal("20.00000000")
        assert record.created_by_user_id == UUID(admin["id"])
        assert record.reversal_ledger_entry_id is None


@pytest.mark.parametrize("amount", ["0", "-1", "not-a-number"])
def test_admin_recharge_requires_a_strictly_positive_decimal_amount(
    client_and_engine, amount: str
) -> None:
    client, _ = client_and_engine
    learner = register(client, "learner")
    client.cookies.clear()
    register(client, "admin")

    response = client.post(
        "/api/v1/admin/recharges",
        json={
            "user_id": learner["id"],
            "amount": amount,
            "external_reference": f"manual-{amount}",
            "reason": "人工充值",
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field, value",
    [("external_reference", " "), ("reason", " ")],
)
def test_admin_recharge_rejects_blank_audit_fields_as_invalid_input(
    client_and_engine, field: str, value: str
) -> None:
    client, _ = client_and_engine
    learner = register(client, "learner")
    client.cookies.clear()
    register(client, "admin")
    payload = {
        "user_id": learner["id"],
        "amount": "20.00",
        "external_reference": "manual-001",
        "reason": "人工充值",
    }
    payload[field] = value

    assert client.post("/api/v1/admin/recharges", json=payload).status_code == 422


def test_admin_recharge_returns_not_found_when_target_user_is_missing(client_and_engine) -> None:
    client, _ = client_and_engine
    register(client, "admin")

    response = client.post(
        "/api/v1/admin/recharges",
        json={
            "user_id": "00000000-0000-0000-0000-000000000099",
            "amount": "20.00",
            "external_reference": "missing-user-001",
            "reason": "人工充值",
        },
    )

    assert response.status_code == 404


def test_admin_recharge_returns_conflict_for_a_reused_external_reference(client_and_engine) -> None:
    client, _ = client_and_engine
    learner = register(client, "learner")
    client.cookies.clear()
    register(client, "admin")
    payload = {
        "user_id": learner["id"],
        "amount": "20.00",
        "external_reference": "manual-duplicate-001",
        "reason": "人工充值",
    }

    assert client.post("/api/v1/admin/recharges", json=payload).status_code == 201
    assert client.post("/api/v1/admin/recharges", json=payload).status_code == 409


def test_postgres_concurrent_external_references_write_one_recharge_record() -> None:
    """The unique key remains the cross-wallet race backstop after wallet locking."""

    postgres_url = os.environ.get("TEST_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("TEST_POSTGRES_URL is not configured")

    from tutor_api.billing.service import create_manual_recharge

    engine = create_engine_from_url(postgres_url, app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    suffix = str(uuid4())
    with factory.begin() as session:
        users = [
            User(
                email=f"recharge-race-{index}-{suffix}@example.com",
                username=f"recharge-race-{index}-{suffix}",
                password_hash="not-used-by-billing-tests",
            )
            for index in range(2)
        ]
        session.add_all(users)
        session.flush()
        user_ids = [user.id for user in users]

    insert_barrier = Barrier(2)
    reference = f"race-{suffix}"

    def synchronize_recharge_insert(*args) -> None:
        if args[2].startswith("INSERT INTO recharge_records"):
            insert_barrier.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", synchronize_recharge_insert)
    try:
        def create_for(user_id: UUID) -> str:
            try:
                with factory.begin() as session:
                    create_manual_recharge(
                        session,
                        user_id=user_id,
                        amount="1",
                        external_reference=reference,
                        reason="并发回归",
                        created_by_user_id=user_id,
                    )
            except IntegrityError:
                return "duplicate"
            return "created"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(create_for, user_ids))
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_recharge_insert)

    with factory() as session:
        assert outcomes.count("created") == 1
        assert outcomes.count("duplicate") == 1
        record = session.query(RechargeRecord).filter_by(external_reference=reference).one()
        assert session.get(LedgerEntry, record.ledger_entry_id) is not None
    engine.dispose()


def test_reversal_is_one_time_and_creates_a_paired_negative_entry(client_and_engine) -> None:
    client, engine = client_and_engine
    learner = register(client, "learner")
    client.cookies.clear()
    register(client, "admin")
    recharge = client.post(
        "/api/v1/admin/recharges",
        json={
            "user_id": learner["id"],
            "amount": "20.00",
            "external_reference": "manual-001",
            "reason": "人工充值",
        },
    )
    assert recharge.status_code == 201

    reversal = client.post(
        f"/api/v1/admin/recharges/{recharge.json()['id']}/reverse",
        json={"reason": "录入错误"},
    )

    assert reversal.status_code == 201
    assert reversal.json()["amount"] == "-20.00000000"
    assert client.post(
        f"/api/v1/admin/recharges/{recharge.json()['id']}/reverse",
        json={"reason": "再次尝试"},
    ).status_code == 409
    factory = sessionmaker(bind=engine)
    with factory() as session:
        record = session.query(RechargeRecord).one()
        assert record.reversal_ledger_entry_id is not None
        reversal_entry = session.get(LedgerEntry, record.reversal_ledger_entry_id)
        assert reversal_entry is not None
        assert reversal_entry.entry_type == LedgerEntryType.REVERSAL
        assert reversal_entry.amount == Decimal("-20.00000000")
        assert reversal_entry.snapshot["reversal_of_recharge_record_id"] == str(record.id)


def test_user_billing_is_paginated_and_hides_internal_usage_details(client_and_engine) -> None:
    client, _ = client_and_engine
    learner = register(client, "learner")
    client.cookies.clear()
    register(client, "admin")
    assert client.post(
        "/api/v1/admin/recharges",
        json={
            "user_id": learner["id"],
            "amount": "20.00",
            "external_reference": "manual-001",
            "reason": "人工充值",
        },
    ).status_code == 201
    client.cookies.clear()
    login(client, "learner@example.com")

    response = client.get("/api/v1/billing/me?limit=1&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert body["balance"] == "20.00000000"
    assert body["currency"] == "CNY"
    assert body["total"] == 1
    assert len(body["entries"]) == 1
    assert "snapshot" not in response.text
    assert "token_digest" not in response.text
    assert client.get(f"/api/v1/billing/{learner['id']}").status_code == 404


@pytest.fixture
def client_and_engine():
    client, engine = make_client()
    try:
        with client:
            yield client, engine
    finally:
        engine.dispose()
