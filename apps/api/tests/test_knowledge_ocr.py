from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

import tutor_api.knowledge.ocr as ocr_module
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

_CREATE_SUSPENDED = getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)


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

    def extract_text(
        self,
        image: bytes,
        *,
        languages: tuple[str, ...],
        timeout_seconds: float | None = None,
    ) -> str:
        assert timeout_seconds is None or timeout_seconds > 0
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
        {"max_ocr_pages": 0},
        {"max_ocr_pages": True},
        {"max_total_evidence_bytes": 0},
        {"max_total_text_chars": False},
        {"max_total_seconds": 0},
        {"max_total_seconds": float("inf")},
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args_file = tmp_path / "args.txt"
    input_file = tmp_path / "input.bin"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCR_ARGS_FILE", str(args_file))
    monkeypatch.setenv("OCR_INPUT_FILE", str(input_file))
    _write_tesseract_helper(
        tmp_path,
        """import os
import sys
from pathlib import Path

Path(os.environ["OCR_ARGS_FILE"]).write_text("\\n".join(sys.argv[1:]), encoding="utf-8")
Path(os.environ["OCR_INPUT_FILE"]).write_bytes(sys.stdin.buffer.read())
sys.stderr.write("provider stderr must stay private")
sys.stdout.buffer.write(b" recognized\\x00\\r\\ntext \\n")
""",
    )
    adapter = TesseractOCRAdapter(executable=sys.executable, timeout_seconds=1.25)

    text = adapter.extract_text(b"P5\n1 1\n255\n\x00", languages=("chi_sim", "eng", "eng"))

    assert text == "recognized\ntext"
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "stdout",
        "-l",
        "chi_sim+eng",
    ]
    assert input_file.read_bytes() == b"P5\n1 1\n255\n\x00"


def test_tesseract_child_environment_filters_coverage_and_preserves_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_file = tmp_path / "environment.txt"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCR_ENV_MARKER", "ocr-marker")
    monkeypatch.setenv("KNOWLEDGE_BUSINESS_MARKER", "business-marker")
    coverage_variables = (
        "COV_CORE_SOURCE",
        "COV_CORE_CONFIG",
        "COV_CORE_DATAFILE",
        "COV_CORE_BRANCH",
        "COVERAGE_PROCESS_START",
    )
    for index, variable in enumerate(coverage_variables):
        monkeypatch.setenv(variable, f"coverage-{index}")

    _write_tesseract_helper(
        tmp_path,
        """import os
from pathlib import Path

Path(os.environ["OCR_ENV_FILE"]).write_text(
    "\\n".join(f"{key}={value}" for key, value in sorted(os.environ.items())),
    encoding="utf-8",
)
print("recognized")
""",
    )
    monkeypatch.setenv("OCR_ENV_FILE", str(environment_file))
    parent_environment = dict(os.environ)
    captured_environments: list[dict[str, str]] = []
    real_popen = ocr_module.subprocess.Popen

    def recording_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        captured_environments.append(dict(kwargs["env"]))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(ocr_module.subprocess, "Popen", recording_popen)

    assert TesseractOCRAdapter(executable=sys.executable).extract_text(
        b"image",
        languages=("eng",),
    ) == "recognized"

    child_environment = captured_environments[0]
    assert all(variable not in child_environment for variable in coverage_variables)
    assert child_environment["OCR_ENV_MARKER"] == "ocr-marker"
    assert child_environment["KNOWLEDGE_BUSINESS_MARKER"] == "business-marker"
    assert environment_file.read_text(encoding="utf-8").splitlines() == [
        f"{key}={value}"
        for key, value in sorted(child_environment.items())
    ]
    assert dict(os.environ) == parent_environment


@pytest.mark.skipif(os.name == "nt", reason="POSIX deadline contract")
def test_tesseract_posix_deadline_is_created_before_popen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def recording_monotonic() -> float:
        events.append("deadline")
        return 100.0

    def failing_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del args
        events.append("popen")
        assert kwargs["start_new_session"] is True
        raise OSError("private Popen failure")

    monkeypatch.setattr(ocr_module.time, "monotonic", recording_monotonic)
    monkeypatch.setattr(ocr_module.subprocess, "Popen", failing_popen)

    with pytest.raises(OCRError) as raised:
        TesseractOCRAdapter(
            executable="ignored",
            timeout_seconds=1.0,
            max_output_bytes=1024,
        ).extract_text(b"image", languages=("eng",))

    assert raised.value.code is OCRErrorCode.PROCESSING_FAILED
    assert events == ["deadline", "popen"]



@pytest.mark.skipif(os.name != "nt", reason="Windows secure startup contract")
def test_tesseract_windows_deadline_starts_after_job_assignment_and_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeStream:
        def close(self) -> None:
            pass

    class FakeProcess:
        pid = 1234
        returncode = 0

        def __init__(self) -> None:
            self.stdin = FakeStream()
            self.stdout = FakeStream()

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

    process = FakeProcess()

    class FakeBoundary:
        def __init__(self, owned_process: FakeProcess) -> None:
            assert owned_process is process
            events.append("job-assigned")

        @property
        def windows_job_assigned(self) -> bool:
            return True

        def terminate(self) -> None:
            events.append("terminate")

        def close(self) -> None:
            events.append("close")

    class FakeThread:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def start(self) -> None:
            pass

        def join(self, timeout: float | None = None) -> None:
            del timeout

    def recording_popen(*args: object, **kwargs: object) -> FakeProcess:
        del args
        events.append("popen")
        assert kwargs["creationflags"] & _CREATE_SUSPENDED
        return process

    def recording_resume(process_id: int) -> bool:
        assert process_id == process.pid
        events.append("resume")
        return True

    monotonic_values = iter((100.0, 101.0))

    def recording_monotonic() -> float:
        events.append("deadline")
        return next(monotonic_values)

    monkeypatch.setattr(ocr_module.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(ocr_module, "_ProcessBoundary", FakeBoundary)
    monkeypatch.setattr(ocr_module, "_resume_windows_process", recording_resume)
    monkeypatch.setattr(ocr_module.threading, "Thread", FakeThread)
    monkeypatch.setattr(ocr_module.time, "monotonic", recording_monotonic)

    with pytest.raises(OCRError) as raised:
        TesseractOCRAdapter(
            executable="ignored",
            timeout_seconds=0.5,
            max_output_bytes=1024,
        ).extract_text(b"image", languages=("eng",))

    assert raised.value.code is OCRErrorCode.TIMEOUT
    assert events.index("popen") < events.index("job-assigned")
    assert events.index("job-assigned") < events.index("resume")
    assert events.index("resume") < events.index("deadline")


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended process and cleanup behavior")
def test_tesseract_windows_resume_failure_cleans_suspended_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    side_effect_file = tmp_path / "resume-must-not-run.txt"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCR_SIDE_EFFECT_FILE", str(side_effect_file))
    _write_tesseract_helper(
        tmp_path,
        """import os
import time
from pathlib import Path

Path(os.environ["OCR_SIDE_EFFECT_FILE"]).write_text("ran", encoding="ascii")
time.sleep(5)
""",
    )
    real_popen = ocr_module.subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    resume_calls: list[int] = []
    terminate_calls: list[int] = []
    close_calls: list[int] = []


    def recording_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        creationflags = kwargs["creationflags"]
        assert isinstance(creationflags, int)
        assert kwargs["creationflags"] & _CREATE_SUSPENDED
        assert creationflags & subprocess.CREATE_NEW_PROCESS_GROUP
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    def fake_create_windows_job(process: subprocess.Popen[bytes]) -> int:
        assert process is processes[0]
        return 1

    def failing_resume(process_id: int) -> bool:
        resume_calls.append(process_id)
        return False

    def terminate_suspended_child(job_handle: int) -> None:
        terminate_calls.append(job_handle)
        processes[0].terminate()
        processes[0].wait(timeout=1.0)

    def close_fake_job(job_handle: int) -> None:
        close_calls.append(job_handle)

    monkeypatch.setattr(ocr_module.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(ocr_module, "_create_windows_job", fake_create_windows_job)
    monkeypatch.setattr(ocr_module, "_resume_windows_process", failing_resume)
    monkeypatch.setattr(ocr_module, "_terminate_windows_job", terminate_suspended_child)
    monkeypatch.setattr(ocr_module, "_close_windows_handle", close_fake_job)

    try:
        with pytest.raises(OCRError) as raised:
            TesseractOCRAdapter(
                executable=sys.executable,
                timeout_seconds=1.0,
            ).extract_text(b"image", languages=("eng",))

        assert raised.value.code is OCRErrorCode.PROCESSING_FAILED
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert len(processes) == 1
        assert resume_calls == [processes[0].pid]
        assert terminate_calls == [1]
        assert close_calls == [1]
        assert not side_effect_file.exists()
        assert processes[0].poll() is not None
    finally:
        _stop_recorded_processes(processes)



def test_tesseract_timeout_maps_to_context_free_public_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_tesseract_helper(
        tmp_path,
        """import sys
import time

sys.stderr.write("C:\\secret\\provider.exe --token hidden stderr")
sys.stderr.flush()
time.sleep(5)
""",
    )

    with pytest.raises(OCRError) as raised:
        TesseractOCRAdapter(
            executable=sys.executable,
            timeout_seconds=0.1,
        ).extract_text(b"image", languages=("eng",))

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


def _write_tesseract_helper(tmp_path: Path, source: str) -> None:
    (tmp_path / "stdin").write_text(source, encoding="utf-8")


def _wait_for_pid_file(path: Path, *, timeout_seconds: float = 1.0) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return int(path.read_text(encoding="ascii"))
        time.sleep(0.01)
    raise AssertionError(f"helper did not write PID file: {path.name}")


def _process_is_running(pid: int) -> bool:
    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        fields = proc_stat.read_text(encoding="ascii").split()
        return len(fields) < 3 or fields[2] != "Z"
    return True


def _assert_process_stops(pid: int, *, timeout_seconds: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline and _process_is_running(pid):
        time.sleep(0.01)
    assert not _process_is_running(pid)


def _stop_recorded_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)


def _live_ocr_io_threads() -> set[threading.Thread]:
    targets = {ocr_module._read_process_stdout, ocr_module._write_process_stdin}
    return {
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("ocr-") or getattr(thread, "_target", None) in targets
    }


def test_tesseract_second_thread_start_failure_cleans_process_and_started_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_pid_file = tmp_path / "thread-start-parent.pid"
    child_pid_file = tmp_path / "thread-start-child.pid"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCR_PARENT_PID", str(parent_pid_file))
    monkeypatch.setenv("OCR_CHILD_PID", str(child_pid_file))
    _write_tesseract_helper(
        tmp_path,
        """import os
import subprocess
import sys
import time
from pathlib import Path

Path(os.environ["OCR_PARENT_PID"]).write_text(str(os.getpid()), encoding="ascii")
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(5)"],
    stdin=sys.stdin,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
Path(os.environ["OCR_CHILD_PID"]).write_text(str(child.pid), encoding="ascii")
time.sleep(5)
""",
    )
    real_popen = ocr_module.subprocess.Popen
    real_start = ocr_module.threading.Thread.start
    processes: list[subprocess.Popen[bytes]] = []
    helper_pids: list[int] = []
    io_start_count = 0

    def recording_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    def fail_second_io_start(thread: threading.Thread) -> None:
        nonlocal io_start_count
        target = getattr(thread, "_target", None)
        if target in {ocr_module._read_process_stdout, ocr_module._write_process_stdin}:
            io_start_count += 1
            if io_start_count == 2:
                helper_pids.extend(
                    [
                        _wait_for_pid_file(parent_pid_file, timeout_seconds=3.0),
                        _wait_for_pid_file(child_pid_file, timeout_seconds=3.0),
                    ]
                )
                raise RuntimeError("private thread-start secret")
        real_start(thread)

    monkeypatch.setattr(ocr_module.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(ocr_module.threading.Thread, "start", fail_second_io_start)
    before_threads = _live_ocr_io_threads()

    try:
        with pytest.raises(OCRError) as raised:
            TesseractOCRAdapter(
                executable=sys.executable,
                timeout_seconds=2.0,
            ).extract_text(b"image", languages=("eng",))

        assert raised.value.code is OCRErrorCode.PROCESSING_FAILED
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert "secret" not in repr(raised.value)
        assert io_start_count == 2
        assert len(processes) == 1
        assert processes[0].poll() is not None
        assert len(helper_pids) == 2
        for helper_pid in helper_pids:
            _assert_process_stops(helper_pid)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and _live_ocr_io_threads() != before_threads:
            time.sleep(0.01)
        assert _live_ocr_io_threads() == before_threads
    finally:
        _stop_recorded_processes(processes)


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended process and Job Object behavior")
def test_tesseract_windows_job_failure_never_resumes_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    side_effect_file = tmp_path / "must-not-run.txt"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCR_SIDE_EFFECT_FILE", str(side_effect_file))
    _write_tesseract_helper(
        tmp_path,
        """import os
import time
from pathlib import Path

Path(os.environ["OCR_SIDE_EFFECT_FILE"]).write_text("ran", encoding="ascii")
time.sleep(5)
""",
    )
    real_popen = ocr_module.subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    resume_calls: list[int] = []
    close_calls: list[int] = []
    created_job_handles: list[int] = []
    assigned_process_handles: list[int] = []

    class FakeWinFunction:
        def __init__(self, callback: Callable[..., object]) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)

    created_job_handle = 123

    def create_job_object(*args: object) -> int:
        del args
        created_job_handles.append(created_job_handle)
        return created_job_handle

    def set_job_information(*args: object) -> bool:
        del args
        return True

    def fail_job_assignment(job_handle: int, process_handle: int) -> bool:
        assigned_process_handles.append(process_handle)
        assert job_handle == created_job_handle
        return False

    def close_job_handle(job_handle: int) -> bool:
        close_calls.append(job_handle)
        return True

    class FakeKernel32:
        def __init__(self) -> None:
            self.CreateJobObjectW = FakeWinFunction(create_job_object)
            self.SetInformationJobObject = FakeWinFunction(set_job_information)
            self.AssignProcessToJobObject = FakeWinFunction(fail_job_assignment)
            self.CloseHandle = FakeWinFunction(close_job_handle)

    fake_kernel32 = FakeKernel32()

    def recording_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        creationflags = kwargs["creationflags"]
        assert isinstance(creationflags, int)
        assert creationflags & _CREATE_SUSPENDED
        assert creationflags & subprocess.CREATE_NEW_PROCESS_GROUP
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    def forbidden_resume(process_id: int) -> bool:
        resume_calls.append(process_id)
        return False

    monkeypatch.setattr(ocr_module.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: fake_kernel32)
    monkeypatch.setattr(ocr_module, "_resume_windows_process", forbidden_resume)

    try:
        with pytest.raises(OCRError) as raised:
            TesseractOCRAdapter(
                executable=sys.executable,
                timeout_seconds=1.0,
            ).extract_text(b"image", languages=("eng",))

        assert raised.value.code is OCRErrorCode.PROCESSING_FAILED
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert resume_calls == []
        assert created_job_handles == [created_job_handle]
        assert assigned_process_handles == [processes[0]._handle]
        assert close_calls == [created_job_handle]
        assert not side_effect_file.exists()
        assert len(processes) == 1
        assert processes[0].poll() is not None
    finally:
        _stop_recorded_processes(processes)


def test_tesseract_rejects_input_before_starting_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_popen(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("Popen must not run for oversized input")

    monkeypatch.setattr("tutor_api.knowledge.ocr.subprocess.Popen", forbidden_popen)
    adapter = TesseractOCRAdapter(max_input_bytes=4)

    with pytest.raises(OCRError) as raised:
        adapter.extract_text(b"12345", languages=("eng",))

    assert raised.value.code is OCRErrorCode.LIMIT_EXCEEDED


def test_tesseract_streams_bounded_stdout_and_terminates_early(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_file = tmp_path / "writer.pid"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCR_HELPER_PID", str(pid_file))
    _write_tesseract_helper(
        tmp_path,
        """import os
import subprocess
import sys
import threading
import time
from pathlib import Path

Path(os.environ["OCR_HELPER_PID"]).write_text(str(os.getpid()), encoding="ascii")
sys.stdin.buffer.read()
chunk = b"x" * 4096
while True:
    sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
    time.sleep(0.01)
""",
    )
    adapter = TesseractOCRAdapter(
        executable=sys.executable,
        timeout_seconds=5.0,
        max_input_bytes=1024,
        max_output_bytes=1024,
    )
    started = time.monotonic()

    with pytest.raises(OCRError) as raised:
        adapter.extract_text(b"image", languages=("eng",))

    elapsed = time.monotonic() - started
    pid = _wait_for_pid_file(pid_file)
    assert raised.value.code is OCRErrorCode.LIMIT_EXCEEDED
    assert elapsed < 1.0
    _assert_process_stops(pid)


def test_tesseract_timeout_kills_descendant_holding_pipes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows_jobs: list[int | None] = []
    if os.name == "nt":
        real_create_windows_job = ocr_module._create_windows_job

        def recording_create_windows_job(process: subprocess.Popen[bytes]) -> int | None:
            job = real_create_windows_job(process)
            windows_jobs.append(job)
            return job

        monkeypatch.setattr(ocr_module, "_create_windows_job", recording_create_windows_job)

    parent_pid_file = tmp_path / "parent.pid"
    child_pid_file = tmp_path / "child.pid"
    survivor_file = tmp_path / "survived.txt"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCR_PARENT_PID", str(parent_pid_file))
    monkeypatch.setenv("OCR_CHILD_PID", str(child_pid_file))
    monkeypatch.setenv("OCR_SURVIVOR_FILE", str(survivor_file))
    _write_tesseract_helper(
        tmp_path,
        """import os
import subprocess
import sys
import time
from pathlib import Path

Path(os.environ["OCR_PARENT_PID"]).write_text(str(os.getpid()), encoding="ascii")
child_code = (
    "import os\\n"
    "import time\\n"
    "from pathlib import Path\\n"
    "Path(os.environ['OCR_CHILD_PID']).write_text(str(os.getpid()), encoding='ascii')\\n"
    "time.sleep(0.6)\\n"
    "Path(os.environ['OCR_SURVIVOR_FILE']).write_text('alive', encoding='ascii')\\n"
    "time.sleep(5)\\n"
)
subprocess.Popen([sys.executable, "-c", child_code])
time.sleep(5)
""",
    )
    adapter = TesseractOCRAdapter(
        executable=sys.executable,
        timeout_seconds=0.2,
        max_input_bytes=16 * 1024 * 1024,
        max_output_bytes=1024,
    )
    started = time.monotonic()

    with pytest.raises(OCRError) as raised:
        adapter.extract_text(b"x" * (8 * 1024 * 1024), languages=("eng",))

    elapsed = time.monotonic() - started
    parent_pid = _wait_for_pid_file(parent_pid_file)
    child_pid = _wait_for_pid_file(child_pid_file)
    assert raised.value.code is OCRErrorCode.TIMEOUT
    assert elapsed < 1.0
    if os.name == "nt":
        assert windows_jobs and all(job is not None for job in windows_jobs)
    _assert_process_stops(parent_pid)
    _assert_process_stops(child_pid)
    time.sleep(0.7)
    assert not survivor_file.exists()


def test_tesseract_timeout_kills_descendant_inheriting_only_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_pid_file = tmp_path / "stdin-parent.pid"
    child_pid_file = tmp_path / "stdin-child.pid"
    survivor_file = tmp_path / "stdin-survived.txt"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCR_PARENT_PID", str(parent_pid_file))
    monkeypatch.setenv("OCR_CHILD_PID", str(child_pid_file))
    monkeypatch.setenv("OCR_SURVIVOR_FILE", str(survivor_file))
    _write_tesseract_helper(
        tmp_path,
        """import os
import subprocess
import sys
from pathlib import Path

Path(os.environ["OCR_PARENT_PID"]).write_text(str(os.getpid()), encoding="ascii")
child_code = (
    "import os\\n"
    "import time\\n"
    "from pathlib import Path\\n"
    "Path(os.environ['OCR_CHILD_PID']).write_text(str(os.getpid()), encoding='ascii')\\n"
    "time.sleep(0.6)\\n"
    "Path(os.environ['OCR_SURVIVOR_FILE']).write_text('alive', encoding='ascii')\\n"
    "time.sleep(5)\\n"
)
subprocess.Popen(
    [sys.executable, "-c", child_code],
    stdin=sys.stdin,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
""",
    )
    adapter = TesseractOCRAdapter(
        executable=sys.executable,
        timeout_seconds=0.2,
        max_input_bytes=16 * 1024 * 1024,
        max_output_bytes=1024,
    )
    started = time.monotonic()

    with pytest.raises(OCRError) as raised:
        adapter.extract_text(b"x" * (8 * 1024 * 1024), languages=("eng",))

    elapsed = time.monotonic() - started
    parent_pid = _wait_for_pid_file(parent_pid_file)
    child_pid = _wait_for_pid_file(child_pid_file)
    assert raised.value.code is OCRErrorCode.TIMEOUT
    assert 0.1 <= elapsed < 1.0
    _assert_process_stops(parent_pid)
    _assert_process_stops(child_pid)
    time.sleep(0.7)
    assert not survivor_file.exists()


@dataclass
class BudgetRenderer:
    calls: list[tuple[int, float]]
    images: dict[int, bytes]
    delays: dict[int, float] | None = None

    def render_page(
        self,
        pdf: bytes,
        *,
        page_number: int,
        max_pixels: int,
        timeout_seconds: float,
    ) -> RenderedPage:
        del pdf, max_pixels
        self.calls.append((page_number, timeout_seconds))
        if self.delays and page_number in self.delays:
            time.sleep(self.delays[page_number])
        return RenderedPage(
            image=self.images[page_number],
            media_type="image/x-portable-graymap",
            width=1,
            height=1,
        )


@dataclass
class BudgetOCR:
    calls: list[bytes]
    texts: dict[bytes, str]

    backend = "fake"

    def extract_text(
        self,
        image: bytes,
        *,
        languages: tuple[str, ...],
        timeout_seconds: float | None = None,
    ) -> str:
        assert languages == ("eng",)
        assert timeout_seconds is None or timeout_seconds > 0
        self.calls.append(image)
        return self.texts[image]


def _selected_pdf_document(page_count: int) -> ParsedDocument:
    pages = tuple(
        ParsedPage(page_number=page_number, blocks=(), needs_ocr=True)
        for page_number in range(1, page_count + 1)
    )
    return ParsedDocument(
        source_name="budget.pdf",
        media_type="application/pdf",
        blocks=(),
        pages=pages,
    )


def test_selective_ocr_rejects_legacy_adapter_before_blocking_body() -> None:
    class LegacyBlockingOCR:
        backend = "legacy"

        def __init__(self) -> None:
            self.entered = False

        def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str:
            del image, languages
            self.entered = True
            time.sleep(0.5)
            return "late"

    adapter = LegacyBlockingOCR()
    renderer = BudgetRenderer(calls=[], images={1: b"a"})
    started = time.monotonic()

    result = apply_selective_ocr(
        _selected_pdf_document(1),
        b"pdf-source",
        adapter=adapter,
        renderer=renderer,
        languages=("eng",),
        max_pixels=10,
        timeout_seconds=1.0,
        max_evidence_bytes=10,
        max_text_chars=10,
        max_ocr_pages=1,
        max_total_evidence_bytes=100,
        max_total_text_chars=100,
        max_total_seconds=0.1,
    )

    assert time.monotonic() - started < 0.2
    assert adapter.entered is False
    assert result.checkpoints[0].status is OCRPageStatus.FAILED
    assert result.checkpoints[0].error_code is OCRErrorCode.PROCESSING_FAILED


def test_selective_ocr_passes_positive_remaining_time_to_every_adapter() -> None:
    class TimedOCR:
        backend = "timed"

        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def extract_text(
            self,
            image: bytes,
            *,
            languages: tuple[str, ...],
            timeout_seconds: float | None = None,
        ) -> str:
            del image, languages
            assert timeout_seconds is not None
            self.timeouts.append(timeout_seconds)
            return "text"

    adapter = TimedOCR()
    renderer = BudgetRenderer(calls=[], images={1: b"a"})

    result = apply_selective_ocr(
        _selected_pdf_document(1),
        b"pdf-source",
        adapter=adapter,
        renderer=renderer,
        languages=("eng",),
        max_pixels=10,
        timeout_seconds=1.0,
        max_evidence_bytes=10,
        max_text_chars=10,
        max_ocr_pages=1,
        max_total_evidence_bytes=100,
        max_total_text_chars=100,
        max_total_seconds=0.2,
    )

    assert result.checkpoints[0].status is OCRPageStatus.SUCCEEDED
    assert len(adapter.timeouts) == 1
    assert 0 < adapter.timeouts[0] < 0.21


def test_selective_ocr_enforces_cumulative_page_budget_before_render() -> None:
    renderer = BudgetRenderer(calls=[], images={1: b"a", 2: b"b", 3: b"c"})
    adapter = BudgetOCR(calls=[], texts={b"a": "a", b"b": "b", b"c": "c"})

    result = apply_selective_ocr(
        _selected_pdf_document(3),
        b"pdf-source",
        adapter=adapter,
        renderer=renderer,
        languages=("eng",),
        max_pixels=10,
        timeout_seconds=1.0,
        max_evidence_bytes=10,
        max_text_chars=10,
        max_ocr_pages=2,
        max_total_evidence_bytes=100,
        max_total_text_chars=100,
        max_total_seconds=10.0,
    )

    assert [call[0] for call in renderer.calls] == [1, 2]
    assert adapter.calls == [b"a", b"b"]
    assert [checkpoint.error_code for checkpoint in result.checkpoints] == [
        None,
        None,
        OCRErrorCode.LIMIT_EXCEEDED,
    ]


def test_selective_ocr_enforces_cumulative_evidence_budget_before_ocr() -> None:
    renderer = BudgetRenderer(calls=[], images={1: b"aaaa", 2: b"bbbb", 3: b"c"})
    adapter = BudgetOCR(calls=[], texts={b"aaaa": "a", b"bbbb": "b", b"c": "c"})

    result = apply_selective_ocr(
        _selected_pdf_document(3),
        b"pdf-source",
        adapter=adapter,
        renderer=renderer,
        languages=("eng",),
        max_pixels=10,
        timeout_seconds=1.0,
        max_evidence_bytes=10,
        max_text_chars=10,
        max_ocr_pages=3,
        max_total_evidence_bytes=6,
        max_total_text_chars=100,
        max_total_seconds=10.0,
    )

    assert [call[0] for call in renderer.calls] == [1, 2]
    assert adapter.calls == [b"aaaa"]
    assert result.checkpoints[1].error_code is OCRErrorCode.LIMIT_EXCEEDED
    assert result.checkpoints[1].evidence is None
    assert result.checkpoints[2].error_code is OCRErrorCode.LIMIT_EXCEEDED


def test_selective_ocr_enforces_cumulative_text_budget_after_ocr() -> None:
    renderer = BudgetRenderer(calls=[], images={1: b"a", 2: b"b", 3: b"c"})
    adapter = BudgetOCR(calls=[], texts={b"a": "1234", b"b": "5678", b"c": "9"})

    result = apply_selective_ocr(
        _selected_pdf_document(3),
        b"pdf-source",
        adapter=adapter,
        renderer=renderer,
        languages=("eng",),
        max_pixels=10,
        timeout_seconds=1.0,
        max_evidence_bytes=10,
        max_text_chars=10,
        max_ocr_pages=3,
        max_total_evidence_bytes=100,
        max_total_text_chars=6,
        max_total_seconds=10.0,
    )

    assert [call[0] for call in renderer.calls] == [1, 2]
    assert adapter.calls == [b"a", b"b"]
    assert result.checkpoints[0].text == "1234"
    assert result.checkpoints[1].error_code is OCRErrorCode.LIMIT_EXCEEDED
    assert result.checkpoints[1].text is None
    assert result.checkpoints[2].error_code is OCRErrorCode.LIMIT_EXCEEDED


def test_selective_ocr_enforces_document_deadline_and_passes_remaining_time() -> None:
    renderer = BudgetRenderer(
        calls=[],
        images={1: b"a", 2: b"b"},
        delays={1: 0.08},
    )
    adapter = BudgetOCR(calls=[], texts={b"a": "a", b"b": "b"})

    result = apply_selective_ocr(
        _selected_pdf_document(2),
        b"pdf-source",
        adapter=adapter,
        renderer=renderer,
        languages=("eng",),
        max_pixels=10,
        timeout_seconds=1.0,
        max_evidence_bytes=10,
        max_text_chars=10,
        max_ocr_pages=2,
        max_total_evidence_bytes=100,
        max_total_text_chars=100,
        max_total_seconds=0.05,
    )

    assert [call[0] for call in renderer.calls] == [1]
    assert 0 < renderer.calls[0][1] <= 0.05
    assert adapter.calls == []
    assert [checkpoint.error_code for checkpoint in result.checkpoints] == [
        OCRErrorCode.LIMIT_EXCEEDED,
        OCRErrorCode.LIMIT_EXCEEDED,
    ]


def test_selective_ocr_passes_document_remaining_time_to_tesseract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[float] = []

    def fake_extract(
        self: TesseractOCRAdapter,
        image: bytes,
        *,
        languages: tuple[str, ...],
        timeout_seconds: float,
    ) -> str:
        del self, image, languages
        captured.append(timeout_seconds)
        return "text"

    monkeypatch.setattr(TesseractOCRAdapter, "_extract_text_with_timeout", fake_extract)
    renderer = BudgetRenderer(calls=[], images={1: b"a"}, delays={1: 0.03})

    result = apply_selective_ocr(
        _selected_pdf_document(1),
        b"pdf-source",
        adapter=TesseractOCRAdapter(timeout_seconds=5.0),
        renderer=renderer,
        languages=("eng",),
        max_pixels=10,
        timeout_seconds=1.0,
        max_evidence_bytes=10,
        max_text_chars=10,
        max_ocr_pages=1,
        max_total_evidence_bytes=100,
        max_total_text_chars=100,
        max_total_seconds=0.2,
    )

    assert result.checkpoints[0].status is OCRPageStatus.SUCCEEDED
    assert len(captured) == 1
    assert 0 < captured[0] < 0.2


@pytest.mark.parametrize(
    "override",
    [
        {"max_input_bytes": 0},
        {"max_input_bytes": True},
        {"max_output_bytes": 0},
        {"timeout_seconds": float("nan")},
    ],
)
def test_tesseract_rejects_invalid_resource_limits(override: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="OCR limits"):
        TesseractOCRAdapter(**override)
