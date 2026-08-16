"""Embedding protocol and deterministic local hash implementation."""

import hashlib
import math
import re
import unicodedata
from typing import Protocol

_ADAPTER_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class EmbeddingAdapter(Protocol):
    """Boundary for local or remote embedding engines."""

    backend: str
    model: str
    dimension: int

    @property
    def signature(self) -> str: ...

    def embed(self, text: str) -> list[float]: ...


class HashEmbeddingAdapter:
    """Dependency-free deterministic embedding for tests and local development."""

    def __init__(self, *, backend: str = "hash", model: str = "sha256-v1", dimension: int = 384):
        normalized_backend = unicodedata.normalize("NFKC", backend).strip().casefold()
        normalized_model = unicodedata.normalize("NFKC", model).strip()
        if not _ADAPTER_NAME.fullmatch(normalized_backend):
            raise ValueError("backend must be a safe adapter name")
        if (
            not _MODEL_NAME.fullmatch(normalized_model)
            or normalized_model.startswith("/")
            or "//" in normalized_model
            or any(segment in {".", ".."} for segment in normalized_model.split("/"))
        ):
            raise ValueError("model must be a safe model name")
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.backend = normalized_backend
        self.model = normalized_model
        self.dimension = dimension

    @property
    def signature(self) -> str:
        return f"{self.backend}:{self.model}:{self.dimension}"

    def embed(self, text: str) -> list[float]:
        normalized_text = unicodedata.normalize("NFC", text).encode("utf-8")
        domain = self.signature.encode("utf-8")
        values: list[float] = []
        counter = 0
        while len(values) < self.dimension:
            digest = hashlib.sha256(
                domain + b"\x00" + counter.to_bytes(8, "big") + b"\x00" + normalized_text
            ).digest()
            values.extend((byte - 127.5) / 127.5 for byte in digest)
            counter += 1

        vector = values[: self.dimension]
        norm = math.sqrt(sum(component * component for component in vector))
        return [component / norm for component in vector]
