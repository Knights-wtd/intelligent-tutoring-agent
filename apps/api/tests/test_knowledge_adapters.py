import math
from uuid import UUID

import pytest

from tutor_api.core.config import Settings
from tutor_api.knowledge.embeddings import HashEmbeddingAdapter
from tutor_api.knowledge.ocr import DisabledOCRAdapter, OCRError
from tutor_api.knowledge.storage import (
    MemoryObjectStorage,
    ObjectAlreadyExistsError,
    build_document_object_key,
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
        pytest.param("", id="empty-name"),
    ],
)
def test_document_object_key_rejects_unsafe_names(unsafe_name: str) -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        build_document_object_key(SPACE_ID, DOCUMENT_ID, VERSION_ID, unsafe_name)


def test_memory_object_storage_round_trips_bytes_and_content_type() -> None:
    storage = MemoryObjectStorage()
    key = build_document_object_key(
        SPACE_ID,
        DOCUMENT_ID,
        VERSION_ID,
        "chapter-1.pdf",
    )

    storage.put_object(key, b"%PDF-test", content_type="application/pdf")

    stored = storage.get_object(key)
    assert stored.data == b"%PDF-test"
    assert stored.content_type == "application/pdf"


def test_memory_object_storage_rejects_overwrite_by_default() -> None:
    storage = MemoryObjectStorage()
    key = build_document_object_key(
        SPACE_ID,
        DOCUMENT_ID,
        VERSION_ID,
        "chapter-1.pdf",
    )
    storage.put_object(key, b"original", content_type="application/pdf")

    with pytest.raises(ObjectAlreadyExistsError) as error:
        storage.put_object(key, b"replacement", content_type="application/pdf")

    assert key not in str(error.value)
    assert storage.get_object(key).data == b"original"


def test_disabled_ocr_exposes_only_a_stable_public_error_code() -> None:
    adapter = DisabledOCRAdapter()
    secret_provider_detail = "provider-token-and-command-line"

    with pytest.raises(OCRError) as error:
        try:
            raise RuntimeError(secret_provider_detail)
        except RuntimeError:
            adapter.extract_text(b"image", languages=("eng",))

    assert error.value.code == "ocr_disabled"
    assert str(error.value) == "ocr_disabled"
    assert error.value.__cause__ is None
    assert secret_provider_detail not in repr(error.value)


def test_hash_embedding_is_unicode_deterministic_fixed_dimension_and_normalized() -> None:
    adapter = HashEmbeddingAdapter(backend="hash", model="sha256-v1", dimension=64)

    composed = adapter.embed("caf\u00e9")
    decomposed = adapter.embed("cafe\u0301")

    assert composed == decomposed
    assert len(composed) == 64
    assert math.sqrt(sum(component * component for component in composed)) == pytest.approx(1.0)


def test_hash_embedding_signature_binds_backend_model_and_dimension() -> None:
    baseline = HashEmbeddingAdapter(backend="hash", model="sha256-v1", dimension=64)

    assert baseline.signature == "hash:sha256-v1:64"
    assert (
        HashEmbeddingAdapter(
            backend="local-hash", model="sha256-v1", dimension=64
        ).signature
        != baseline.signature
    )
    assert (
        HashEmbeddingAdapter(backend="hash", model="sha512-v1", dimension=64).signature
        != baseline.signature
    )
    assert (
        HashEmbeddingAdapter(backend="hash", model="sha256-v1", dimension=32).signature
        != baseline.signature
    )


def test_knowledge_settings_have_safe_local_defaults_and_normalize_names() -> None:
    settings = Settings(
        ocr_backend=" DISABLED ",
        ocr_languages=" ENG, chi_SIM,eng ",
        embedding_backend=" HASH ",
        embedding_model=" sha256-v1 ",
    )

    assert settings.max_upload_bytes == 50 * 1024 * 1024
    assert settings.max_vault_files == 5_000
    assert settings.max_vault_uncompressed_bytes == 500 * 1024 * 1024
    assert settings.ocr_backend == "disabled"
    assert settings.ocr_languages == ("eng", "chi_sim")
    assert settings.embedding_backend == "hash"
    assert settings.embedding_model == "sha256-v1"
    assert settings.embedding_dimension == 384


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
    ("field", "value"),
    [
        pytest.param("ocr_backend", "", id="blank-ocr-backend"),
        pytest.param("ocr_backend", "bad backend", id="invalid-ocr-backend"),
        pytest.param("ocr_languages", "eng,,chi_sim", id="empty-ocr-language"),
        pytest.param("ocr_languages", "eng,../../secret", id="invalid-ocr-language"),
        pytest.param("embedding_backend", "bad/backend", id="invalid-embedding-backend"),
        pytest.param("embedding_model", " ", id="blank-embedding-model"),
    ],
)
def test_knowledge_settings_reject_invalid_adapter_names_without_echoing_input(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match=field.upper()) as error:
        Settings(**{field: value})

    if value.strip():
        assert value not in str(error.value)
