"""Embedding protocol and deterministic signed feature-hash implementation."""

import hashlib
import math
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

HASH_EMBEDDING_BACKEND = "hash"
HASH_EMBEDDING_MODEL = "feature-hash-v1"
MIN_EMBEDDING_DIMENSION = 8
MAX_EMBEDDING_DIMENSION = 4096
_WORD = re.compile(r"\w+", flags=re.UNICODE)


class EmbeddingAdapter(Protocol):
    """Boundary for local or remote embedding engines."""

    @property
    def backend(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def signature(self) -> str: ...

    def embed(self, text: str) -> list[float]: ...


def normalize_embedding_backend(value: object) -> str:
    normalized = (
        unicodedata.normalize("NFKC", value).strip().casefold()
        if isinstance(value, str)
        else ""
    )
    if normalized != HASH_EMBEDDING_BACKEND:
        raise ValueError("EMBEDDING_BACKEND must be 'hash'")
    return normalized


def normalize_embedding_model(value: object) -> str:
    normalized = (
        unicodedata.normalize("NFKC", value).strip().casefold()
        if isinstance(value, str)
        else ""
    )
    if normalized != HASH_EMBEDDING_MODEL:
        raise ValueError("EMBEDDING_MODEL must be 'feature-hash-v1'")
    return normalized


def validate_embedding_dimension(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_EMBEDDING_DIMENSION <= value <= MAX_EMBEDDING_DIMENSION
    ):
        raise ValueError("EMBEDDING_DIMENSION must be between 8 and 4096")
    return value


def validate_embedding_configuration(
    *,
    backend: object,
    model: object,
    dimension: object,
) -> tuple[str, str, int]:
    """Apply the same fail-closed checks to settings and runtime adapters."""

    return (
        normalize_embedding_backend(backend),
        normalize_embedding_model(model),
        validate_embedding_dimension(dimension),
    )


def _normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("text must not be blank")
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(
        " " if unicodedata.category(character).startswith(("P", "Z")) else character
        for character in normalized
    )
    normalized = " ".join(normalized.split())
    if not normalized:
        raise ValueError("text must not be blank")
    return normalized


def _iter_weighted_features(text: str) -> Iterator[tuple[str, float]]:
    for token in _WORD.findall(text):
        yield f"word:{token}", 0.5

    compact = text.replace(" ", "")
    for size, weight in ((1, 1.0), (2, 1.5), (3, 1.0), (4, 0.5)):
        for start in range(len(compact) - size + 1):
            yield f"char{size}:{compact[start : start + size]}", weight


def _feature_bucket(feature: str, dimension: int) -> tuple[int, float]:
    digest = hashlib.blake2b(
        feature.encode("utf-8"),
        digest_size=8,
        person=b"tutor-fh-v1",
    ).digest()
    bucket = int.from_bytes(digest[:4], "big") % dimension
    sign = 1.0 if digest[4] & 1 else -1.0
    return bucket, sign


@dataclass(frozen=True, slots=True)
class HashEmbeddingAdapter:
    """Deterministic local signed feature hashing for tests and development."""

    backend: str = HASH_EMBEDDING_BACKEND
    model: str = HASH_EMBEDDING_MODEL
    dimension: int = 384

    def __post_init__(self) -> None:
        backend, model, dimension = validate_embedding_configuration(
            backend=self.backend,
            model=self.model,
            dimension=self.dimension,
        )
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "dimension", dimension)

    @property
    def signature(self) -> str:
        return f"{self.backend}:{self.model}:{self.dimension}"

    def embed(self, text: str) -> list[float]:
        normalized_text = _normalize_text(text)
        vector = [0.0] * self.dimension
        for feature, weight in _iter_weighted_features(normalized_text):
            bucket, sign = _feature_bucket(feature, self.dimension)
            vector[bucket] += sign * weight

        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0.0:
            bucket, sign = _feature_bucket(f"fallback:{normalized_text}", self.dimension)
            vector[bucket] = sign
            norm = 1.0
        return [component / norm for component in vector]
