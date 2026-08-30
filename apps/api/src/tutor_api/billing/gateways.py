"""Payment gateway port plus Alipay (RSA2 page pay), WeChat Pay v3 (Native), and local mock.

The gateway boundary is deliberately narrow: ``create_payment`` turns a
persisted pending order into something the payer can act on (a redirect URL or
a QR code payload), and ``verify_notify`` turns an untrusted gateway callback
into a typed notification or raises. Everything else — order state
transitions, crediting, audit — lives in the billing service so no gateway can
bypass the ledger.

Alipay signing follows the RSA2 (SHA256withRSA) contract: sort the top-level
parameters, join them as ``key=value`` with ``&`` (no URL escaping inside the
signing material), sign with the merchant private key, and verify asynchronous
notifications the same way after dropping ``sign``/``sign_type`` using the
Alipay platform public key.

WeChat Pay uses APIv3 (WECHATPAY2-SHA256-RSA2048): requests are signed with
the merchant API private key over ``METHOD\\nPATH\\nTIMESTAMP\\nNONCE\\nBODY\\n``;
callbacks and responses are verified with the WeChat Pay *platform*
certificate matching the reported serial (fetched from ``/v3/certificates``
and cached), and the callback resource is an AEAD_AES_256_GCM blob encrypted
with the APIv3 key. Amounts cross the boundary in 分 (cents); this module
converts to yuan Decimals so the ledger keeps its single currency unit.

Keys and APIv3 secrets never leave the server process.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote, urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509 import load_pem_x509_certificate

from tutor_api.billing.models import RechargeOrder


class InvalidPaymentNotifyError(ValueError):
    """The callback failed signature or field validation and must not be trusted."""


class PaymentGatewayNotConfiguredError(ValueError):
    """The selected gateway is missing mandatory credentials or endpoints."""


class PaymentRequestError(RuntimeError):
    """The gateway rejected an order-creation request or an unexpected response."""


@dataclass(frozen=True, slots=True)
class GatewayCallback:
    """Everything a gateway may need from an inbound notification.

    Alipay and the mock cashier post form fields; WeChat Pay posts a JSON body
    signed through HTTP headers. Endpoints pass what they received and the
    gateway picks what it trusts.
    """

    headers: Mapping[str, str]
    body: bytes
    form: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class GatewayPaymentCreation:
    provider: str
    pay_url: str | None = None
    code_url: str | None = None
    mode: str = "redirect"


@dataclass(frozen=True, slots=True)
class GatewayNotification:
    out_trade_no: str
    trade_no: str
    total_amount: Decimal
    paid: bool
    raw: dict[str, str]

    def payload(self) -> dict[str, str]:
        """Sanitized notify payload safe to persist for audit."""

        return dict(self.raw)


_ALIPAY_SUCCESS_STATUSES = frozenset({"TRADE_SUCCESS", "TRADE_FINISHED"})
_CST = timezone(timedelta(hours=8))
_REQUEST_SIGN_EXCLUDED = frozenset({"sign"})
_NOTIFY_VERIFY_EXCLUDED = frozenset({"sign", "sign_type"})


class PaymentGateway(Protocol):
    provider: str

    def create_payment(self, order: RechargeOrder) -> GatewayPaymentCreation: ...

    def verify_notify(self, callback: GatewayCallback) -> GatewayNotification: ...


def _signing_material(
    fields: Mapping[str, str], *, excluded_keys: frozenset[str]
) -> bytes:
    """Sorted ``key=value`` pairs joined with ``&``, per the Alipay RSA2 contract.

    Request signing excludes only ``sign``; notification verification also
    excludes ``sign_type`` and empty values.
    """

    selected = [
        (key, value)
        for key, value in fields.items()
        if key not in excluded_keys and value != ""
    ]
    joined = "&".join(f"{key}={value}" for key, value in sorted(selected))
    return joined.encode("utf-8")


def _load_private_key(pem_text: str) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None)
    except (ValueError, TypeError) as error:
        raise PaymentGatewayNotConfiguredError(
            "Merchant private key must be a PEM RSA private key"
        ) from error
    if not isinstance(key, rsa.RSAPrivateKey):
        raise PaymentGatewayNotConfiguredError("Merchant private key must be an RSA key")
    return key


def _load_public_key(pem_text: str) -> rsa.RSAPublicKey:
    try:
        key = serialization.load_pem_public_key(pem_text.encode("utf-8"))
    except (ValueError, TypeError) as error:
        raise InvalidPaymentNotifyError(
            "Configured platform public key is not a PEM key"
        ) from error
    if not isinstance(key, rsa.RSAPublicKey):
        raise InvalidPaymentNotifyError("Configured platform key must be an RSA key")
    return key


def _rsa2_sign(private_key: rsa.RSAPrivateKey, material: bytes) -> str:
    signature = private_key.sign(material, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


def _rsa2_verify(public_key: rsa.RSAPublicKey, material: bytes, signature_b64: str) -> bool:
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError) as error:
        raise InvalidPaymentNotifyError("Notification signature is not valid base64") from error
    try:
        public_key.verify(signature, material, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return False
    return True


class MockPaymentGateway:
    """Local development gateway: no money moves, the UI confirms orders directly.

    ``create_payment`` returns ``mode="mock"`` so the web client knows to offer
    the simulated cashier button instead of a redirect or QR code, and
    ``verify_notify`` runs the same field validation as a real gateway so the
    crediting path is identical to production.
    """

    provider = "mock"

    def create_payment(self, order: RechargeOrder) -> GatewayPaymentCreation:
        del order
        return GatewayPaymentCreation(provider=self.provider, mode="mock")

    def verify_notify(self, callback: GatewayCallback) -> GatewayNotification:
        return _validated_notification(callback.form, expected_app_id=None)


class AlipayPagePaymentGateway:
    """Alipay PC page pay (电脑网站支付) with RSA2 request signing.

    ``notify_base_url`` is the public HTTPS base address of this API; the
    gateway posts payment results to ``{notify_base_url}/api/v1/billing/
    payments/alipay/notify``. It must be reachable from Alipay servers, so it
    is configured independently of WEB_ORIGIN.
    """

    provider = "alipay"

    def __init__(
        self,
        *,
        app_id: str,
        app_private_key_pem: str,
        alipay_public_key_pem: str,
        gateway_url: str,
        notify_base_url: str,
        return_url: str,
    ) -> None:
        self._app_id = app_id.strip()
        self._private_key = _load_private_key(app_private_key_pem)
        self._alipay_public_key = _load_public_key(alipay_public_key_pem)
        self._gateway_url = gateway_url.rstrip("/")
        self._notify_url = f"{notify_base_url.rstrip('/')}/api/v1/billing/payments/alipay/notify"
        self._return_url = return_url

    def create_payment(self, order: RechargeOrder) -> GatewayPaymentCreation:
        parameters = {
            "app_id": self._app_id,
            "method": "alipay.trade.page.pay",
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "notify_url": self._notify_url,
            "return_url": self._return_url,
            "biz_content": json.dumps(
                {
                    "out_trade_no": order.out_trade_no,
                    "product_code": "FAST_INSTANT_TRADE_PAY",
                    "subject": "知学空间积分充值",
                    "total_amount": f"{order.amount:.2f}",
                },
                ensure_ascii=False,
            ),
        }
        parameters["sign"] = _rsa2_sign(
            self._private_key, _signing_material(parameters, excluded_keys=_REQUEST_SIGN_EXCLUDED)
        )
        pay_url = f"{self._gateway_url}?{urlencode(parameters, quote_via=quote)}"
        return GatewayPaymentCreation(provider=self.provider, pay_url=pay_url, mode="redirect")

    def verify_notify(self, callback: GatewayCallback) -> GatewayNotification:
        notification = _validated_notification(callback.form, expected_app_id=self._app_id)
        material = _signing_material(callback.form, excluded_keys=_NOTIFY_VERIFY_EXCLUDED)
        sign = callback.form.get("sign", "")
        if not _rsa2_verify(self._alipay_public_key, material, sign):
            raise InvalidPaymentNotifyError("Notification signature verification failed")
        return notification


def _validated_notification(
    fields: Mapping[str, str], *, expected_app_id: str | None
) -> GatewayNotification:
    raw = {str(key): str(value) for key, value in fields.items()}
    out_trade_no = raw.get("out_trade_no", "").strip()
    trade_no = raw.get("trade_no", "").strip()
    total_amount_text = raw.get("total_amount", "").strip()
    if not out_trade_no or not trade_no:
        raise InvalidPaymentNotifyError("Notification is missing order identifiers")
    if expected_app_id is not None and raw.get("app_id", "") != expected_app_id:
        raise InvalidPaymentNotifyError("Notification app_id does not match this merchant")
    try:
        total_amount = Decimal(total_amount_text)
    except InvalidOperation as error:
        raise InvalidPaymentNotifyError("Notification total_amount is not a decimal") from error
    if total_amount <= Decimal("0"):
        raise InvalidPaymentNotifyError("Notification total_amount must be positive")
    return GatewayNotification(
        out_trade_no=out_trade_no,
        trade_no=trade_no,
        total_amount=total_amount,
        paid=raw.get("trade_status", "") in _ALIPAY_SUCCESS_STATUSES,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# WeChat Pay v3 (Native 扫码支付)
# ---------------------------------------------------------------------------

_WECHAT_SIGNATURE_SCHEMA = "WECHATPAY2-SHA256-RSA2048"
_WECHAT_CERT_PATH = "/v3/certificates"
_WECHAT_NATIVE_ORDER_PATH = "/v3/pay/transactions/native"
# Callback timestamps outside this window are rejected as replays.
_WECHAT_MAX_CALLBACK_CLOCK_SKEW_SECONDS = 300


@dataclass(frozen=True, slots=True)
class _WechatPlatformCert:
    serial_no: str
    public_key: rsa.RSAPublicKey


class _WechatPlatformCertificates:
    """Platform certificate cache keyed by serial, refreshed on unknown serials.

    WeChat Pay rotates platform certificates; the authoritative source is
    ``GET /v3/certificates``, whose entries are AES-256-GCM encrypted with the
    APIv3 key. Callbacks name the serial they were signed with, so an unknown
    serial simply triggers one refresh before we decide the callback is fake.
    """

    def __init__(
        self,
        apiv3_key: bytes,
        http_client: httpx.Client,
        request_signer: _WechatRequestSigner,
    ) -> None:
        self._apiv3_key = apiv3_key
        self._http_client = http_client
        self._request_signer = request_signer
        self._lock = threading.Lock()
        self._certs: dict[str, _WechatPlatformCert] = {}
        self._downloaded_at: float = 0.0

    def public_key_for(self, serial_no: str) -> rsa.RSAPublicKey:
        with self._lock:
            cert = self._certs.get(serial_no)
        if cert is not None:
            return cert.public_key
        self._refresh()
        with self._lock:
            cert = self._certs.get(serial_no)
        if cert is None:
            raise InvalidPaymentNotifyError(
                "Callback references an unknown WeChat Pay platform certificate serial"
            )
        return cert.public_key

    def _decrypt_certificate(self, encrypt_certificate: Mapping[str, Any]) -> str:
        try:
            ciphertext = base64.b64decode(str(encrypt_certificate["ciphertext"]))
            nonce = str(encrypt_certificate["nonce"]).encode("utf-8")
            associated = str(encrypt_certificate.get("associated_data") or "certificate")
        except (KeyError, ValueError, TypeError) as error:
            raise PaymentRequestError("Platform certificate payload is malformed") from error
        try:
            plaintext = AESGCM(self._apiv3_key).decrypt(
                nonce, ciphertext, associated.encode("utf-8")
            )
        except InvalidSignature as error:
            raise PaymentRequestError(
                "Platform certificate decryption failed; check WECHAT_APIV3_KEY"
            ) from error
        return plaintext.decode("utf-8")

    def _refresh(self) -> None:
        # One refresher at a time; others reuse whatever lands in the cache.
        with self._lock:
            if time.time() - self._downloaded_at < 5:
                return
            self._downloaded_at = time.time()
        response = self._request_signer.request("GET", _WECHAT_CERT_PATH)
        if response.status_code != 200:
            raise PaymentRequestError(
                f"WeChat Pay platform certificate download failed ({response.status_code})"
            )
        try:
            entries = response.json()["data"]
        except (ValueError, KeyError, TypeError) as error:
            raise PaymentRequestError("Platform certificate response is malformed") from error
        refreshed: dict[str, _WechatPlatformCert] = {}
        for entry in entries:
            pem = self._decrypt_certificate(entry["encrypt_certificate"])
            certificate = load_pem_x509_certificate(pem.encode("utf-8"))
            public_key = certificate.public_key()
            if not isinstance(public_key, rsa.RSAPublicKey):
                raise PaymentRequestError("Platform certificate is not an RSA certificate")
            refreshed[str(entry["serial_no"])] = _WechatPlatformCert(
                serial_no=str(entry["serial_no"]), public_key=public_key
            )
        with self._lock:
            self._certs.update(refreshed)


class _WechatRequestSigner:
    """Signs APIv3 requests with the merchant private key (SHA256withRSA)."""

    def __init__(
        self,
        *,
        mch_id: str,
        serial_no: str,
        private_key: rsa.RSAPrivateKey,
        http_client: httpx.Client,
        gateway_url: str,
    ) -> None:
        self._mch_id = mch_id
        self._serial_no = serial_no
        self._private_key = private_key
        self._http_client = http_client
        self._gateway_url = gateway_url.rstrip("/")

    def request(self, method: str, path: str, *, body: str = "") -> httpx.Response:
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        material = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n".encode()
        signature = _rsa2_sign(self._private_key, material)
        authorization = (
            f"{_WECHAT_SIGNATURE_SCHEMA} "
            f'mchid="{self._mch_id}",'
            f'nonce_str="{nonce}",'
            f'signature="{signature}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{self._serial_no}"'
        )
        return self._send(method, path, body, authorization)

    def _send(
        self, method: str, path: str, body: str, authorization: str
    ) -> httpx.Response:
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if method == "POST":
            return self._http_client.post(
                f"{self._gateway_url}{path}", content=body.encode("utf-8"), headers=headers
            )
        return self._http_client.get(f"{self._gateway_url}{path}", headers=headers)

    def verify_platform_signature(
        self,
        *,
        certificates: _WechatPlatformCertificates,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        signature = headers.get("wechatpay-signature", "")
        timestamp = headers.get("wechatpay-timestamp", "")
        nonce = headers.get("wechatpay-nonce", "")
        serial = headers.get("wechatpay-serial", "")
        if not signature or not timestamp or not nonce or not serial:
            raise InvalidPaymentNotifyError("WeChat Pay callback is missing signature headers")
        try:
            callback_time = int(timestamp)
        except ValueError as error:
            raise InvalidPaymentNotifyError(
                "WeChat Pay callback timestamp is not a number"
            ) from error
        if abs(time.time() - callback_time) > _WECHAT_MAX_CALLBACK_CLOCK_SKEW_SECONDS:
            raise InvalidPaymentNotifyError("WeChat Pay callback timestamp is stale")
        material = f"{timestamp}\n{nonce}\n".encode() + body + b"\n"
        platform_key = certificates.public_key_for(serial)
        if not _rsa2_verify(platform_key, material, signature):
            raise InvalidPaymentNotifyError("WeChat Pay callback signature verification failed")


def _decrypt_wechat_resource(
    apiv3_key: bytes, resource: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        ciphertext = base64.b64decode(str(resource["ciphertext"]))
        nonce = str(resource["nonce"]).encode("utf-8")
        associated_data = resource.get("associated_data")
    except (KeyError, ValueError, TypeError) as error:
        raise InvalidPaymentNotifyError("WeChat Pay callback resource is malformed") from error
    try:
        plaintext = AESGCM(apiv3_key).decrypt(
            nonce,
            ciphertext,
            str(associated_data).encode("utf-8") if associated_data else None,
        )
    except InvalidSignature as error:
        raise InvalidPaymentNotifyError(
            "WeChat Pay callback resource decryption failed; check WECHAT_APIV3_KEY"
        ) from error
    try:
        parsed = json.loads(plaintext.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidPaymentNotifyError("WeChat Pay callback resource is not valid JSON") from error
    if not isinstance(parsed, dict):
        raise InvalidPaymentNotifyError("WeChat Pay callback resource must be a JSON object")
    return parsed


class WechatPayNativeGateway:
    """WeChat Pay APIv3 Native pay (扫码支付) for real-money recharge.

    ``create_payment`` posts the prepay transaction and returns ``code_url``
    for the QR code; ``verify_notify`` verifies the callback signature against
    the platform certificate of the reported serial, decrypts the AEAD_AES_256_GCM
    resource with the APIv3 key, and re-checks that the transaction really
    belongs to this merchant and app. Amounts are converted from 分 to yuan.
    """

    provider = "wechat"

    def __init__(
        self,
        *,
        mch_id: str,
        app_id: str,
        mch_serial_no: str,
        mch_private_key_pem: str,
        apiv3_key: str,
        gateway_url: str,
        notify_base_url: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        if len(apiv3_key) != 32:
            raise PaymentGatewayNotConfiguredError("WECHAT_APIV3_KEY must be exactly 32 characters")
        self._mch_id = mch_id.strip()
        self._app_id = app_id.strip()
        self._apiv3_key = apiv3_key.encode("utf-8")
        self._notify_url = f"{notify_base_url.rstrip('/')}/api/v1/billing/payments/wechat/notify"
        private_key = _load_private_key(mch_private_key_pem)
        self._http_client = http_client or httpx.Client(
            timeout=15.0,
            trust_env=False,
        )
        self._request_signer = _WechatRequestSigner(
            mch_id=self._mch_id,
            serial_no=mch_serial_no.strip(),
            private_key=private_key,
            http_client=self._http_client,
            gateway_url=gateway_url.rstrip("/"),
        )
        self._certificates = _WechatPlatformCertificates(
            apiv3_key=self._apiv3_key,
            http_client=self._http_client,
            request_signer=self._request_signer,
        )

    def create_payment(self, order: RechargeOrder) -> GatewayPaymentCreation:
        total_cents = int((Decimal(order.amount) * 100).quantize(Decimal("1")))
        payload = json.dumps(
            {
                "appid": self._app_id,
                "mchid": self._mch_id,
                "description": "知学空间积分充值",
                "out_trade_no": order.out_trade_no,
                "notify_url": self._notify_url,
                "amount": {"total": total_cents, "currency": "CNY"},
            },
            ensure_ascii=False,
        )
        response = self._request_signer.request(
            "POST", _WECHAT_NATIVE_ORDER_PATH, body=payload
        )
        if response.status_code != 200:
            detail = ""
            try:
                message = response.json().get("message", "")
                detail = str(message)[:200]
            except (ValueError, TypeError):
                detail = ""
            raise PaymentRequestError(
                f"WeChat Pay order creation failed ({response.status_code}) {detail}".strip()
            )
        self._request_signer.verify_platform_signature(
            certificates=self._certificates,
            headers={key.lower(): value for key, value in response.headers.items()},
            body=response.content,
        )
        try:
            code_url = str(response.json()["code_url"])
        except (ValueError, KeyError, TypeError) as error:
            raise PaymentRequestError("WeChat Pay order response has no code_url") from error
        if not code_url.startswith("weixin://"):
            raise PaymentRequestError("WeChat Pay code_url is not a weixin:// payload")
        return GatewayPaymentCreation(provider=self.provider, code_url=code_url, mode="qrcode")

    def verify_notify(self, callback: GatewayCallback) -> GatewayNotification:
        self._request_signer.verify_platform_signature(
            certificates=self._certificates,
            headers={key.lower(): value for key, value in callback.headers.items()},
            body=callback.body,
        )
        try:
            envelope = json.loads(callback.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise InvalidPaymentNotifyError("WeChat Pay callback body is not valid JSON") from error
        if not isinstance(envelope, dict) or not isinstance(envelope.get("resource"), dict):
            raise InvalidPaymentNotifyError("WeChat Pay callback body is missing its resource")
        transaction = _decrypt_wechat_resource(self._apiv3_key, envelope["resource"])
        out_trade_no = str(transaction.get("out_trade_no", "")).strip()
        transaction_id = str(transaction.get("transaction_id", "")).strip()
        amount = transaction.get("amount") if isinstance(transaction.get("amount"), dict) else {}
        total_cents = amount.get("total") if isinstance(amount.get("total"), int) else None
        if not out_trade_no or not transaction_id or total_cents is None or total_cents <= 0:
            raise InvalidPaymentNotifyError("WeChat Pay callback transaction is incomplete")
        if str(transaction.get("mchid", "")) != self._mch_id or str(
            transaction.get("appid", "")
        ) != self._app_id:
            raise InvalidPaymentNotifyError(
                "WeChat Pay transaction does not belong to this merchant"
            )
        total_amount = (Decimal(total_cents) / Decimal("100")).quantize(Decimal("0.01"))
        audit = {
            "provider": "wechat",
            "transaction_id": transaction_id,
            "out_trade_no": out_trade_no,
            "trade_state": str(transaction.get("trade_state", "")),
            "amount_total_cents": str(total_cents),
            "amount_payer_total_cents": str(amount.get("payer_total", "")),
            "callback_id": str(envelope.get("id", "")),
        }
        return GatewayNotification(
            out_trade_no=out_trade_no,
            trade_no=transaction_id,
            total_amount=total_amount,
            paid=str(transaction.get("trade_state", "")) == "SUCCESS",
            raw=audit,
        )


def build_payment_gateway(settings: Any) -> PaymentGateway:
    """Build the configured gateway; mock is always available for local use."""

    provider = settings.payment_provider
    if provider == "alipay":
        app_private_key = settings.alipay_app_private_key.get_secret_value()
        alipay_public_key = settings.alipay_public_key.get_secret_value()
        missing = [
            name
            for name, value in (
                ("ALIPAY_APP_ID", settings.alipay_app_id),
                ("ALIPAY_APP_PRIVATE_KEY", app_private_key.strip()),
                ("ALIPAY_PUBLIC_KEY", alipay_public_key.strip()),
                ("ALIPAY_NOTIFY_BASE_URL", settings.alipay_notify_origin),
            )
            if not value
        ]
        if missing:
            raise PaymentGatewayNotConfiguredError(
                f"PAYMENT_PROVIDER=alipay requires {', '.join(missing)}"
            )
        return AlipayPagePaymentGateway(
            app_id=settings.alipay_app_id,
            app_private_key_pem=app_private_key,
            alipay_public_key_pem=alipay_public_key,
            gateway_url=settings.alipay_gateway_url,
            notify_base_url=settings.alipay_notify_origin,
            return_url=settings.web_origin,
        )
    if provider == "wechat":
        mch_private_key = settings.wechat_mch_private_key.get_secret_value()
        apiv3_key = settings.wechat_apiv3_key.get_secret_value()
        missing = [
            name
            for name, value in (
                ("WECHAT_MCH_ID", settings.wechat_mch_id),
                ("WECHAT_APP_ID", settings.wechat_app_id),
                ("WECHAT_MCH_SERIAL_NO", settings.wechat_mch_serial_no),
                ("WECHAT_MCH_PRIVATE_KEY", mch_private_key.strip()),
                ("WECHAT_APIV3_KEY", apiv3_key.strip()),
                ("WECHAT_NOTIFY_BASE_URL", settings.wechat_notify_origin),
            )
            if not value
        ]
        if missing:
            raise PaymentGatewayNotConfiguredError(
                f"PAYMENT_PROVIDER=wechat requires {', '.join(missing)}"
            )
        return WechatPayNativeGateway(
            mch_id=settings.wechat_mch_id,
            app_id=settings.wechat_app_id,
            mch_serial_no=settings.wechat_mch_serial_no,
            mch_private_key_pem=mch_private_key,
            apiv3_key=apiv3_key,
            gateway_url=settings.wechat_gateway_url,
            notify_base_url=settings.wechat_notify_origin,
        )
    return MockPaymentGateway()


def mock_notification_fields(order: RechargeOrder) -> dict[str, str]:
    """Simulated gateway callback fields for the local mock cashier."""

    return {
        "out_trade_no": order.out_trade_no,
        "trade_no": f"MOCK{order.out_trade_no}",
        "total_amount": f"{order.amount:.2f}",
        "trade_status": "TRADE_SUCCESS",
    }


def order_reference_for_provider(provider: str, trade_no: str) -> str:
    """Unique, auditable external reference binding a gateway trade to the ledger."""

    return f"{provider}:{trade_no}"[:255]
