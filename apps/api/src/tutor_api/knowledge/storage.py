"""Object-storage protocol and deterministic in-memory implementation."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:(?:/|$)")
_SAFE_PATH_ERROR = "source name must be a safe relative path"


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
    """Storage boundary used by ingestion services."""

    def put_object(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        overwrite: bool = False,
    ) -> None: ...

    def get_object(self, key: str) -> StoredObject: ...


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
        or "\x00" in normalized_name
        or _WINDOWS_DRIVE_PATH.match(normalized_name)
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
    """Test storage that keeps immutable objects in process memory."""

    def __init__(self) -> None:
        self._objects: dict[str, StoredObject] = {}

    def put_object(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        overwrite: bool = False,
    ) -> None:
        if key in self._objects and not overwrite:
            raise ObjectAlreadyExistsError
        if not content_type.strip() or "\r" in content_type or "\n" in content_type:
            raise ValueError("content_type must be a non-blank media type")
        self._objects[key] = StoredObject(data=bytes(data), content_type=content_type.strip())

    def get_object(self, key: str) -> StoredObject:
        try:
            return self._objects[key]
        except KeyError:
            raise ObjectNotFoundError from None
