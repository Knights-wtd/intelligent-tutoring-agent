"""Self-service recharge orders: gateway notifications, idempotent credit, RSA2."""

import base64
from decimal import Decimal
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import tutor_api.billing.models  # noqa: F401
from tutor_api.billing.gateways import (
    AlipayPagePaymentGateway,
    GatewayCallback,
    InvalidPaymentNotifyError,
    MockPaymentGateway,
    PaymentGatewayNotConfiguredError,
    _signing_material,
    build_payment_gateway,
    mock_notification_fields,
)
from tutor_api.billing.models import LedgerEntry, RechargeOrder
from tutor_api.billing.service import confirm_recharge_payment
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.main import create_app


def make_client(
    payment_provider: str = "mock",
) -> tuple[TestClient, object, Settings]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    settings = Settings(app_env="test", payment_provider=payment_provider)  # type: ignore[call-arg]
    client = TestClient(create_app(settings, sessionmaker(bind=engine)))
    return client, engine, settings


def register(client: TestClient, username: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "password": "Correct horse battery staple 9",
        },
    )
    assert response.status_code == 201
    return response.json()["user"]


def _ledger_rows(engine: object) -> list[tuple[str, str]]:
    with sessionmaker(bind=engine)() as session:
        rows = session.scalars(select(LedgerEntry)).all()
        return [(row.entry_type.value, str(row.amount)) for row in rows]


def _rsa_key_pair() -> tuple[rsa.RSAPrivateKey, str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("utf-8")
    )
    return private_key, private_pem, public_pem


def test_recharge_order_requires_authentication() -> None:
    client, engine, _ = make_client()
    try:
        response = client.post(
            "/api/v1/billing/recharge-orders",
            json={"provider": "mock", "amount": "50.00"},
        )
        assert response.status_code == 401
    finally:
        client.close()
        engine.dispose()


def test_mock_order_lifecycle_credits_balance_exactly_once() -> None:
    client, engine, _ = make_client()
    try:
        register(client, "recharger")
        created = client.post(
            "/api/v1/billing/recharge-orders",
            json={"provider": "mock", "amount": "50.00"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["state"] == "pending"
        assert body["mock_confirmable"] is True
        assert body["amount"] == "50.00"
        assert body["out_trade_no"].startswith("R")
        assert body["pay_url"] is None

        confirmed = client.post(
            f"/api/v1/billing/recharge-orders/{body['id']}/mock-confirm"
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["state"] == "paid"
        assert confirmed.json()["mock_confirmable"] is False

        # Repeat notifications must not double-credit.
        repeat = client.post(f"/api/v1/billing/recharge-orders/{body['id']}/mock-confirm")
        assert repeat.status_code == 200
        assert repeat.json()["state"] == "paid"

        me = client.get("/api/v1/billing/me").json()
        assert Decimal(str(me["balance"])) == Decimal("50.00")
        recharge_rows = [row for row in _ledger_rows(engine) if row[0] == "recharge"]
        assert recharge_rows == [("recharge", "50.00000000")]
        assert me["entries"][0]["entry_type"] == "recharge"
    finally:
        client.close()
        engine.dispose()


def test_recharge_order_rejects_out_of_range_amounts() -> None:
    client, engine, _ = make_client()
    try:
        register(client, "amount-checker")
        too_small = client.post(
            "/api/v1/billing/recharge-orders",
            json={"provider": "mock", "amount": "0.50"},
        )
        too_large = client.post(
            "/api/v1/billing/recharge-orders",
            json={"provider": "mock", "amount": "10001.00"},
        )
        assert too_small.status_code == 422
        assert too_large.status_code == 422
    finally:
        client.close()
        engine.dispose()


def test_recharge_orders_are_private_to_their_owner() -> None:
    client, engine, _ = make_client()
    try:
        register(client, "order-owner")
        created = client.post(
            "/api/v1/billing/recharge-orders",
            json={"provider": "mock", "amount": "10.00"},
        ).json()
        client.cookies.clear()
        register(client, "order-outsider")
        response = client.get(f"/api/v1/billing/recharge-orders/{created['id']}")
        assert response.status_code == 404
    finally:
        client.close()
        engine.dispose()


def test_alipay_gateway_signs_and_verifies_rsa2() -> None:
    merchant_key, merchant_pem, merchant_public_pem = _rsa_key_pair()
    gateway = AlipayPagePaymentGateway(
        app_id="2026test",
        app_private_key_pem=merchant_pem,
        alipay_public_key_pem=merchant_public_pem,
        gateway_url="https://openapi-sandbox.dl.alipaydev.com/gateway.do",
        notify_base_url="https://api.example.com",
        return_url="https://app.example.com",
    )

    class _FakeOrder:
        out_trade_no = f"R{uuid4().hex}"
        amount = Decimal("88.50")

    creation = gateway.create_payment(_FakeOrder())  # type: ignore[arg-type]
    assert creation.pay_url is not None
    assert creation.pay_url.startswith("https://openapi-sandbox.dl.alipaydev.com/gateway.do?")
    assert "out_trade_no" in creation.pay_url

    # Alipay posts form fields; emulate the platform signing with the same key pair.
    notify_fields = {
        "app_id": "2026test",
        "trade_status": "TRADE_SUCCESS",
        "out_trade_no": _FakeOrder.out_trade_no,
        "trade_no": "2026082922001000000001234567",
        "total_amount": "88.50",
        "sign_type": "RSA2",
        "sign": "",
    }
    material = _signing_material(notify_fields, excluded_keys=frozenset({"sign", "sign_type"}))
    signature = merchant_key.sign(material, padding.PKCS1v15(), hashes.SHA256())
    notify_fields["sign"] = base64.b64encode(signature).decode("ascii")

    notification = gateway.verify_notify(
        GatewayCallback(headers={}, body=b"", form=notify_fields)
    )
    assert notification.paid is True
    assert notification.total_amount == Decimal("88.50")
    assert notification.out_trade_no == _FakeOrder.out_trade_no


def test_alipay_gateway_rejects_tampered_or_foreign_notifications() -> None:
    _, merchant_pem, merchant_public_pem = _rsa_key_pair()
    gateway = AlipayPagePaymentGateway(
        app_id="2026test",
        app_private_key_pem=merchant_pem,
        alipay_public_key_pem=merchant_public_pem,
        gateway_url="https://openapi.alipay.com/gateway.do",
        notify_base_url="https://api.example.com",
        return_url="https://app.example.com",
    )
    fields = {
        "app_id": "2026test",
        "trade_status": "TRADE_SUCCESS",
        "out_trade_no": f"R{uuid4().hex}",
        "trade_no": "2026082922001000000009999999",
        "total_amount": "10.00",
        "sign_type": "RSA2",
        "sign": base64.b64encode(b"forged").decode("ascii"),
    }
    with pytest.raises(InvalidPaymentNotifyError):
        gateway.verify_notify(GatewayCallback(headers={}, body=b"", form=fields))

    foreign = dict(fields, app_id="someone-elses-app")
    with pytest.raises(InvalidPaymentNotifyError):
        gateway.verify_notify(GatewayCallback(headers={}, body=b"", form=foreign))


def test_amount_mismatch_is_never_credited() -> None:
    client, engine, _ = make_client()
    try:
        register(client, "mismatch-user")
        order = client.post(
            "/api/v1/billing/recharge-orders",
            json={"provider": "mock", "amount": "20.00"},
        ).json()
        with sessionmaker(bind=engine)() as session:
            stored = session.scalar(select(RechargeOrder))
            assert stored is not None
            notification = MockPaymentGateway().verify_notify(
                GatewayCallback(
                    headers={},
                    body=b"",
                    form={
                        "out_trade_no": stored.out_trade_no,
                        "trade_no": "MOCKMISMATCH",
                        "total_amount": "25.00",
                        "trade_status": "TRADE_SUCCESS",
                    },
                )
            )
            confirm_recharge_payment(
                session,
                out_trade_no=notification.out_trade_no,
                gateway_trade_no=notification.trade_no,
                paid_amount=notification.total_amount,
                notify_payload=notification.payload(),
            )
            session.commit()
        me = client.get("/api/v1/billing/me").json()
        assert Decimal(str(me["balance"])) == Decimal("0")
        assert _ledger_rows(engine) == []
        assert client.get(f"/api/v1/billing/recharge-orders/{order['id']}").json()[
            "state"
        ] == "paid_mismatch"
    finally:
        client.close()
        engine.dispose()


def test_build_payment_gateway_fails_fast_for_unconfigured_alipay() -> None:
    settings = Settings(app_env="test", payment_provider="alipay")  # type: ignore[call-arg]
    with pytest.raises(PaymentGatewayNotConfiguredError):
        build_payment_gateway(settings)


def test_payment_settings_default_to_mock_and_validate_gateway_url() -> None:
    settings = Settings(app_env="test")
    assert settings.payment_provider == "mock"
    with pytest.raises(ValueError):
        Settings(app_env="test", alipay_gateway_url="http://insecure.example.com")
    with pytest.raises(ValueError):
        Settings(app_env="test", alipay_notify_base_url="https://api.example.com/deep/path")


def test_alipay_notify_endpoint_is_public_and_signature_gated() -> None:
    client, engine, _ = make_client()
    try:
        # Reachable without a session cookie; on a mock deployment it acks
        # failure so a misrouted gateway retries elsewhere instead of crediting.
        response = client.post(
            "/api/v1/billing/payments/alipay/notify",
            data={"out_trade_no": "Rinvalid", "trade_no": "t", "total_amount": "1.00"},
        )
        assert response.status_code == 400
    finally:
        client.close()
        engine.dispose()


def test_recharge_order_is_part_of_metadata() -> None:
    assert "recharge_orders" in Base.metadata.tables


def test_mock_notification_fields_match_the_order() -> None:
    class _FakeOrder:
        out_trade_no = f"R{uuid4().hex}"
        amount = Decimal("12.30")

    fields = mock_notification_fields(_FakeOrder())  # type: ignore[arg-type]
    assert fields["total_amount"] == "12.30"
    assert fields["trade_status"] == "TRADE_SUCCESS"
    assert (
        MockPaymentGateway()
        .verify_notify(GatewayCallback(headers={}, body=b"", form=fields))
        .paid
        is True
    )
