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
from urllib.request import HTTPRedirectHandler, Request, build_opener
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
        self.code = "object_not_found"
        super().__init__(self.code)


class ObjectSizeLimitError(RuntimeError):
    """Raised when an object exceeds the configured in-memory boundary."""

    def __init__(self) -> None:
        self.code = "object_size_limit_exceeded"
        super().__init__(self.code)


class ObjectRangeNotSatisfiableError(RuntimeError):
    """Raised when a bounded object range cannot be served."""

    def __init__(self) -> None:
        self.code = "object_range_not_satisfiable"
        super().__init__(self.code)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        del request, fp, code, msg, headers, newurl
        return None


def _read_bounded(data: BinaryIO, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = data.read(min(64 * 1024, maximum + 1 - total))
        if not chunk:
            return b"".join(chunks)
        raw = bytes(chunk)
        total += len(raw)
        if total > maximum:
            raise ObjectSizeLimitError
        chunks.append(raw)


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Bytes and media type returned from object storage."""

    data: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class StoredObjectRange:
    """A bounded segment of a stored object."""

    data: bytes
    content_type: str
    start: int
    total_size: int


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

    def get_object_range(self, key: str, *, start: int, length: int) -> StoredObjectRange: ...


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


def build_page_text_preview_object_key(
    space_id: UUID,
    version_id: UUID,
    page_number: int,
    content_sha256: str,
) -> str:
    """Build an immutable, server-derived key for one bounded textual page preview."""

    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number <= 0:
        raise ValueError("page_number must be a positive integer")
    if not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
        raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
    return (
        f"spaces/{space_id}/document-versions/{version_id}/page-previews/"
        f"{page_number}-{content_sha256}.txt"
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
        max_object_bytes: int = 100 * 1024 * 1024,
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
        if isinstance(max_object_bytes, bool) or not isinstance(max_object_bytes, int):
            raise ValueError("max_object_bytes must be a positive integer")
        if max_object_bytes <= 0:
            raise ValueError("max_object_bytes must be a positive integer")
        self.endpoint = f"{parsed.scheme}://{parsed.netloc}"
        self.access_key = access_key
        self._secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self.timeout_seconds = timeout_seconds
        self.max_object_bytes = max_object_bytes
        self._host = parsed.netloc
        self._opener = build_opener(_RejectRedirects())

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
        range_header: str | None = None,
    ):
        if not key or key.startswith("/"):
            raise ValueError("object key must be a non-empty relative path")
        payload = b"" if data is None else bytes(data)
        if len(payload) > self.max_object_bytes:
            raise ObjectSizeLimitError
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
        if range_header is not None:
            headers["range"] = range_header
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
            return self._opener.open(request, timeout=self.timeout_seconds)
        except HTTPError as error:
            code = error.code
            error.close()
            if code == 404:
                raise ObjectNotFoundError from None
            if code == 416:
                raise ObjectRangeNotSatisfiableError from None
            if immutable_create and code in {409, 412}:
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
        self.put_if_absent(
            key,
            _read_bounded(data, self.max_object_bytes),
            content_type=content_type,
        )

    def get_object(self, key: str) -> StoredObject:
        with self._request("GET", key) as response:
            raw_length = response.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    content_length = int(raw_length)
                except (TypeError, ValueError):
                    content_length = None
                if content_length is not None and content_length > self.max_object_bytes:
                    raise ObjectSizeLimitError
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            return StoredObject(
                data=_read_bounded(response, self.max_object_bytes),
                content_type=_normalize_content_type(content_type),
            )


    def get_object_range(self, key: str, *, start: int, length: int) -> StoredObjectRange:
        if (
            isinstance(start, bool)
            or isinstance(length, bool)
            or not isinstance(start, int)
            or not isinstance(length, int)
            or start < 0
            or not 1 <= length <= self.max_object_bytes
        ):
            raise ObjectRangeNotSatisfiableError
        end = start + length - 1
        with self._request("GET", key, range_header=f"bytes={start}-{end}") as response:
            raw_content_range = response.headers.get("Content-Range")
            content_type = _normalize_content_type(
                response.headers.get("Content-Type", "application/octet-stream")
            )
            if raw_content_range is None:
                if start != 0:
                    raise ObjectRangeNotSatisfiableError
                raw_length = response.headers.get("Content-Length")
                try:
                    total_size = int(raw_length) if raw_length is not None else None
                except (TypeError, ValueError):
                    total_size = None
                if total_size is None or total_size > length:
                    raise ObjectRangeNotSatisfiableError
                return StoredObjectRange(
                    data=_read_bounded(response, length),
                    content_type=content_type,
                    start=0,
                    total_size=total_size,
                )
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", raw_content_range.strip())
            if match is None:
                raise ObjectRangeNotSatisfiableError
            actual_start, actual_end, total_size = (int(value) for value in match.groups())
            if (
                actual_start != start
                or actual_end < actual_start
                or actual_end - actual_start + 1 > length
                or total_size <= actual_end
            ):
                raise ObjectRangeNotSatisfiableError
            return StoredObjectRange(
                data=_read_bounded(response, length),
                content_type=content_type,
                start=actual_start,
                total_size=total_size,
            )


def create_object_storage(settings: Settings) -> S3ObjectStorage:
    """Construct the shared production object-storage adapter from Settings."""

    secret_value = settings.object_storage_secret_key.get_secret_value()
    return S3ObjectStorage(
        endpoint=settings.object_storage_endpoint,
        access_key=settings.object_storage_access_key,
        secret_key=secret_value,
        bucket=settings.object_storage_bucket,
        max_object_bytes=settings.knowledge_upload_max_bytes,
    )


class MemoryObjectStorage:
    """Thread-safe test storage with atomic immutable-create semantics."""

    def __init__(self, *, max_object_bytes: int = 100 * 1024 * 1024) -> None:
        if isinstance(max_object_bytes, bool) or not isinstance(max_object_bytes, int):
            raise ValueError("max_object_bytes must be a positive integer")
        if max_object_bytes <= 0:
            raise ValueError("max_object_bytes must be a positive integer")
        self.max_object_bytes = max_object_bytes
        self._objects: dict[str, StoredObject] = {}
        self._lock = threading.Lock()

    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        raw = bytes(data)
        if len(raw) > self.max_object_bytes:
            raise ObjectSizeLimitError
        stored = StoredObject(
            data=raw,
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
        self.put_if_absent(
            key,
            _read_bounded(data, self.max_object_bytes),
            content_type=content_type,
        )

    def get_object(self, key: str) -> StoredObject:
        with self._lock:
            try:
                return self._objects[key]
            except KeyError:
                raise ObjectNotFoundError from None

    def get_object_range(self, key: str, *, start: int, length: int) -> StoredObjectRange:
        if (
            isinstance(start, bool)
            or isinstance(length, bool)
            or not isinstance(start, int)
            or not isinstance(length, int)
            or start < 0
            or not 1 <= length <= self.max_object_bytes
        ):
            raise ObjectRangeNotSatisfiableError
        with self._lock:
            try:
                stored = self._objects[key]
            except KeyError:
                raise ObjectNotFoundError from None
        if start >= len(stored.data):
            raise ObjectRangeNotSatisfiableError
        return StoredObjectRange(
            data=stored.data[start : start + length],
            content_type=stored.content_type,
            start=start,
            total_size=len(stored.data),
        )
