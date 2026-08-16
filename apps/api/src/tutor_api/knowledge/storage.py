"""Object-storage protocol and deterministic in-memory implementation."""

import re
import threading
import unicodedata
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

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

    def get_object(self, key: str) -> StoredObject:
        with self._lock:
            try:
                return self._objects[key]
            except KeyError:
                raise ObjectNotFoundError from None
