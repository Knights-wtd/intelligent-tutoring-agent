"""Selective OCR, isolated PDF rendering, and safe public error boundaries."""

from __future__ import annotations

import hashlib
import math
import multiprocessing
import subprocess
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol

from tutor_api.knowledge.parsers import (
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    ParsedPage,
)

OCR_BACKEND_DISABLED = "disabled"
_DEFAULT_OCR_LANGUAGES = ("eng", "chi_sim")
_ALLOWED_OCR_LANGUAGES = frozenset(_DEFAULT_OCR_LANGUAGES)
_DEFAULT_MAX_PIXELS = 20_000_000
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
_DEFAULT_MAX_TEXT_CHARS = 2_000_000
_DEFAULT_RENDER_SCALE = 2.0


class OCRErrorCode(StrEnum):
    """Stable public OCR error codes safe to expose to callers."""

    DISABLED = "ocr_disabled"
    PROCESSING_FAILED = "ocr_processing_failed"
    TIMEOUT = "ocr_timeout"
    LIMIT_EXCEEDED = "ocr_limit_exceeded"


class OCRPageStatus(StrEnum):
    """Stable page checkpoint states."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OCRError(RuntimeError):
    """Public OCR failure carrying only a restricted non-sensitive code."""

    def __init__(self, code: OCRErrorCode) -> None:
        if not isinstance(code, OCRErrorCode):
            raise TypeError("code must be an OCRErrorCode")
        self.code = code
        super().__init__(code.value)


class OCRAdapter(Protocol):
    """Boundary shared by disabled, fake, and production OCR engines."""

    backend: str

    def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str: ...


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """Bounded in-memory page image returned by a renderer."""

    image: bytes
    media_type: str
    width: int
    height: int


class PDFPageRenderer(Protocol):
    """Isolated renderer boundary for PDF pages selected for OCR."""

    def render_page(
        self,
        pdf: bytes,
        *,
        page_number: int,
        max_pixels: int,
        timeout_seconds: float,
    ) -> RenderedPage: ...


@dataclass(frozen=True, slots=True)
class PageEvidence:
    """Immutable page image evidence safe to checkpoint."""

    page_number: int
    source_pointer: str
    media_type: str
    width: int
    height: int
    image: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class OCRPageCheckpoint:
    """Per-page OCR outcome without provider exceptions or diagnostics."""

    page_number: int
    status: OCRPageStatus
    text: str | None = None
    evidence: PageEvidence | None = None
    error_code: OCRErrorCode | None = None


@dataclass(frozen=True, slots=True)
class OCRDocumentResult:
    """Updated immutable document plus resumable page checkpoints."""

    document: ParsedDocument
    checkpoints: tuple[OCRPageCheckpoint, ...]


def normalize_ocr_backend(value: object) -> str:
    """Normalize and fail closed to the default disabled runtime backend."""

    normalized = (
        unicodedata.normalize("NFKC", value).strip().casefold()
        if isinstance(value, str)
        else ""
    )
    if normalized != OCR_BACKEND_DISABLED:
        raise ValueError("OCR_BACKEND must be 'disabled'")
    return normalized


def normalize_ocr_languages(value: object) -> tuple[str, ...]:
    """Normalize, deduplicate, and allowlist installed OCR language packs."""

    values: object = value.split(",") if isinstance(value, str) else value
    if isinstance(values, bool) or not isinstance(values, (tuple, list)):
        raise ValueError("OCR languages must use the supported allowlist")

    normalized: list[str] = []
    seen: set[str] = set()
    for language in values:
        candidate = (
            unicodedata.normalize("NFKC", language).strip().casefold()
            if isinstance(language, str)
            else ""
        )
        if candidate not in _ALLOWED_OCR_LANGUAGES:
            raise ValueError("OCR languages must use the supported allowlist")
        if candidate not in seen:
            seen.add(candidate)
            normalized.append(candidate)
    if not normalized:
        raise ValueError("OCR languages must use the supported allowlist")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class DisabledOCRAdapter:
    """Local default that makes unavailable OCR explicit and safe."""

    backend: str = field(default=OCR_BACKEND_DISABLED, init=False)

    def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str:
        del image, languages
        raise OCRError(OCRErrorCode.DISABLED) from None


def _validate_positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _validate_positive_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def _sanitize_ocr_text(text: object, *, max_chars: int) -> str:
    if not isinstance(text, str):
        raise OCRError(OCRErrorCode.PROCESSING_FAILED) from None
    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    filtered = "".join(
        character
        for character in normalized
        if character in "\n\t" or unicodedata.category(character) not in {"Cc", "Cs"}
    )
    compact = "\n".join(
        compact_line for line in filtered.splitlines() if (compact_line := " ".join(line.split()))
    )
    if len(compact) > max_chars:
        raise OCRError(OCRErrorCode.LIMIT_EXCEEDED) from None
    return compact


@dataclass(frozen=True, slots=True)
class TesseractOCRAdapter:
    """Tesseract subprocess adapter with a fixed argument shape and hard timeout."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_output_bytes: int = _DEFAULT_MAX_TEXT_CHARS * 4
    executable: str = "tesseract"
    backend: str = field(default="tesseract", init=False)

    def __post_init__(self) -> None:
        if not _validate_positive_finite_number(self.timeout_seconds):
            raise ValueError("OCR limits must be positive finite values")
        if not _validate_positive_int(self.max_output_bytes):
            raise ValueError("OCR limits must be positive finite values")
        if not isinstance(self.executable, str) or not self.executable or "\x00" in self.executable:
            raise ValueError("Tesseract executable is invalid")

    def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str:
        normalized_languages = normalize_ocr_languages(languages)
        raw = bytes(image)
        failure_code: OCRErrorCode | None = None
        try:
            completed = subprocess.run(
                [
                    self.executable,
                    "stdin",
                    "stdout",
                    "-l",
                    "+".join(normalized_languages),
                ],
                input=raw,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            failure_code = OCRErrorCode.TIMEOUT
        except Exception:
            failure_code = OCRErrorCode.PROCESSING_FAILED
        if failure_code is not None:
            raise OCRError(failure_code) from None

        return_code = completed.returncode
        stdout = completed.stdout
        del completed
        if return_code != 0:
            raise OCRError(OCRErrorCode.PROCESSING_FAILED) from None
        if not isinstance(stdout, bytes) or len(stdout) > self.max_output_bytes:
            raise OCRError(OCRErrorCode.LIMIT_EXCEEDED) from None
        decoded: str | None = None
        try:
            decoded = stdout.decode("utf-8")
        except UnicodeDecodeError:
            pass
        if decoded is None:
            raise OCRError(OCRErrorCode.PROCESSING_FAILED) from None
        return _sanitize_ocr_text(decoded, max_chars=self.max_output_bytes)


def _safe_public_code(error: OCRError) -> OCRErrorCode:
    try:
        code = error.code
    except Exception:
        return OCRErrorCode.PROCESSING_FAILED
    return code if isinstance(code, OCRErrorCode) else OCRErrorCode.PROCESSING_FAILED


def extract_text_safely(
    adapter: OCRAdapter,
    image: bytes,
    *,
    languages: tuple[str, ...],
) -> str:
    """Run OCR while replacing provider failures with context-free public errors."""

    public_code = OCRErrorCode.PROCESSING_FAILED
    try:
        return adapter.extract_text(image, languages=languages)
    except OCRError as error:
        public_code = _safe_public_code(error)
    except Exception:
        pass

    raise OCRError(public_code) from None


def _pdfium_render_worker(
    connection: object,
    pdf: bytes,
    page_number: int,
    max_pixels: int,
    scale: float,
) -> None:
    """Render in a dedicated process because PDFium is not thread-safe."""

    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(pdf)
        try:
            if page_number < 1 or page_number > len(document):
                raise ValueError("page out of range")
            page = document.get_page(page_number - 1)
            try:
                page_width = float(page.get_width())
                page_height = float(page.get_height())
                if (
                    not math.isfinite(page_width)
                    or not math.isfinite(page_height)
                    or page_width <= 0
                    or page_height <= 0
                ):
                    raise ValueError("invalid page dimensions")
                render_scale = min(scale, math.sqrt(max_pixels / (page_width * page_height)))
                for _ in range(32):
                    width = math.ceil(page_width * render_scale)
                    height = math.ceil(page_height * render_scale)
                    if width > 0 and height > 0 and width * height <= max_pixels:
                        break
                    render_scale *= 0.99
                else:
                    raise ValueError("pixel budget unavailable")
                bitmap = page.render(scale=render_scale, grayscale=True)
                try:
                    width = int(bitmap.width)
                    height = int(bitmap.height)
                    if width < 1 or height < 1 or width * height > max_pixels:
                        raise ValueError("pixel budget exceeded")
                    pixels = bytearray()
                    for row in range(height):
                        start = row * bitmap.stride
                        pixels.extend(bitmap.buffer[start : start + width])
                    header = f"P5\n{width} {height}\n255\n".encode("ascii")
                    connection.send(("ok", header + bytes(pixels), width, height))
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            document.close()
    except Exception:
        try:
            connection.send(("error",))
        except Exception:
            pass
    finally:
        try:
            connection.close()
        except Exception:
            pass


RenderWorker = Callable[..., None]


@dataclass(frozen=True, slots=True)
class PDFiumPageRenderer:
    """Process-isolated PDFium renderer with a parent-enforced wall-clock timeout."""

    scale: float = _DEFAULT_RENDER_SCALE
    worker: RenderWorker = field(default=_pdfium_render_worker, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not _validate_positive_finite_number(self.scale):
            raise ValueError("OCR limits must be positive finite values")
        if not callable(self.worker):
            raise TypeError("worker must be callable")

    def render_page(
        self,
        pdf: bytes,
        *,
        page_number: int,
        max_pixels: int,
        timeout_seconds: float,
    ) -> RenderedPage:
        if not _validate_positive_int(page_number):
            raise ValueError("page_number must be a positive integer")
        if not _validate_positive_int(max_pixels) or not _validate_positive_finite_number(
            timeout_seconds
        ):
            raise ValueError("OCR limits must be positive finite values")

        receive_connection: object | None = None
        send_connection: object | None = None
        process: object | None = None
        started = False
        rendered: RenderedPage | None = None
        failure_code: OCRErrorCode | None = None
        try:
            context = multiprocessing.get_context("spawn")
            receive_connection, send_connection = context.Pipe(duplex=False)
            process = context.Process(
                target=self.worker,
                args=(send_connection, bytes(pdf), page_number, max_pixels, self.scale),
                daemon=True,
            )
            process.start()
            started = True
            send_connection.close()
            if not receive_connection.poll(float(timeout_seconds)):
                failure_code = OCRErrorCode.TIMEOUT
            else:
                payload = receive_connection.recv()
                if (
                    not isinstance(payload, tuple)
                    or len(payload) != 4
                    or payload[0] != "ok"
                    or not isinstance(payload[1], bytes)
                    or not _validate_positive_int(payload[2])
                    or not _validate_positive_int(payload[3])
                    or payload[2] * payload[3] > max_pixels
                ):
                    failure_code = OCRErrorCode.PROCESSING_FAILED
                else:
                    rendered = RenderedPage(
                        image=payload[1],
                        media_type="image/x-portable-graymap",
                        width=payload[2],
                        height=payload[3],
                    )
        except Exception:
            failure_code = OCRErrorCode.PROCESSING_FAILED
        finally:
            for connection in (send_connection, receive_connection):
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
            if process is not None and started:
                try:
                    if rendered is not None:
                        process.join(timeout=0.25)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=0.25)
                    if process.is_alive() and hasattr(process, "kill"):
                        process.kill()
                        process.join(timeout=0.25)
                except Exception:
                    if failure_code is None:
                        failure_code = OCRErrorCode.PROCESSING_FAILED
                finally:
                    try:
                        process.close()
                    except Exception:
                        pass

        if failure_code is not None or rendered is None:
            raise OCRError(failure_code or OCRErrorCode.PROCESSING_FAILED) from None
        return rendered
def _make_evidence(
    document: ParsedDocument,
    page: ParsedPage,
    rendered: RenderedPage,
    *,
    max_pixels: int,
    max_evidence_bytes: int,
) -> PageEvidence:
    if (
        not _validate_positive_int(rendered.width)
        or not _validate_positive_int(rendered.height)
        or rendered.width * rendered.height > max_pixels
        or not isinstance(rendered.image, bytes)
        or not rendered.image
        or len(rendered.image) > max_evidence_bytes
        or not isinstance(rendered.media_type, str)
        or not rendered.media_type.startswith("image/")
    ):
        raise OCRError(OCRErrorCode.LIMIT_EXCEEDED) from None
    return PageEvidence(
        page_number=page.page_number,
        source_pointer=f"{document.source_name}#page={page.page_number}&evidence=ocr",
        media_type=rendered.media_type,
        width=rendered.width,
        height=rendered.height,
        image=rendered.image,
        sha256=hashlib.sha256(rendered.image).hexdigest(),
    )


def _render_selected_page(
    document: ParsedDocument,
    page: ParsedPage,
    source_data: bytes,
    *,
    renderer: PDFPageRenderer | None,
    max_pixels: int,
    timeout_seconds: float,
) -> RenderedPage:
    if document.media_type == "application/pdf":
        if renderer is None:
            raise OCRError(OCRErrorCode.PROCESSING_FAILED) from None
        return renderer.render_page(
            source_data,
            page_number=page.page_number,
            max_pixels=max_pixels,
            timeout_seconds=timeout_seconds,
        )
    if document.media_type.startswith("image/"):
        if not _validate_positive_int(page.width) or not _validate_positive_int(page.height):
            raise OCRError(OCRErrorCode.PROCESSING_FAILED) from None
        if page.width * page.height > max_pixels:
            raise OCRError(OCRErrorCode.LIMIT_EXCEEDED) from None
        return RenderedPage(
            image=source_data,
            media_type=document.media_type,
            width=page.width,
            height=page.height,
        )
    raise OCRError(OCRErrorCode.PROCESSING_FAILED) from None


def _failed_checkpoint(
    page_number: int,
    code: OCRErrorCode,
    *,
    evidence: PageEvidence | None = None,
) -> OCRPageCheckpoint:
    return OCRPageCheckpoint(
        page_number=page_number,
        status=OCRPageStatus.FAILED,
        evidence=evidence,
        error_code=code,
    )


def apply_selective_ocr(
    document: ParsedDocument,
    source_data: bytes,
    *,
    adapter: OCRAdapter,
    renderer: PDFPageRenderer | None,
    languages: object = _DEFAULT_OCR_LANGUAGES,
    max_pixels: int = _DEFAULT_MAX_PIXELS,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    max_evidence_bytes: int = _DEFAULT_MAX_EVIDENCE_BYTES,
    max_text_chars: int = _DEFAULT_MAX_TEXT_CHARS,
) -> OCRDocumentResult:
    """OCR only selected pages and checkpoint every success or redacted failure."""

    if (
        not _validate_positive_int(max_pixels)
        or not _validate_positive_finite_number(timeout_seconds)
        or not _validate_positive_int(max_evidence_bytes)
        or not _validate_positive_int(max_text_chars)
    ):
        raise ValueError("OCR limits must be positive finite values")
    normalized_languages = normalize_ocr_languages(languages)
    raw_source = bytes(source_data)

    pages: list[ParsedPage] = []
    checkpoints: list[OCRPageCheckpoint] = []
    for page in document.pages:
        if not page.needs_ocr:
            pages.append(page)
            continue

        evidence: PageEvidence | None = None
        try:
            rendered = _render_selected_page(
                document,
                page,
                raw_source,
                renderer=renderer,
                max_pixels=max_pixels,
                timeout_seconds=float(timeout_seconds),
            )
            evidence = _make_evidence(
                document,
                page,
                rendered,
                max_pixels=max_pixels,
                max_evidence_bytes=max_evidence_bytes,
            )
            extracted = extract_text_safely(
                adapter,
                evidence.image,
                languages=normalized_languages,
            )
            text = _sanitize_ocr_text(extracted, max_chars=max_text_chars)
        except OCRError as error:
            checkpoints.append(
                _failed_checkpoint(
                    page.page_number,
                    _safe_public_code(error),
                    evidence=evidence,
                )
            )
            pages.append(page)
            continue
        except Exception:
            checkpoints.append(
                _failed_checkpoint(
                    page.page_number,
                    OCRErrorCode.PROCESSING_FAILED,
                    evidence=evidence,
                )
            )
            pages.append(page)
            continue

        blocks = page.blocks
        if text:
            blocks += (
                ParsedBlock(
                    kind=ParsedBlockKind.PARAGRAPH,
                    text=text,
                    order=len(blocks),
                    source_pointer=f"{document.source_name}#page={page.page_number}&ocr=1",
                    page_number=page.page_number,
                ),
            )
        completed_page = replace(page, blocks=blocks, needs_ocr=False)
        pages.append(completed_page)
        checkpoints.append(
            OCRPageCheckpoint(
                page_number=page.page_number,
                status=OCRPageStatus.SUCCEEDED,
                text=text,
                evidence=evidence,
            )
        )

    frozen_pages = tuple(pages)
    updated = replace(
        document,
        pages=frozen_pages,
        blocks=tuple(block for page in frozen_pages for block in page.blocks),
    )
    return OCRDocumentResult(document=updated, checkpoints=tuple(checkpoints))
