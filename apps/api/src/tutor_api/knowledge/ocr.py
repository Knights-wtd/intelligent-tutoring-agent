"""OCR protocol and safe disabled implementation."""

from typing import Protocol


class OCRError(RuntimeError):
    """Public OCR failure carrying only a stable non-sensitive code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OCRAdapter(Protocol):
    """Boundary for OCR engines implemented in later milestones."""

    backend: str

    def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str: ...


class DisabledOCRAdapter:
    """Local default that makes unavailable OCR explicit and safe."""

    backend = "disabled"

    def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str:
        del image, languages
        raise OCRError("ocr_disabled") from None
