"""OCR protocol, disabled adapter, and public error boundary."""

import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

OCR_BACKEND_DISABLED = "disabled"


class OCRErrorCode(StrEnum):
    """Stable public OCR error codes safe to expose to callers."""

    DISABLED = "ocr_disabled"
    PROCESSING_FAILED = "ocr_processing_failed"


class OCRError(RuntimeError):
    """Public OCR failure carrying only a restricted non-sensitive code."""

    def __init__(self, code: OCRErrorCode) -> None:
        if not isinstance(code, OCRErrorCode):
            raise TypeError("code must be an OCRErrorCode")
        self.code = code
        super().__init__(code.value)


class OCRAdapter(Protocol):
    """Boundary for OCR engines implemented in later milestones."""

    backend: str

    def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str: ...


def normalize_ocr_backend(value: object) -> str:
    """Normalize and fail closed to the only OCR backend implemented today."""

    normalized = (
        unicodedata.normalize("NFKC", value).strip().casefold()
        if isinstance(value, str)
        else ""
    )
    if normalized != OCR_BACKEND_DISABLED:
        raise ValueError("OCR_BACKEND must be 'disabled'")
    return normalized


@dataclass(frozen=True, slots=True)
class DisabledOCRAdapter:
    """Local default that makes unavailable OCR explicit and safe."""

    backend: str = field(default=OCR_BACKEND_DISABLED, init=False)

    def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str:
        del image, languages
        raise OCRError(OCRErrorCode.DISABLED) from None


def extract_text_safely(
    adapter: OCRAdapter,
    image: bytes,
    *,
    languages: tuple[str, ...],
) -> str:
    """Run OCR while replacing provider failures with context-free public errors."""

    public_error: OCRError | None = None
    try:
        return adapter.extract_text(image, languages=languages)
    except OCRError as error:
        public_error = OCRError(error.code)
    except Exception:
        public_error = OCRError(OCRErrorCode.PROCESSING_FAILED)

    if public_error is None:  # pragma: no cover - defensive exhaustiveness guard
        raise RuntimeError("unreachable OCR error mapping state")
    raise public_error
