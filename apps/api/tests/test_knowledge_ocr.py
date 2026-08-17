from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from tutor_api.knowledge.ocr import (
    OCRError,
    OCRErrorCode,
    OCRPageStatus,
    PDFiumPageRenderer,
    RenderedPage,
    TesseractOCRAdapter,
    apply_selective_ocr,
    normalize_ocr_languages,
)
from tutor_api.knowledge.parsers import (
    ParsedBlock,
    ParsedBlockKind,
    ParsedDocument,
    ParsedPage,
)


def _block(text: str, *, page_number: int, order: int, source_name: str) -> ParsedBlock:
    return ParsedBlock(
        kind=ParsedBlockKind.PARAGRAPH,
        text=text,
        order=order,
        source_pointer=f"{source_name}#page={page_number}&block={order + 1}",
        page_number=page_number,
    )


def _pdf_document() -> ParsedDocument:
    source_name = "lesson.pdf"
    native = _block(
        "Reliable native text stays untouched.",
        page_number=1,
        order=0,
        source_name=source_name,
    )
    low_confidence = _block(
        "garbled native fragment",
        page_number=2,
        order=0,
        source_name=source_name,
    )
    return ParsedDocument(
        source_name=source_name,
        media_type="application/pdf",
        blocks=(native, low_confidence),
        pages=(
            ParsedPage(page_number=1, blocks=(native,), needs_ocr=False),
            ParsedPage(page_number=2, blocks=(low_confidence,), needs_ocr=True),
            ParsedPage(page_number=3, blocks=(), needs_ocr=True),
        ),
    )


@dataclass
class FakeRenderer:
    calls: list[int]

    def render_page(
        self,
        pdf: bytes,
        *,
        page_number: int,
        max_pixels: int,
        timeout_seconds: float,
    ) -> RenderedPage:
        assert pdf == b"pdf-source"
        assert max_pixels == 64
        assert timeout_seconds == 0.5
        self.calls.append(page_number)
        return RenderedPage(
            image=f"page-{page_number}".encode(),
            media_type="image/x-portable-graymap",
            width=2,
            height=2,
        )


@dataclass
class FakeOCR:
    calls: list[tuple[bytes, tuple[str, ...]]]
    fail_images: tuple[bytes, ...] = ()

    backend = "fake"

    def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str:
        self.calls.append((image, languages))
        if image in self.fail_images:
            raise RuntimeError("/private/provider --token secret stderr details")
        return f" OCR {image.decode()}\x00\r\n"


def test_selective_ocr_targets_only_requested_pdf_pages_and_preserves_native_order() -> None:
    document = _pdf_document()
    renderer = FakeRenderer(calls=[])
    adapter = FakeOCR(calls=[])

    result = apply_selective_ocr(
        document,
        b"pdf-source",
        adapter=adapter,
        renderer=renderer,
        languages=(" ENG ", "chi_SIM", "eng"),
        max_pixels=64,
        timeout_seconds=0.5,
        max_evidence_bytes=1024,
        max_text_chars=100,
    )

    assert renderer.calls == [2, 3]
    assert adapter.calls == [
        (b"page-2", ("eng", "chi_sim")),
        (b"page-3", ("eng", "chi_sim")),
    ]
    assert result.document.pages[0] == document.pages[0]
    assert result.document.pages[1].blocks[0] == document.pages[1].blocks[0]
    assert [block.text for block in result.document.pages[1].blocks] == [
        "garbled native fragment",
        "OCR page-2",
    ]
    assert [block.order for block in result.document.pages[1].blocks] == [0, 1]
    assert result.document.pages[1].blocks[1].source_pointer == "lesson.pdf#page=2&ocr=1"
    assert result.document.pages[1].blocks[1].page_number == 2
    assert [block.source_pointer for block in result.document.blocks] == [
        "lesson.pdf#page=1&block=1",
        "lesson.pdf#page=2&block=1",
        "lesson.pdf#page=2&ocr=1",
        "lesson.pdf#page=3&ocr=1",
    ]
    assert [checkpoint.page_number for checkpoint in result.checkpoints] == [2, 3]
    assert all(checkpoint.status is OCRPageStatus.SUCCEEDED for checkpoint in result.checkpoints)
    assert result.checkpoints[0].text == "OCR page-2"
    assert result.checkpoints[0].evidence is not None
    assert result.checkpoints[0].evidence.image == b"page-2"
    assert result.checkpoints[0].evidence.source_pointer == "lesson.pdf#page=2&evidence=ocr"
    assert len(result.checkpoints[0].evidence.sha256) == 64
    assert result.document.needs_ocr is False


def test_image_ocr_uses_original_image_bytes_without_pdf_renderer() -> None:
    page = ParsedPage(page_number=1, blocks=(), needs_ocr=True, width=3, height=2)
    document = ParsedDocument(
        source_name="scan.png",
        media_type="image/png",
        pages=(page,),
    )
    adapter = FakeOCR(calls=[])

    result = apply_selective_ocr(
        document,
        b"png-bytes",
        adapter=adapter,
        renderer=None,
        languages=("eng",),
        max_pixels=6,
        timeout_seconds=1.0,
        max_evidence_bytes=32,
        max_text_chars=100,
    )

    assert adapter.calls == [(b"png-bytes", ("eng",))]
    assert result.checkpoints[0].evidence is not None
    assert result.checkpoints[0].evidence.media_type == "image/png"
    assert (result.checkpoints[0].evidence.width, result.checkpoints[0].evidence.height) == (3, 2)
    assert result.document.pages[0].blocks[0].source_pointer == "scan.png#page=1&ocr=1"


def test_page_failure_is_redacted_checkpointed_and_does_not_discard_later_success() -> None:
    document = _pdf_document()
    renderer = FakeRenderer(calls=[])
    adapter = FakeOCR(calls=[], fail_images=(b"page-2",))

    result = apply_selective_ocr(
        document,
        b"pdf-source",
        adapter=adapter,
        renderer=renderer,
        languages=("eng",),
        max_pixels=64,
        timeout_seconds=0.5,
        max_evidence_bytes=1024,
        max_text_chars=100,
    )

    failed, succeeded = result.checkpoints
    assert failed.page_number == 2
    assert failed.status is OCRPageStatus.FAILED
    assert failed.error_code is OCRErrorCode.PROCESSING_FAILED
    assert failed.text is None
    assert failed.evidence is not None
    assert result.document.pages[1] == document.pages[1]
    assert succeeded.page_number == 3
    assert succeeded.status is OCRPageStatus.SUCCEEDED
    assert result.document.pages[2].needs_ocr is False
    assert [call[0] for call in adapter.calls] == [b"page-2", b"page-3"]
    rendered = repr(result)
    assert "provider" not in rendered
    assert "token" not in rendered
    assert "stderr" not in rendered


def test_renderer_pixel_limit_and_ocr_text_limit_become_page_failures() -> None:
    document = _pdf_document()
    adapter = FakeOCR(calls=[])

    class OversizedRenderer:
        def render_page(
            self,
            pdf: bytes,
            *,
            page_number: int,
            max_pixels: int,
            timeout_seconds: float,
        ) -> RenderedPage:
            del pdf, page_number, max_pixels, timeout_seconds
            return RenderedPage(
                image=b"oversized",
                media_type="image/x-portable-graymap",
                width=9,
                height=9,
            )

    pixel_result = apply_selective_ocr(
        document,
        b"pdf-source",
        adapter=adapter,
        renderer=OversizedRenderer(),
        languages=("eng",),
        max_pixels=64,
        timeout_seconds=1,
        max_evidence_bytes=100,
        max_text_chars=100,
    )

    assert adapter.calls == []
    assert [checkpoint.error_code for checkpoint in pixel_result.checkpoints] == [
        OCRErrorCode.LIMIT_EXCEEDED,
        OCRErrorCode.LIMIT_EXCEEDED,
    ]

    text_adapter = FakeOCR(calls=[])
    text_result = apply_selective_ocr(
        document,
        b"pdf-source",
        adapter=text_adapter,
        renderer=FakeRenderer(calls=[]),
        languages=("eng",),
        max_pixels=64,
        timeout_seconds=0.5,
        max_evidence_bytes=100,
        max_text_chars=5,
    )

    assert len(text_adapter.calls) == 2
    assert [checkpoint.error_code for checkpoint in text_result.checkpoints] == [
        OCRErrorCode.LIMIT_EXCEEDED,
        OCRErrorCode.LIMIT_EXCEEDED,
    ]
    assert all(checkpoint.evidence is not None for checkpoint in text_result.checkpoints)
    assert text_result.document == document

def test_pixel_and_evidence_limits_fail_closed_before_ocr() -> None:
    page = ParsedPage(page_number=1, blocks=(), needs_ocr=True, width=10, height=10)
    document = ParsedDocument(source_name="scan.png", media_type="image/png", pages=(page,))
    adapter = FakeOCR(calls=[])

    pixel_result = apply_selective_ocr(
        document,
        b"small",
        adapter=adapter,
        renderer=None,
        languages=("eng",),
        max_pixels=99,
        timeout_seconds=1,
        max_evidence_bytes=100,
        max_text_chars=100,
    )
    byte_result = apply_selective_ocr(
        document,
        b"too-many-bytes",
        adapter=adapter,
        renderer=None,
        languages=("eng",),
        max_pixels=100,
        timeout_seconds=1,
        max_evidence_bytes=4,
        max_text_chars=100,
    )

    assert adapter.calls == []
    assert pixel_result.checkpoints[0].error_code is OCRErrorCode.LIMIT_EXCEEDED
    assert pixel_result.checkpoints[0].evidence is None
    assert byte_result.checkpoints[0].error_code is OCRErrorCode.LIMIT_EXCEEDED
    assert byte_result.checkpoints[0].evidence is None


@pytest.mark.parametrize(
    ("languages", "expected"),
    [
        ((" ENG ", "chi_SIM", "eng"), ("eng", "chi_sim")),
        ("eng,chi_sim,eng", ("eng", "chi_sim")),
    ],
)
def test_ocr_languages_are_allowlisted_and_deduplicated(
    languages: object,
    expected: tuple[str, ...],
) -> None:
    assert normalize_ocr_languages(languages) == expected


@pytest.mark.parametrize(
    "languages",
    [(), ("deu",), ("eng", "--psm 6"), ("../../chi_sim",), True, 1],
)
def test_ocr_languages_reject_empty_unknown_and_parameter_injection(languages: object) -> None:
    with pytest.raises(ValueError, match="OCR languages") as error:
        normalize_ocr_languages(languages)

    assert repr(languages) not in str(error.value)


@pytest.mark.parametrize(
    "override",
    [
        {"max_pixels": 0},
        {"max_pixels": True},
        {"max_pixels": 1.5},
        {"timeout_seconds": 0},
        {"timeout_seconds": -1},
        {"timeout_seconds": True},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": float("nan")},
        {"max_evidence_bytes": 0},
        {"max_text_chars": False},
    ],
)
def test_selective_ocr_rejects_invalid_resource_limits(override: dict[str, object]) -> None:
    kwargs: dict[str, object] = {
        "max_pixels": 64,
        "timeout_seconds": 1.0,
        "max_evidence_bytes": 1024,
        "max_text_chars": 100,
    }
    kwargs.update(override)

    with pytest.raises(ValueError, match="OCR limits"):
        apply_selective_ocr(
            _pdf_document(),
            b"pdf-source",
            adapter=FakeOCR(calls=[]),
            renderer=FakeRenderer(calls=[]),
            languages=("eng",),
            **kwargs,
        )


def test_tesseract_adapter_uses_safe_argument_list_stdin_stdout_and_hard_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=b" recognized\x00\r\ntext \n",
            stderr=b"provider stderr must stay private",
        )

    monkeypatch.setattr("tutor_api.knowledge.ocr.subprocess.run", fake_run)
    adapter = TesseractOCRAdapter(timeout_seconds=1.25)

    text = adapter.extract_text(b"P5\n1 1\n255\n\x00", languages=("chi_sim", "eng", "eng"))

    assert text == "recognized\ntext"
    assert captured["command"] == ["tesseract", "stdin", "stdout", "-l", "chi_sim+eng"]
    assert captured["input"] == b"P5\n1 1\n255\n\x00"
    assert captured["capture_output"] is True
    assert captured["timeout"] == 1.25
    assert captured["check"] is False
    assert captured["shell"] is False


def test_tesseract_timeout_maps_to_context_free_public_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"C:\\secret\\provider.exe --token hidden stderr"

    def timeout(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise subprocess.TimeoutExpired("secret-command", 0.01, stderr=secret)

    monkeypatch.setattr("tutor_api.knowledge.ocr.subprocess.run", timeout)

    with pytest.raises(OCRError) as raised:
        TesseractOCRAdapter(timeout_seconds=0.01).extract_text(
            b"image",
            languages=("eng",),
        )

    assert raised.value.code is OCRErrorCode.TIMEOUT
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "secret" not in repr(raised.value)
    assert "token" not in repr(raised.value)


def _sleeping_render_worker(*args: object) -> None:
    del args
    time.sleep(5)


def test_pdfium_renderer_enforces_wall_clock_timeout_in_isolated_process() -> None:
    renderer = PDFiumPageRenderer(worker=_sleeping_render_worker)
    started = time.monotonic()

    with pytest.raises(OCRError) as raised:
        renderer.render_page(
            b"pdf-data",
            page_number=1,
            max_pixels=100,
            timeout_seconds=0.05,
        )

    assert time.monotonic() - started < 2.0
    assert raised.value.code is OCRErrorCode.TIMEOUT
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
