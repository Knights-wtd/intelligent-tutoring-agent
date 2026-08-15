from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import tutor_api.billing.models  # noqa: F401
from tutor_api.billing.models import LedgerEntry, LedgerEntryType, RechargeRecord
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
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
