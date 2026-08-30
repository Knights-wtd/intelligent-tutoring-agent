import math
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.error import HTTPError
from uuid import UUID

import pytest

from tutor_api.core.config import Settings
from tutor_api.knowledge.embeddings import HashEmbeddingAdapter
from tutor_api.knowledge.ocr import (
    DisabledOCRAdapter,
    OCRError,
    OCRErrorCode,
    extract_text_safely,
)
from tutor_api.knowledge.storage import (
    MemoryObjectStorage,
    ObjectAlreadyExistsError,
    ObjectSizeLimitError,
    S3ObjectStorage,
    build_document_object_key,
    create_object_storage,
)

SPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
DOCUMENT_ID = UUID("22222222-2222-2222-2222-222222222222")
VERSION_ID = UUID("33333333-3333-3333-3333-333333333333")


def test_document_object_key_uses_fixed_scope_and_normalizes_unicode() -> None:
    key = build_document_object_key(
        SPACE_ID,
        DOCUMENT_ID,
        VERSION_ID,
        "notes/cafe\u0301.md",
    )

    assert key == (
        "spaces/11111111-1111-1111-1111-111111111111/"
        "documents/22222222-2222-2222-2222-222222222222/"
        "versions/33333333-3333-3333-3333-333333333333/notes/caf\u00e9.md"
    )


@pytest.mark.parametrize(
    "unsafe_name",
    [
        pytest.param("/absolute.pdf", id="posix-absolute"),
        pytest.param("../secret.pdf", id="leading-traversal"),
        pytest.param("notes/../secret.pdf", id="nested-traversal"),
        pytest.param("notes\\secret.pdf", id="backslash"),
        pytest.param("notes/secret\x00.pdf", id="nul"),
        pytest.param("notes//secret.pdf", id="empty-segment"),
        pytest.param("C:/secret.pdf", id="windows-drive"),
        pytest.param("notes/line\rbreak.md", id="carriage-return"),
        pytest.param("notes/line\nbreak.md", id="line-feed"),
        pytest.param("notes/tab\tname.md", id="tab"),
        pytest.param("notes/control\x1fname.md", id="c0-control"),
        pytest.param("notes/delete\x7fname.md", id="delete-control"),
        pytest.param("notes/zero\u200bwidth.md", id="unicode-format"),
        pytest.param("", id="empty-name"),
    ],
)
def test_document_object_key_rejects_unsafe_names(unsafe_name: str) -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        build_document_object_key(SPACE_ID, DOCUMENT_ID, VERSION_ID, unsafe_name)


def test_settings_construct_real_shared_s3_object_storage() -> None:
    settings = Settings(
        app_env="development",
        object_storage_endpoint="http://minio:9000",
        object_storage_access_key="app-access",
        object_storage_secret_key="app-secret-value",
        object_storage_bucket="knowledge-assets",
    )

    storage = create_object_storage(settings)

    assert isinstance(storage, S3ObjectStorage)
    assert storage.endpoint == "http://minio:9000"
    assert storage.bucket == "knowledge-assets"
    assert storage.max_object_bytes == settings.knowledge_upload_max_bytes


def test_s3_signed_request_does_not_follow_redirect_or_leak_sensitive_headers() -> None:
    received_headers: list[dict[str, str]] = []

    class RedirectTarget(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            received_headers.append(dict(self.headers.items()))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    target = ThreadingHTTPServer(("127.0.0.1", 0), RedirectTarget)

    class RedirectSource(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(307)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{target.server_port}/stolen",
            )
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectSource)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
    target_thread.start()
    source_thread.start()
    try:
        storage = S3ObjectStorage(
            endpoint=f"http://127.0.0.1:{source.server_port}",
            access_key="access",
            secret_key="secret",
            bucket="bucket",
            max_object_bytes=1024,
        )

        with pytest.raises(RuntimeError, match="object_storage_request_failed"):
            storage.get_object("document.pdf")

        assert received_headers == []
    finally:
        source.shutdown()
        target.shutdown()
        source.server_close()
        target.server_close()
        source_thread.join(timeout=2)
        target_thread.join(timeout=2)


def test_s3_http_error_is_closed_before_stable_failure() -> None:
    body = BytesIO(b"provider details")
    error = HTTPError(
        "http://storage.invalid/bucket/key",
        500,
        "secret provider error",
        {},
        body,
    )

    class FailingOpener:
        def open(self, request: object, timeout: float) -> object:
            del request, timeout
            raise error

    storage = S3ObjectStorage(
        endpoint="http://storage.invalid",
        access_key="access",
        secret_key="secret",
        bucket="bucket",
        max_object_bytes=1024,
    )
    storage._opener = FailingOpener()

    with pytest.raises(RuntimeError, match="object_storage_request_failed"):
        storage.get_object("document.pdf")

    assert body.closed


class _FakeStorageResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str]) -> None:
        self._chunks = iter(chunks)
        self.headers = headers
        self.closed = False
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return next(self._chunks, b"")

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_FakeStorageResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self.close()


class _FakeStorageOpener:
    def __init__(self, response: _FakeStorageResponse) -> None:
        self.response = response
        self.calls = 0

    def open(self, request: object, timeout: float) -> _FakeStorageResponse:
        del request, timeout
        self.calls += 1
        return self.response


def test_s3_get_rejects_oversized_content_length_without_reading_and_closes() -> None:
    response = _FakeStorageResponse([], {"Content-Length": "5"})
    storage = S3ObjectStorage(
        endpoint="http://storage.invalid",
        access_key="access",
        secret_key="secret",
        bucket="bucket",
        max_object_bytes=4,
    )
    storage._opener = _FakeStorageOpener(response)

    with pytest.raises(ObjectSizeLimitError, match="object_size_limit_exceeded"):
        storage.get_object("document.pdf")

    assert response.read_sizes == []
    assert response.closed


def test_s3_get_bounds_chunked_or_unknown_length_response_and_closes() -> None:
    response = _FakeStorageResponse(
        [b"abc", b"de", b"ignored"],
        {"Content-Type": "application/pdf"},
    )
    storage = S3ObjectStorage(
        endpoint="http://storage.invalid",
        access_key="access",
        secret_key="secret",
        bucket="bucket",
        max_object_bytes=4,
    )
    storage._opener = _FakeStorageOpener(response)

    with pytest.raises(ObjectSizeLimitError, match="object_size_limit_exceeded"):
        storage.get_object("document.pdf")

    assert all(0 < size <= 5 for size in response.read_sizes)
    assert response.closed


def test_s3_put_file_is_bounded_before_network_request() -> None:
    response = _FakeStorageResponse([], {})
    opener = _FakeStorageOpener(response)
    storage = S3ObjectStorage(
        endpoint="http://storage.invalid",
        access_key="access",
        secret_key="secret",
        bucket="bucket",
        max_object_bytes=4,
    )
    storage._opener = opener

    with pytest.raises(ObjectSizeLimitError, match="object_size_limit_exceeded"):
        storage.put_file_if_absent(
            "document.pdf",
            BytesIO(b"12345"),
            content_type="application/pdf",
        )

    assert opener.calls == 0


def test_memory_object_storage_round_trips_bytes_and_normalized_content_type() -> None:
    storage = MemoryObjectStorage()
    key = build_document_object_key(
        SPACE_ID,
        DOCUMENT_ID,
        VERSION_ID,
        "chapter-1.pdf",
    )

    storage.put_if_absent(
        key,
        b"%PDF-test",
        content_type=" Application/PDF ; Charset=UTF-8 ",
    )

    stored = storage.get_object(key)
    assert stored.data == b"%PDF-test"
    assert stored.content_type == "application/pdf; charset=UTF-8"


@pytest.mark.parametrize(
    "content_type",
    [
        pytest.param("", id="empty"),
        pytest.param("application", id="missing-subtype"),
        pytest.param("application/", id="empty-subtype"),
        pytest.param("/pdf", id="empty-type"),
        pytest.param("application/p df", id="invalid-token"),
        pytest.param("application/pdf\x00", id="nul"),
        pytest.param("application/pdf\t", id="tab"),
        pytest.param("application/pdf\r\nX-Test: injected", id="header-injection"),
        pytest.param("application/pdf;", id="empty-parameter"),
        pytest.param("application/pdf; charset", id="parameter-without-value"),
        pytest.param("application/pdf; charset=", id="empty-parameter-value"),
        pytest.param("application/pdf; bad name=utf-8", id="invalid-parameter-name"),
    ],
)
def test_memory_object_storage_rejects_unsafe_content_type(content_type: str) -> None:
    storage = MemoryObjectStorage()

    with pytest.raises(ValueError, match="content_type"):
        storage.put_if_absent("safe-key", b"data", content_type=content_type)


def test_memory_object_storage_exposes_only_immutable_create() -> None:
    storage = MemoryObjectStorage()

    assert not hasattr(storage, "put_object")


def test_memory_object_storage_allows_exactly_one_concurrent_writer() -> None:
    storage = MemoryObjectStorage()
    barrier = threading.Barrier(2)

    def write(payload: bytes) -> bool:
        barrier.wait()
        try:
            storage.put_if_absent("shared-key", payload, content_type="application/pdf")
        except ObjectAlreadyExistsError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, (b"first", b"second")))

    assert sorted(results) == [False, True]
    assert storage.get_object("shared-key").data in {b"first", b"second"}


def test_disabled_ocr_uses_a_restricted_public_error_code() -> None:
    adapter = DisabledOCRAdapter()

    with pytest.raises(OCRError) as error:
        adapter.extract_text(b"image", languages=("eng",))

    assert error.value.code is OCRErrorCode.DISABLED
    assert str(error.value) == OCRErrorCode.DISABLED.value
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def _assert_ocr_error_is_sanitized(
    provider_error: OCRError,
    *,
    expected_code: OCRErrorCode,
    secret: str,
) -> None:
    class FailingOCRAdapter:
        backend = "test-provider"

        def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str:
            del image, languages
            provider_stack_marker(provider_error)

    with pytest.raises(OCRError) as error:
        extract_text_safely(FailingOCRAdapter(), b"image", languages=("eng",))

    rendered = "".join(traceback.format_exception(error.value))
    assert type(error.value) is OCRError
    assert error.value.code is expected_code
    assert str(error.value) == expected_code.value
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert secret not in repr(error.value)
    assert secret not in rendered
    assert "provider_stack_marker" not in repr(error.value)
    assert "provider_stack_marker" not in rendered


def provider_stack_marker(error: OCRError) -> None:
    raise error


def test_ocr_boundary_preserves_valid_code_without_provider_details() -> None:
    secret = "secret-valid-provider-message"
    provider_error = OCRError(OCRErrorCode.DISABLED)
    provider_error.args = (secret,)
    provider_error.__cause__ = RuntimeError(secret)
    provider_error.__context__ = RuntimeError(secret)

    _assert_ocr_error_is_sanitized(
        provider_error,
        expected_code=OCRErrorCode.DISABLED,
        secret=secret,
    )


def test_ocr_boundary_rejects_invalid_code_from_malformed_subclass() -> None:
    secret = "secret-invalid-subclass-message"

    class InvalidCodeOCRError(OCRError):
        def __init__(self) -> None:
            RuntimeError.__init__(self, secret)
            self.code = "forged-code"

    _assert_ocr_error_is_sanitized(
        InvalidCodeOCRError(),
        expected_code=OCRErrorCode.PROCESSING_FAILED,
        secret=secret,
    )


def test_ocr_boundary_rejects_code_mutated_after_construction() -> None:
    secret = "secret-mutated-code-message"
    provider_error = OCRError(OCRErrorCode.DISABLED)
    provider_error.args = (secret,)
    provider_error.code = "forged-code"

    _assert_ocr_error_is_sanitized(
        provider_error,
        expected_code=OCRErrorCode.PROCESSING_FAILED,
        secret=secret,
    )


def test_ocr_boundary_handles_missing_code() -> None:
    secret = "secret-missing-code-message"

    class MissingCodeOCRError(OCRError):
        def __init__(self) -> None:
            RuntimeError.__init__(self, secret)

    _assert_ocr_error_is_sanitized(
        MissingCodeOCRError(),
        expected_code=OCRErrorCode.PROCESSING_FAILED,
        secret=secret,
    )


def test_ocr_boundary_handles_code_property_that_raises() -> None:
    secret = "secret-code-property-message"

    class ExplodingCodeOCRError(OCRError):
        @property
        def code(self) -> OCRErrorCode:
            raise RuntimeError(secret)

        def __init__(self) -> None:
            RuntimeError.__init__(self, secret)

    _assert_ocr_error_is_sanitized(
        ExplodingCodeOCRError(),
        expected_code=OCRErrorCode.PROCESSING_FAILED,
        secret=secret,
    )


def test_ocr_boundary_redacts_provider_errors_without_retaining_context() -> None:
    secret_provider_detail = "provider-token-and-command-line"

    class FailingOCRAdapter:
        backend = "test-provider"

        def extract_text(self, image: bytes, *, languages: tuple[str, ...]) -> str:
            del image, languages
            raise RuntimeError(secret_provider_detail)

    with pytest.raises(OCRError) as error:
        extract_text_safely(
            FailingOCRAdapter(),
            b"image",
            languages=("eng",),
        )

    rendered = "".join(traceback.format_exception(error.value))
    assert error.value.code is OCRErrorCode.PROCESSING_FAILED
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert secret_provider_detail not in repr(error.value)
    assert secret_provider_detail not in rendered


def test_hash_embedding_is_unicode_deterministic_fixed_dimension_and_normalized() -> None:
    adapter = HashEmbeddingAdapter(dimension=64)

    composed = adapter.embed("caf\u00e9 explains force and acceleration")
    decomposed = adapter.embed("cafe\u0301 explains force and acceleration")

    assert composed == decomposed
    assert len(composed) == 64
    assert math.sqrt(sum(component * component for component in composed)) == pytest.approx(1.0)


def test_feature_hash_embedding_preserves_near_text_similarity() -> None:
    adapter = HashEmbeddingAdapter(dimension=384)
    source = adapter.embed("牛顿第二定律说明物体加速度与合外力成正比，与质量成反比")
    near = adapter.embed("牛顿第二定律：物体的加速度和合外力成正比，和质量成反比")
    unrelated = adapter.embed("光合作用利用叶绿素把光能转化为化学能并释放氧气")

    near_similarity = sum(left * right for left, right in zip(source, near, strict=True))
    unrelated_similarity = sum(
        left * right for left, right in zip(source, unrelated, strict=True)
    )

    assert near_similarity > unrelated_similarity
    assert near_similarity > 0.5


@pytest.mark.parametrize("text", ["", " ", "\t\r\n"])
def test_hash_embedding_rejects_blank_text(text: str) -> None:
    with pytest.raises(ValueError, match="text must not be blank"):
        HashEmbeddingAdapter().embed(text)


def test_hash_embedding_signature_describes_the_real_algorithm() -> None:
    adapter = HashEmbeddingAdapter(dimension=64)

    assert adapter.signature == "hash:feature-hash-v1:64"


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"backend": "openai"}, id="unknown-backend"),
        pytest.param({"model": "sha256-v1"}, id="unknown-model"),
        pytest.param({"dimension": 7}, id="dimension-too-small"),
        pytest.param({"dimension": 4_097}, id="dimension-too-large"),
    ],
)
def test_hash_embedding_adapter_rejects_unsupported_configuration(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        HashEmbeddingAdapter(**kwargs)


def test_runtime_adapters_are_immutable() -> None:
    embedding = HashEmbeddingAdapter()
    ocr = DisabledOCRAdapter()

    with pytest.raises(FrozenInstanceError):
        embedding.dimension = 128
    with pytest.raises(FrozenInstanceError):
        ocr.backend = "tesseract"


def test_knowledge_settings_have_fail_closed_local_defaults_and_normalize_names() -> None:
    settings = Settings(
        ocr_backend=" DISABLED ",
        ocr_languages=" ENG, chi_SIM,eng ",
        embedding_backend=" HASH ",
        embedding_model=" FEATURE-HASH-V1 ",
    )

    assert settings.max_upload_bytes == 50 * 1024 * 1024
    assert settings.max_vault_files == 5_000
    assert settings.max_vault_uncompressed_bytes == 500 * 1024 * 1024
    assert settings.ocr_backend == "disabled"
    assert settings.ocr_languages == ("eng", "chi_sim")
    assert settings.embedding_backend == "hash"
    assert settings.embedding_model == "feature-hash-v1"
    assert settings.embedding_dimension == 384


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("ocr_backend", "tesseract", id="unknown-ocr-backend"),
        pytest.param("embedding_backend", "openai", id="unknown-embedding-backend"),
        pytest.param("embedding_model", "sha256-v1", id="obsolete-embedding-model"),
        pytest.param("embedding_model", "feature-hash-v2", id="unknown-embedding-model"),
    ],
)
def test_knowledge_settings_fail_closed_for_unknown_runtime_configuration(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match=field.upper()) as error:
        Settings(**{field: value})

    assert value not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("max_upload_bytes", 0, id="upload-too-small"),
        pytest.param("max_upload_bytes", 2 * 1024 * 1024 * 1024 + 1, id="upload-too-large"),
        pytest.param("max_vault_files", 0, id="vault-files-too-small"),
        pytest.param("max_vault_files", 100_001, id="vault-files-too-large"),
        pytest.param("max_vault_uncompressed_bytes", 0, id="vault-bytes-too-small"),
        pytest.param(
            "max_vault_uncompressed_bytes",
            20 * 1024 * 1024 * 1024 + 1,
            id="vault-bytes-too-large",
        ),
        pytest.param("embedding_dimension", 7, id="embedding-dimension-too-small"),
        pytest.param("embedding_dimension", 4_097, id="embedding-dimension-too-large"),
    ],
)
def test_knowledge_settings_enforce_numeric_bounds(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field.upper()):
        Settings(**{field: value})


@pytest.mark.parametrize(
    "ocr_languages",
    [
        pytest.param("eng,,chi_sim", id="empty-language"),
        pytest.param("eng,../../secret", id="invalid-language"),
    ],
)
def test_knowledge_settings_reject_invalid_ocr_languages_without_echoing_input(
    ocr_languages: str,
) -> None:
    with pytest.raises(ValueError, match="OCR_LANGUAGES") as error:
        Settings(ocr_languages=ocr_languages)

    assert ocr_languages not in str(error.value)


def test_memory_object_storage_accepts_stream_without_overwrite() -> None:
    storage = MemoryObjectStorage()
    storage.put_file_if_absent(
        "spaces/streamed/document.bin",
        BytesIO(b"streamed-bytes"),
        content_type="application/octet-stream",
    )

    assert storage.get_object("spaces/streamed/document.bin").data == b"streamed-bytes"
    with pytest.raises(ObjectAlreadyExistsError):
        storage.put_file_if_absent(
            "spaces/streamed/document.bin",
            BytesIO(b"replacement"),
            content_type="application/octet-stream",
        )
