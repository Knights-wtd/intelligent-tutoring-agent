"""Object-storage protocol and deterministic in-memory implementation."""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, BinaryIO, Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

if TYPE_CHECKING:
    from tutor_api.core.config import Settings

_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:(?:/|$)")
_HTTP_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_SAFE_PATH_ERROR = "source name must be a safe relative path"
_CONTENT_TYPE_ERROR = "content_type must be a safe type/subtype value"


class ObjectAlreadyExistsError(RuntimeError):
    """Raised when immutable object content would be overwritten."""

    def __init__(self) -> None:
        super().__init__("object_already_exists")


class ObjectNotFoundError(RuntimeError):
    """Raised when an object key does not exist."""

    def __init__(self) -> None:
        super().__init__("object_not_found")


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Bytes and media type returned from object storage."""

    data: bytes
    content_type: str


class ObjectStorage(Protocol):
    """Immutable-create storage boundary used by ingestion services."""

    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None: ...

    def put_file_if_absent(
        self,
        key: str,
        data: BinaryIO,
        *,
        content_type: str,
    ) -> None: ...

    def get_object(self, key: str) -> StoredObject: ...


def _contains_control_or_format(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)


def _normalize_content_type(value: str) -> str:
    if not isinstance(value, str) or _contains_control_or_format(value):
        raise ValueError(_CONTENT_TYPE_ERROR)

    parts = value.split(";")
    media_type = parts[0].strip()
    if media_type.count("/") != 1:
        raise ValueError(_CONTENT_TYPE_ERROR)
    type_name, subtype_name = (part.strip() for part in media_type.split("/", 1))
    if not _HTTP_TOKEN.fullmatch(type_name) or not _HTTP_TOKEN.fullmatch(subtype_name):
        raise ValueError(_CONTENT_TYPE_ERROR)

    normalized_parameters: list[str] = []
    seen_parameter_names: set[str] = set()
    for raw_parameter in parts[1:]:
        parameter = raw_parameter.strip()
        if not parameter or parameter.count("=") != 1:
            raise ValueError(_CONTENT_TYPE_ERROR)
        raw_name, raw_value = (part.strip() for part in parameter.split("=", 1))
        if not _HTTP_TOKEN.fullmatch(raw_name) or not _HTTP_TOKEN.fullmatch(raw_value):
            raise ValueError(_CONTENT_TYPE_ERROR)
        normalized_name = raw_name.casefold()
        if normalized_name in seen_parameter_names:
            raise ValueError(_CONTENT_TYPE_ERROR)
        seen_parameter_names.add(normalized_name)
        normalized_parameters.append(f"{normalized_name}={raw_value}")

    normalized = f"{type_name.casefold()}/{subtype_name.casefold()}"
    if normalized_parameters:
        normalized = f"{normalized}; {'; '.join(normalized_parameters)}"
    return normalized


def build_document_object_key(
    space_id: UUID,
    document_id: UUID,
    version_id: UUID,
    source_name: str,
) -> str:
    """Build a space-scoped immutable key from a safe relative source name."""

    normalized_name = unicodedata.normalize("NFC", source_name)
    if (
        not normalized_name
        or normalized_name.startswith("/")
        or "\\" in normalized_name
        or _WINDOWS_DRIVE_PATH.match(normalized_name)
        or _contains_control_or_format(normalized_name)
    ):
        raise ValueError(_SAFE_PATH_ERROR)

    segments = normalized_name.split("/")
    if any(
        not segment or not segment.strip() or segment in {".", ".."}
        for segment in segments
    ):
        raise ValueError(_SAFE_PATH_ERROR)

    return (
        f"spaces/{space_id}/documents/{document_id}/versions/{version_id}/"
        f"{normalized_name}"
    )


class S3ObjectStorage:
    """Minimal path-style S3/MinIO adapter using AWS Signature Version 4."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        timeout_seconds: float = 30.0,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("object storage endpoint must be an absolute HTTP(S) origin")
        if not access_key or not secret_key or not bucket or "/" in bucket:
            raise ValueError("object storage credentials and bucket must not be blank")
        self.endpoint = f"{parsed.scheme}://{parsed.netloc}"
        self.access_key = access_key
        self._secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self.timeout_seconds = timeout_seconds
        self._host = parsed.netloc

    @staticmethod
    def _signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
        date_key = hmac.new(
            f"AWS4{secret_key}".encode(), date_stamp.encode(), hashlib.sha256
        ).digest()
        region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
        service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
        return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()

    def _request(
        self,
        method: str,
        key: str,
        *,
        data: bytes | None = None,
        content_type: str | None = None,
        immutable_create: bool = False,
    ):
        if not key or key.startswith("/"):
            raise ValueError("object key must be a non-empty relative path")
        payload = b"" if data is None else bytes(data)
        payload_hash = hashlib.sha256(payload).hexdigest()
        timestamp = datetime.now(UTC)
        amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = timestamp.strftime("%Y%m%d")
        canonical_uri = f"/{quote(self.bucket, safe='-_.~')}/{quote(key, safe='/-_.~')}"
        headers = {
            "host": self._host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type is not None:
            headers["content-type"] = _normalize_content_type(content_type)
        if immutable_create:
            headers["if-none-match"] = "*"
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(
            f"{name}:{' '.join(headers[name].split())}\n" for name in sorted(headers)
        )
        canonical_request = "\n".join(
            (method, canonical_uri, "", canonical_headers, signed_headers, payload_hash)
        )
        scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            (
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            )
        )
        signature = hmac.new(
            self._signing_key(self._secret_key, date_stamp, self.region),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        request = Request(
            f"{self.endpoint}{canonical_uri}",
            data=payload if method == "PUT" else None,
            method=method,
            headers=headers,
        )
        try:
            return urlopen(request, timeout=self.timeout_seconds)
        except HTTPError as error:
            if error.code == 404:
                raise ObjectNotFoundError from None
            if immutable_create and error.code in {409, 412}:
                raise ObjectAlreadyExistsError from None
            raise RuntimeError("object_storage_request_failed") from None
        except Exception:
            raise RuntimeError("object_storage_request_failed") from None

    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        with self._request(
            "PUT",
            key,
            data=data,
            content_type=content_type,
            immutable_create=True,
        ):
            return None

    def put_file_if_absent(
        self,
        key: str,
        data: BinaryIO,
        *,
        content_type: str,
    ) -> None:
        self.put_if_absent(key, data.read(), content_type=content_type)

    def get_object(self, key: str) -> StoredObject:
        with self._request("GET", key) as response:
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            return StoredObject(
                data=response.read(),
                content_type=_normalize_content_type(content_type),
            )


def create_object_storage(settings: Settings) -> S3ObjectStorage:
    """Construct the shared production object-storage adapter from Settings."""

    secret_value = settings.object_storage_secret_key.get_secret_value()
    return S3ObjectStorage(
        endpoint=settings.object_storage_endpoint,
        access_key=settings.object_storage_access_key,
        secret_key=secret_value,
        bucket=settings.object_storage_bucket,
    )


class MemoryObjectStorage:
    """Thread-safe test storage with atomic immutable-create semantics."""

    def __init__(self) -> None:
        self._objects: dict[str, StoredObject] = {}
        self._lock = threading.Lock()

    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        stored = StoredObject(
            data=bytes(data),
            content_type=_normalize_content_type(content_type),
        )
        with self._lock:
            if key in self._objects:
                raise ObjectAlreadyExistsError
            self._objects[key] = stored

    def put_file_if_absent(
        self,
        key: str,
        data: BinaryIO,
        *,
        content_type: str,
    ) -> None:
        chunks: list[bytes] = []
        while chunk := data.read(64 * 1024):
            chunks.append(chunk)
        self.put_if_absent(key, b"".join(chunks), content_type=content_type)

    def get_object(self, key: str) -> StoredObject:
        with self._lock:
            try:
                return self._objects[key]
            except KeyError:
                raise ObjectNotFoundError from None
