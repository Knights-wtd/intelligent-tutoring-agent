"""Selective OCR, isolated PDF rendering, and safe public error boundaries."""

from __future__ import annotations

import hashlib
import math
import multiprocessing
import os
import queue
import signal
import subprocess
import threading
import time
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
_DEFAULT_MAX_OCR_PAGES = 100
_DEFAULT_MAX_TOTAL_EVIDENCE_BYTES = 128 * 1024 * 1024
_DEFAULT_MAX_TOTAL_TEXT_CHARS = 5_000_000
_DEFAULT_MAX_TOTAL_SECONDS = 120.0
_DEFAULT_RENDER_SCALE = 2.0
_TESSERACT_IO_CHUNK_BYTES = 64 * 1024
_PROCESS_CLEANUP_SECONDS = 0.25


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

    def extract_text(
        self,
        image: bytes,
        *,
        languages: tuple[str, ...],
        timeout_seconds: float | None = None,
    ) -> str: ...


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

    def extract_text(
        self,
        image: bytes,
        *,
        languages: tuple[str, ...],
        timeout_seconds: float | None = None,
    ) -> str:
        del image, languages, timeout_seconds
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


class _ProcessBoundary:
    """Own a subprocess and its descendants across supported platforms."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self._windows_job = _create_windows_job(process) if os.name == "nt" else None

    @property
    def windows_job_assigned(self) -> bool:
        return self._windows_job is not None

    def terminate(self) -> None:
        if os.name == "nt":
            if self._windows_job is not None:
                _terminate_windows_job(self._windows_job)
            else:
                _terminate_direct_process(self.process)
                return
        else:
            _signal_posix_process_group(self.process.pid, signal.SIGTERM)

        if not _wait_for_process(self.process, _PROCESS_CLEANUP_SECONDS):
            if os.name == "nt":
                if self._windows_job is not None:
                    _terminate_windows_job(self._windows_job)
            else:
                _signal_posix_process_group(self.process.pid, signal.SIGKILL)
            _wait_for_process(self.process, _PROCESS_CLEANUP_SECONDS)

    def close(self) -> None:
        if os.name == "nt":
            if self._windows_job is not None:
                _close_windows_handle(self._windows_job)
                self._windows_job = None
        else:
            _signal_posix_process_group(self.process.pid, signal.SIGTERM)
            time.sleep(0.01)
            _signal_posix_process_group(self.process.pid, signal.SIGKILL)


def _wait_for_process(process: subprocess.Popen[bytes], timeout_seconds: float) -> bool:
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return process.poll() is not None
    return True


def _terminate_direct_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.terminate()
    except Exception:
        pass
    if not _wait_for_process(process, _PROCESS_CLEANUP_SECONDS):
        try:
            process.kill()
        except Exception:
            pass
        _wait_for_process(process, _PROCESS_CLEANUP_SECONDS)


def _terminate_spawned_process(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        _terminate_direct_process(process)
        return
    _signal_posix_process_group(process.pid, signal.SIGTERM)
    if not _wait_for_process(process, _PROCESS_CLEANUP_SECONDS):
        _signal_posix_process_group(process.pid, signal.SIGKILL)
        _wait_for_process(process, _PROCESS_CLEANUP_SECONDS)


def _signal_posix_process_group(process_group_id: int, sig: int) -> None:
    try:
        os.killpg(process_group_id, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _create_windows_job(process: subprocess.Popen[bytes]) -> int | None:
    if os.name != "nt":
        return None
    job_handle = 0
    try:
        import ctypes
        from ctypes import wintypes

        class JobObjectBasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JobObjectExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JobObjectBasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        job_handle = int(job)
        information = JobObjectExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        configured = kernel32.SetInformationJobObject(
            job,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        )
        assigned = configured and kernel32.AssignProcessToJobObject(job, process._handle)
        if not assigned:
            _close_windows_handle(job_handle)
            return None
        return job_handle
    except Exception:
        if job_handle:
            _close_windows_handle(job_handle)
        return None


def _terminate_windows_job(job_handle: int) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject(job_handle, 1)
    except Exception:
        pass


def _close_windows_handle(handle: int) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(handle)
    except Exception:
        pass



def _resume_windows_process(process_id: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes

        class ThreadEntry32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        if snapshot == wintypes.HANDLE(-1).value:
            return False
        resumed = False
        try:
            entry = ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            present = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while present:
                if int(entry.th32OwnerProcessID) == process_id:
                    thread_handle = kernel32.OpenThread(0x0002, False, entry.th32ThreadID)
                    if thread_handle:
                        try:
                            resumed = kernel32.ResumeThread(thread_handle) != 0xFFFFFFFF or resumed
                        finally:
                            _close_windows_handle(int(thread_handle))
                present = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            _close_windows_handle(int(snapshot))
        return resumed
    except Exception:
        return False

def _put_process_message(
    messages: queue.Queue[tuple[str, bytes | None]],
    stop: threading.Event,
    message: tuple[str, bytes | None],
) -> None:
    while not stop.is_set():
        try:
            messages.put(message, timeout=0.02)
            return
        except queue.Full:
            continue


def _read_process_stdout(
    stream: object,
    messages: queue.Queue[tuple[str, bytes | None]],
    stop: threading.Event,
) -> None:
    try:
        file_descriptor = stream.fileno()
        while not stop.is_set():
            chunk = os.read(file_descriptor, _TESSERACT_IO_CHUNK_BYTES)
            if not chunk:
                _put_process_message(messages, stop, ("eof", None))
                return
            _put_process_message(messages, stop, ("data", chunk))
    except Exception:
        _put_process_message(messages, stop, ("error", None))


def _write_process_stdin(
    stream: object,
    raw: bytes,
    done: threading.Event,
    failed: threading.Event,
) -> None:
    try:
        file_descriptor = stream.fileno()
        view = memoryview(raw)
        offset = 0
        while offset < len(view):
            offset += os.write(file_descriptor, view[offset : offset + _TESSERACT_IO_CHUNK_BYTES])
    except Exception:
        failed.set()
    finally:
        try:
            stream.close()
        except Exception:
            pass
        done.set()


def _run_tesseract_process(
    command: list[str],
    raw: bytes,
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> bytes:
    creation_kwargs: dict[str, object] = {}
    if os.name == "nt":
        creation_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004
        )
    else:
        creation_kwargs["start_new_session"] = True
        deadline = time.monotonic() + timeout_seconds

    child_environment = os.environ.copy()
    for coverage_variable in (
        "COV_CORE_SOURCE",
        "COV_CORE_CONFIG",
        "COV_CORE_DATAFILE",
        "COV_CORE_BRANCH",
        "COVERAGE_PROCESS_START",
    ):
        child_environment.pop(coverage_variable, None)

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            env=child_environment,
            **creation_kwargs,
        )
    except Exception:
        raise OCRError(OCRErrorCode.PROCESSING_FAILED) from None

    boundary: _ProcessBoundary | None = None
    stop: threading.Event | None = None
    reader: threading.Thread | None = None
    writer: threading.Thread | None = None
    reader_started = False
    writer_started = False
    stdout = bytearray()
    failure_code: OCRErrorCode | None = None

    try:
        boundary = _ProcessBoundary(process)
        if os.name == "nt":
            if not boundary.windows_job_assigned:
                raise RuntimeError("Windows Job Object assignment failed")
            if not _resume_windows_process(process.pid):
                raise RuntimeError("Windows process resume failed")
            deadline = time.monotonic() + timeout_seconds

        messages: queue.Queue[tuple[str, bytes | None]] = queue.Queue(maxsize=2)
        stop = threading.Event()
        writer_done = threading.Event()
        writer_failed = threading.Event()
        reader = threading.Thread(
            target=_read_process_stdout,
            args=(process.stdout, messages, stop),
            daemon=True,
            name="ocr-stdout-reader",
        )
        writer = threading.Thread(
            target=_write_process_stdin,
            args=(process.stdin, raw, writer_done, writer_failed),
            daemon=True,
            name="ocr-stdin-writer",
        )
        reader.start()
        reader_started = True
        writer.start()
        writer_started = True
        stdout_eof = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure_code = OCRErrorCode.TIMEOUT
                break
            try:
                kind, payload = messages.get(timeout=min(remaining, 0.05))
            except queue.Empty:
                if process.poll() is not None and stdout_eof:
                    break
                continue
            if kind == "data" and payload is not None:
                if len(stdout) + len(payload) > max_output_bytes:
                    failure_code = OCRErrorCode.LIMIT_EXCEEDED
                    break
                stdout.extend(payload)
            elif kind == "eof":
                stdout_eof = True
                if process.poll() is not None:
                    break
            else:
                failure_code = OCRErrorCode.PROCESSING_FAILED
                break

        if failure_code is None and process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not _wait_for_process(process, remaining):
                failure_code = OCRErrorCode.TIMEOUT
        if failure_code is None and not writer_done.is_set():
            remaining = max(0.0, deadline - time.monotonic())
            if not writer_done.wait(timeout=remaining):
                failure_code = OCRErrorCode.TIMEOUT
        if failure_code is None and writer_failed.is_set():
            failure_code = OCRErrorCode.PROCESSING_FAILED
        if failure_code is None and process.returncode != 0:
            failure_code = OCRErrorCode.PROCESSING_FAILED
    except OCRError as error:
        failure_code = _safe_public_code(error)
    except Exception:
        failure_code = OCRErrorCode.PROCESSING_FAILED
    finally:
        if failure_code is not None or process.poll() is None:
            if boundary is not None:
                boundary.terminate()
            else:
                _terminate_spawned_process(process)
        if stop is not None:
            stop.set()
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        if reader_started and reader is not None:
            reader.join(timeout=_PROCESS_CLEANUP_SECONDS)
        if writer_started and writer is not None:
            writer.join(timeout=_PROCESS_CLEANUP_SECONDS)
        if process.poll() is None:
            if boundary is not None:
                boundary.terminate()
            else:
                _terminate_spawned_process(process)
        if boundary is not None:
            boundary.close()
        _wait_for_process(process, _PROCESS_CLEANUP_SECONDS)

    if failure_code is not None:
        raise OCRError(failure_code) from None
    return bytes(stdout)


@dataclass(frozen=True, slots=True)
class TesseractOCRAdapter:
    """Tesseract subprocess adapter with bounded input, output, and lifetime."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_output_bytes: int = _DEFAULT_MAX_TEXT_CHARS * 4
    executable: str = "tesseract"
    max_input_bytes: int = _DEFAULT_MAX_EVIDENCE_BYTES
    backend: str = field(default="tesseract", init=False)

    def __post_init__(self) -> None:
        if not _validate_positive_finite_number(self.timeout_seconds):
            raise ValueError("OCR limits must be positive finite values")
        if not _validate_positive_int(self.max_input_bytes) or not _validate_positive_int(
            self.max_output_bytes
        ):
            raise ValueError("OCR limits must be positive finite values")
        if not isinstance(self.executable, str) or not self.executable or "\x00" in self.executable:
            raise ValueError("Tesseract executable is invalid")

    def extract_text(
        self,
        image: bytes,
        *,
        languages: tuple[str, ...],
        timeout_seconds: float | None = None,
    ) -> str:
        effective_timeout = (
            float(self.timeout_seconds)
            if timeout_seconds is None
            else min(float(self.timeout_seconds), float(timeout_seconds))
        )
        return self._extract_text_with_timeout(
            image,
            languages=languages,
            timeout_seconds=effective_timeout,
        )

    def _extract_text_with_timeout(
        self,
        image: bytes,
        *,
        languages: tuple[str, ...],
        timeout_seconds: float,
    ) -> str:
        if not _validate_positive_finite_number(timeout_seconds):
            raise OCRError(OCRErrorCode.TIMEOUT) from None
        normalized_languages = normalize_ocr_languages(languages)
        raw = bytes(image)
        if len(raw) > self.max_input_bytes:
            raise OCRError(OCRErrorCode.LIMIT_EXCEEDED) from None
        stdout = _run_tesseract_process(
            [
                self.executable,
                "stdin",
                "stdout",
                "-l",
                "+".join(normalized_languages),
            ],
            raw,
            timeout_seconds=min(float(timeout_seconds), float(self.timeout_seconds)),
            max_output_bytes=self.max_output_bytes,
        )
        try:
            decoded = stdout.decode("utf-8")
        except UnicodeDecodeError:
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
    timeout_seconds: float | None = None,
) -> str:
    """Run OCR while replacing provider failures with context-free public errors."""

    public_code = OCRErrorCode.PROCESSING_FAILED
    try:
        if timeout_seconds is None:
            return adapter.extract_text(image, languages=languages)
        return adapter.extract_text(
            image,
            languages=languages,
            timeout_seconds=timeout_seconds,
        )
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


class _OCRDocumentLimitExceeded(Exception):
    pass


def _remaining_document_seconds(deadline: float, *, maximum: float | None = None) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _OCRDocumentLimitExceeded
    return min(remaining, maximum) if maximum is not None else remaining


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
    max_ocr_pages: int = _DEFAULT_MAX_OCR_PAGES,
    max_total_evidence_bytes: int = _DEFAULT_MAX_TOTAL_EVIDENCE_BYTES,
    max_total_text_chars: int = _DEFAULT_MAX_TOTAL_TEXT_CHARS,
    max_total_seconds: float = _DEFAULT_MAX_TOTAL_SECONDS,
) -> OCRDocumentResult:
    """OCR selected pages under per-page and document-wide hard resource budgets."""

    if (
        not _validate_positive_int(max_pixels)
        or not _validate_positive_finite_number(timeout_seconds)
        or not _validate_positive_int(max_evidence_bytes)
        or not _validate_positive_int(max_text_chars)
        or not _validate_positive_int(max_ocr_pages)
        or not _validate_positive_int(max_total_evidence_bytes)
        or not _validate_positive_int(max_total_text_chars)
        or not _validate_positive_finite_number(max_total_seconds)
    ):
        raise ValueError("OCR limits must be positive finite values")
    normalized_languages = normalize_ocr_languages(languages)
    raw_source = bytes(source_data)
    deadline = time.monotonic() + float(max_total_seconds)

    pages: list[ParsedPage] = []
    checkpoints: list[OCRPageCheckpoint] = []
    selected_pages = 0
    total_evidence_bytes = 0
    total_text_chars = 0
    document_limit_reached = False

    for page in document.pages:
        if not page.needs_ocr:
            pages.append(page)
            continue

        selected_pages += 1
        if document_limit_reached or selected_pages > max_ocr_pages:
            document_limit_reached = True
            checkpoints.append(
                _failed_checkpoint(page.page_number, OCRErrorCode.LIMIT_EXCEEDED)
            )
            pages.append(page)
            continue

        evidence: PageEvidence | None = None
        try:
            remaining = _remaining_document_seconds(deadline, maximum=float(max_total_seconds))
            rendered = _render_selected_page(
                document,
                page,
                raw_source,
                renderer=renderer,
                max_pixels=max_pixels,
                timeout_seconds=min(float(timeout_seconds), remaining),
            )
            _remaining_document_seconds(deadline, maximum=float(max_total_seconds))
            candidate_evidence = _make_evidence(
                document,
                page,
                rendered,
                max_pixels=max_pixels,
                max_evidence_bytes=max_evidence_bytes,
            )
            candidate_size = len(candidate_evidence.image)
            if total_evidence_bytes + candidate_size > max_total_evidence_bytes:
                raise _OCRDocumentLimitExceeded
            evidence = candidate_evidence
            total_evidence_bytes += candidate_size

            remaining = _remaining_document_seconds(deadline, maximum=float(max_total_seconds))
            extracted = extract_text_safely(
                adapter,
                evidence.image,
                languages=normalized_languages,
                timeout_seconds=remaining,
            )
            _remaining_document_seconds(deadline, maximum=float(max_total_seconds))
            text = _sanitize_ocr_text(extracted, max_chars=max_text_chars)
            if total_text_chars + len(text) > max_total_text_chars:
                raise _OCRDocumentLimitExceeded
            total_text_chars += len(text)
        except _OCRDocumentLimitExceeded:
            document_limit_reached = True
            checkpoints.append(
                _failed_checkpoint(
                    page.page_number,
                    OCRErrorCode.LIMIT_EXCEEDED,
                    evidence=evidence,
                )
            )
            pages.append(page)
            continue
        except OCRError as error:
            code = _safe_public_code(error)
            if code is OCRErrorCode.TIMEOUT and time.monotonic() >= deadline:
                code = OCRErrorCode.LIMIT_EXCEEDED
                document_limit_reached = True
            checkpoints.append(
                _failed_checkpoint(
                    page.page_number,
                    code,
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
