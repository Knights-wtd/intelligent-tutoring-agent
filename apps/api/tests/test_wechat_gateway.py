"""WeChat Pay APIv3 Native gateway: request signing, platform certs, callbacks."""

import base64
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import tutor_api.billing.models  # noqa: F401
from tutor_api.billing.gateways import (
    GatewayCallback,
    InvalidPaymentNotifyError,
    PaymentGatewayNotConfiguredError,
    PaymentRequestError,
    WechatPayNativeGateway,
    build_payment_gateway,
)
from tutor_api.billing.models import LedgerEntry
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.main import create_app

APIV3_KEY = "0123456789abcdef0123456789abcdef"
MCH_ID = "1900006000"
APP_ID = "wx8888888888888888"
MCH_SERIAL = "TEST-MCH-SERIAL-0001"
PLATFORM_SERIAL = "PLATFORM-SERIAL-0001"


def _rsa_key_pair(common_name: str) -> tuple[rsa.RSAPrivateKey, str, str]:
    """Generate an RSA key plus a self-signed PEM certificate (WeChat uses certs)."""

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    return key, private_pem, cert_pem


def _encrypted_platform_certificate(platform_cert_pem: str, serial: str) -> dict[str, str]:
    return {
        "serial_no": serial,
        "encrypt_certificate": {
            "algorithm": "AEAD_AES_256_GCM",
            "associated_data": "certificate",
            "nonce": "certnonce12",
            "ciphertext": base64.b64encode(
                AESGCM(APIV3_KEY.encode("utf-8")).encrypt(
                    b"certnonce12", platform_cert_pem.encode("utf-8"), b"certificate"
                )
            ).decode("ascii"),
        },
    }


def _make_gateway(
    *,
    native_code_url: str | None = None,
    native_payload: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[WechatPayNativeGateway, rsa.RSAPrivateKey]:
    """Build a gateway over a mock transport; also returns the platform key.

    The native-order response is signed with the platform key exactly like a
    real WeChat Pay response, so response verification is exercised too.
    """

    _, mch_private_pem, _ = _rsa_key_pair("merchant")
    platform_key, _, platform_cert_pem = _rsa_key_pair("wechatpay-platform")
    if transport is None:
        resolved_code_url = native_code_url or f"weixin://wxpay/bizpayurl?pr={uuid4().hex}"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v3/certificates":
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            _encrypted_platform_certificate(platform_cert_pem, PLATFORM_SERIAL)
                        ]
                    },
                )
            if request.url.path == "/v3/pay/transactions/native":
                payload_body = json.dumps(
                    native_payload or {"code_url": resolved_code_url}
                ).encode("utf-8")
                timestamp = str(int(time.time()))
                nonce = "respnonce01"
                return httpx.Response(
                    200,
                    content=payload_body,
                    headers={
                        "Content-Type": "application/json",
                        "Wechatpay-Serial": PLATFORM_SERIAL,
                        "Wechatpay-Signature": _sign_platform(
                            platform_key, timestamp, nonce, payload_body
                        ),
                        "Wechatpay-Timestamp": timestamp,
                        "Wechatpay-Nonce": nonce,
                    },
                )
            return httpx.Response(404, json={"code": "FAIL", "message": "not found"})

        transport = httpx.MockTransport(handler)
    gateway = WechatPayNativeGateway(
        mch_id=MCH_ID,
        app_id=APP_ID,
        mch_serial_no=MCH_SERIAL,
        mch_private_key_pem=mch_private_pem,
        apiv3_key=APIV3_KEY,
        gateway_url="https://api.mch.weixin.qq.com",
        notify_base_url="https://api.example.com",
        http_client=httpx.Client(transport=transport),
    )
    return gateway, platform_key


def _sign_platform(platform_key: rsa.RSAPrivateKey, timestamp: str, nonce: str, body: bytes) -> str:
    material = f"{timestamp}\n{nonce}\n".encode() + body + b"\n"
    signature = platform_key.sign(material, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


def _encrypted_transaction_resource(
    *, out_trade_no: str, transaction_id: str, total_cents: int, trade_state: str
) -> dict[str, object]:
    transaction = {
        "mchid": MCH_ID,
        "appid": APP_ID,
        "out_trade_no": out_trade_no,
        "transaction_id": transaction_id,
        "trade_state": trade_state,
        "amount": {"total": total_cents, "payer_total": total_cents, "currency": "CNY"},
    }
    ciphertext = base64.b64encode(
        AESGCM(APIV3_KEY.encode("utf-8")).encrypt(
            b"notifynonce1", json.dumps(transaction).encode("utf-8"), b"transaction"
        )
    ).decode("ascii")
    return {
        "original_type": "transaction",
        "algorithm": "AEAD_AES_256_GCM",
        "ciphertext": ciphertext,
        "associated_data": "transaction",
        "nonce": "notifynonce1",
    }


def _signed_headers(platform_key: rsa.RSAPrivateKey, body: bytes, nonce: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "Wechatpay-Serial": PLATFORM_SERIAL,
        "Wechatpay-Signature": _sign_platform(platform_key, timestamp, nonce, body),
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": nonce,
    }


def test_wechat_gateway_signs_requests_and_returns_code_url() -> None:
    code_url = f"weixin://wxpay/bizpayurl?pr={uuid4().hex}"
    gateway, _ = _make_gateway(native_code_url=code_url)

    class _FakeOrder:
        out_trade_no = f"R{uuid4().hex}"
        amount = Decimal("88.50")

    creation = gateway.create_payment(_FakeOrder())  # type: ignore[arg-type]
    assert creation.provider == "wechat"
    assert creation.mode == "qrcode"
    assert creation.code_url == code_url
    assert creation.pay_url is None


def test_wechat_gateway_rejects_gateway_failures_and_bad_code_urls() -> None:
    def failing_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/certificates":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(400, json={"code": "PARAM_ERROR", "message": "金额错误"})

    gateway, _ = _make_gateway(transport=httpx.MockTransport(failing_handler))

    class _FakeOrder:
        out_trade_no = f"R{uuid4().hex}"
        amount = Decimal("10.00")

    with pytest.raises(PaymentRequestError):
        gateway.create_payment(_FakeOrder())  # type: ignore[arg-type]

    gateway2, _ = _make_gateway(native_payload={"code_url": "https://evil.example.com"})
    with pytest.raises(PaymentRequestError):
        gateway2.create_payment(_FakeOrder())  # type: ignore[arg-type]


def test_wechat_callback_signature_and_decryption() -> None:
    gateway, platform_key = _make_gateway()
    out_trade_no = f"R{uuid4().hex}"
    body = json.dumps(
        {
            "id": "evt-1",
            "resource": _encrypted_transaction_resource(
                out_trade_no=out_trade_no,
                transaction_id="1000000202682900000001",
                total_cents=3000,
                trade_state="SUCCESS",
            ),
        }
    ).encode("utf-8")

    notification = gateway.verify_notify(
        GatewayCallback(headers=_signed_headers(platform_key, body, "n1"), body=body, form={})
    )
    assert notification.paid is True
    assert notification.out_trade_no == out_trade_no
    assert notification.trade_no == "1000000202682900000001"
    assert notification.total_amount == Decimal("30.00")
    assert notification.payload()["provider"] == "wechat"


def test_wechat_callback_rejects_forgery_staleness_and_foreign_signatures() -> None:
    gateway, platform_key = _make_gateway()
    body = json.dumps(
        {
            "id": "evt-2",
            "resource": _encrypted_transaction_resource(
                out_trade_no=f"R{uuid4().hex}",
                transaction_id="1000000202682900000002",
                total_cents=100,
                trade_state="SUCCESS",
            ),
        }
    ).encode("utf-8")

    # Forged signature.
    forged = {
        "Wechatpay-Serial": PLATFORM_SERIAL,
        "Wechatpay-Signature": base64.b64encode(b"forged").decode("ascii"),
        "Wechatpay-Timestamp": str(int(time.time())),
        "Wechatpay-Nonce": "n2",
    }
    with pytest.raises(InvalidPaymentNotifyError):
        gateway.verify_notify(GatewayCallback(headers=forged, body=body, form={}))

    # Stale timestamp (replay window exceeded).
    stale_timestamp = str(int(time.time()) - 400)
    stale = {
        "Wechatpay-Serial": PLATFORM_SERIAL,
        "Wechatpay-Signature": _sign_platform(platform_key, stale_timestamp, "n3", body),
        "Wechatpay-Timestamp": stale_timestamp,
        "Wechatpay-Nonce": "n3",
    }
    with pytest.raises(InvalidPaymentNotifyError):
        gateway.verify_notify(GatewayCallback(headers=stale, body=body, form={}))

    # Unknown platform certificate serial (not in /v3/certificates).
    unknown = dict(_signed_headers(platform_key, body, "n4"), **{"Wechatpay-Serial": "UNKNOWN"})
    with pytest.raises(InvalidPaymentNotifyError):
        gateway.verify_notify(GatewayCallback(headers=unknown, body=body, form={}))

    # The certificate served for a serial must be the one that signed the
    # callback: sign with one key, publish a certificate for a different key.
    other_key, _, _ = _rsa_key_pair("other-platform")
    third_key, _, third_cert_pem = _rsa_key_pair("third-platform")

    def other_serial_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/certificates":
            return httpx.Response(
                200,
                json={"data": [_encrypted_platform_certificate(third_cert_pem, "OTHER-SERIAL")]},
            )
        return httpx.Response(404)

    gateway_other, _ = _make_gateway(transport=httpx.MockTransport(other_serial_handler))
    wrong_platform = {
        "Wechatpay-Serial": "OTHER-SERIAL",
        "Wechatpay-Signature": _sign_platform(other_key, str(int(time.time())), "n5", body),
        "Wechatpay-Timestamp": str(int(time.time())),
        "Wechatpay-Nonce": "n5",
    }
    del third_key
    with pytest.raises(InvalidPaymentNotifyError):
        gateway_other.verify_notify(GatewayCallback(headers=wrong_platform, body=body, form={}))


def test_wechat_non_success_trade_states_do_not_credit() -> None:
    gateway, platform_key = _make_gateway()
    body = json.dumps(
        {
            "id": "evt-3",
            "resource": _encrypted_transaction_resource(
                out_trade_no=f"R{uuid4().hex}",
                transaction_id="1000000202682900000003",
                total_cents=1000,
                trade_state="NOTPAY",
            ),
        }
    ).encode("utf-8")
    notification = gateway.verify_notify(
        GatewayCallback(headers=_signed_headers(platform_key, body, "n6"), body=body, form={})
    )
    assert notification.paid is False


def test_wechat_notify_endpoint_verifies_and_credits_exactly_once() -> None:
    code_url = f"weixin://wxpay/bizpayurl?pr={uuid4().hex}"
    gateway, platform_key = _make_gateway(native_code_url=code_url)
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    # Valid-shaped credentials let the app build its real gateway; the mock
    # gateway below is then swapped in so no network access happens.
    _, placeholder_private_pem, _ = _rsa_key_pair("placeholder-merchant")
    settings = Settings(
        app_env="test",
        payment_provider="wechat",  # type: ignore[call-arg]
        wechat_mch_id=MCH_ID,
        wechat_app_id=APP_ID,
        wechat_mch_serial_no=MCH_SERIAL,
        wechat_mch_private_key=SecretStr(placeholder_private_pem),
        wechat_apiv3_key=SecretStr(APIV3_KEY),
        wechat_notify_origin="https://api.example.com",
    )
    app = create_app(settings, sessionmaker(bind=engine))
    app.state.payment_gateway = gateway
    client = TestClient(app)
    try:
        register_response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "wechat-user@example.com",
                "username": "wechat-user",
                "password": "Correct horse battery staple 9",
            },
        )
        assert register_response.status_code == 201

        created = client.post(
            "/api/v1/billing/recharge-orders",
            json={"provider": "wechat", "amount": "30.00"},
        )
        assert created.status_code == 201
        body_json = created.json()
        assert body_json["state"] == "pending"
        assert body_json["code_url"] == code_url
        assert body_json["mock_confirmable"] is False

        out_trade_no = body_json["out_trade_no"]
        notify_body = json.dumps(
            {
                "id": "evt-4",
                "resource": _encrypted_transaction_resource(
                    out_trade_no=out_trade_no,
                    transaction_id="1000000202682900000004",
                    total_cents=3000,
                    trade_state="SUCCESS",
                ),
            }
        ).encode("utf-8")
        headers = _signed_headers(platform_key, notify_body, "n7")

        first = client.post(
            "/api/v1/billing/payments/wechat/notify", content=notify_body, headers=headers
        )
        assert first.status_code == 200
        assert first.json()["code"] == "SUCCESS"

        # Replayed notification must not double-credit.
        replay = client.post(
            "/api/v1/billing/payments/wechat/notify", content=notify_body, headers=headers
        )
        assert replay.status_code == 200
        assert replay.json()["code"] == "SUCCESS"

        me = client.get("/api/v1/billing/me").json()
        assert str(me["balance"]) == "30.00000000"
        with sessionmaker(bind=engine)() as session:
            rows = session.scalars(select(LedgerEntry)).all()
        assert len([row for row in rows if row.entry_type.value == "recharge"]) == 1

        # Forged notification must be rejected without crediting.
        forged = dict(headers, **{"Wechatpay-Signature": base64.b64encode(b"bad").decode("ascii")})
        rejected = client.post(
            "/api/v1/billing/payments/wechat/notify", content=notify_body, headers=forged
        )
        assert rejected.status_code == 400
        assert rejected.json()["code"] == "FAIL"

        order_state = client.get(
            f"/api/v1/billing/recharge-orders/{body_json['id']}"
        ).json()["state"]
        assert order_state == "paid"
    finally:
        client.close()
        engine.dispose()


def test_wechat_settings_fail_fast_without_credentials() -> None:
    settings = Settings(app_env="test", payment_provider="wechat")  # type: ignore[call-arg]
    with pytest.raises(PaymentGatewayNotConfiguredError):
        build_payment_gateway(settings)


def test_wechat_apiv3_key_must_be_32_characters() -> None:
    _, merchant_pem, _ = _rsa_key_pair("merchant")
    with pytest.raises(PaymentGatewayNotConfiguredError):
        WechatPayNativeGateway(
            mch_id=MCH_ID,
            app_id=APP_ID,
            mch_serial_no=MCH_SERIAL,
            mch_private_key_pem=merchant_pem,
            apiv3_key="too-short",
            gateway_url="https://api.mch.weixin.qq.com",
            notify_base_url="https://api.example.com",
        )
