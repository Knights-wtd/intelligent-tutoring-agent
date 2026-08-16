import asyncio
import io
import threading
import unicodedata
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers

import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.knowledge.service as knowledge_service
import tutor_api.spaces.models  # noqa: F401
from tutor_api.classrooms.models import ClassroomRole
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import (
    Document,
    DocumentVersion,
    IngestionJob,
    KnowledgeUploadRequest,
)
from tutor_api.knowledge.router import post_knowledge_document
from tutor_api.knowledge.service import (
    _normalize_idempotency_key,
    _normalize_source_name,
    _prepare_upload,
)
from tutor_api.knowledge.storage import MemoryObjectStorage
from tutor_api.main import create_app

SAFE_UPLOAD_FIELDS = {
    "document_id",
    "document_version_id",
    "ingestion_job_id",
    "space_id",
    "knowledge_base_id",
    "source_name",
    "version_number",
    "content_sha256",
    "content_type",
    "document_state",
    "version_state",
    "job_state",
    "created_at",
}


def make_client(
    *, max_bytes: int = 1024 * 1024, with_storage: bool = True
) -> tuple[TestClient, object, MemoryObjectStorage | None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    storage = MemoryObjectStorage() if with_storage else None
    settings = Settings(app_env="test", knowledge_upload_max_bytes=max_bytes)
    app = create_app(settings, sessionmaker(bind=engine), object_storage=storage)
    return TestClient(app), engine, storage


def register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "password": "Correct horse battery staple 9",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_knowledge_base(client: TestClient, space_id: str, name: str = "教材") -> dict:
    response = client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(
    client: TestClient,
    knowledge_base_id: str,
    *,
    name: str = "lesson.pdf",
    content: bytes = b"%PDF-1.7\nminimal",
    content_type: str = "application/pdf",
    key: str = "upload-key-1",
):
    return client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        headers={"Idempotency-Key": key},
        files={"file": (name, content, content_type)},
    )


class BlockingStorage(MemoryObjectStorage):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.thread_id: int | None = None

    def put_file_if_absent(self, key, data, *, content_type):
        self.thread_id = threading.get_ident()
        self.started.set()
        self.release.wait(timeout=2)
        return super().put_file_if_absent(key, data, content_type=content_type)


class RecordingSessionFactory:
    def __init__(self, factory) -> None:
        self.factory = factory
        self.created_on: list[int] = []

    def __call__(self):
        self.created_on.append(threading.get_ident())
        return self.factory()


def test_upload_database_and_storage_work_do_not_block_the_event_loop() -> None:
    client, engine, _ = make_client()
    registration = register(client, "worker")
    knowledge_base = create_knowledge_base(
        client, registration["personal_space"]["id"], "worker knowledge"
    )
    factory = sessionmaker(bind=engine)
    with factory() as session:
        current_user = session.get(User, UUID(registration["user"]["id"]))
        assert current_user is not None
        session.expunge(current_user)

    recording_factory = RecordingSessionFactory(factory)
    storage = BlockingStorage()
    client.app.state.session_factory = recording_factory
    client.app.state.object_storage = storage
    request = SimpleNamespace(app=client.app)
    uploaded_file = UploadFile(
        io.BytesIO(b"%PDF-1.7\nworker"),
        filename="worker.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )
    knowledge_base_id = UUID(knowledge_base["id"])

    async def exercise() -> None:
        event_loop_thread = threading.get_ident()
        task = asyncio.create_task(
            post_knowledge_document(
                knowledge_base_id,
                request,
                current_user,
                uploaded_file,
                "worker-key",
            )
        )
        try:
            assert await asyncio.to_thread(storage.started.wait, 2)
            assert storage.thread_id != event_loop_thread
            assert recording_factory.created_on
            assert all(
                thread_id != event_loop_thread
                for thread_id in recording_factory.created_on
            )
            assert storage.thread_id in recording_factory.created_on
            await asyncio.sleep(0.01)
            assert not task.done()
        finally:
            storage.release.set()
        response = await task
        assert response.knowledge_base_id == knowledge_base_id
        assert uploaded_file.file.closed

    try:
        asyncio.run(exercise())
    finally:
        storage.release.set()
        client.close()
        engine.dispose()


def test_prepare_upload_closes_temporary_file_when_cancelled(monkeypatch) -> None:
    temporary_file = io.BytesIO()
    monkeypatch.setattr(
        knowledge_service.tempfile,
        "SpooledTemporaryFile",
        lambda **_: temporary_file,
    )

    class CancellingUpload:
        filename = "cancelled.pdf"
        content_type = "application/pdf"

        async def read(self, _: int) -> bytes:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_prepare_upload(CancellingUpload(), 1024))

    assert temporary_file.closed


def test_upload_settings_are_centralized_and_bounded() -> None:
    assert Settings(app_env="test").knowledge_upload_max_bytes == 100 * 1024 * 1024
    assert Settings(app_env="test", knowledge_upload_max_bytes=64).knowledge_upload_max_bytes == 64


def test_upload_requires_authentication() -> None:
    client, engine, _ = make_client()
    response = upload(client, str(uuid4()))
    assert response.status_code == 401
    engine.dispose()


def test_upload_fails_closed_without_object_storage() -> None:
    client, engine, _ = make_client(with_storage=False)
    registration = register(client, "no-storage")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])

    response = upload(client, knowledge_base["id"])

    assert response.status_code == 503
    assert "storage" not in response.text.casefold()
    engine.dispose()


def test_personal_owner_uploads_pdf_to_immutable_scoped_object() -> None:
    client, engine, storage = make_client()
    registration = register(client, "pdf-owner")
    space_id = registration["personal_space"]["id"]
    knowledge_base = create_knowledge_base(client, space_id)
    content = b"%PDF-1.7\nimmutable bytes"

    response = upload(client, knowledge_base["id"], content=content)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert set(payload) == SAFE_UPLOAD_FIELDS
    assert payload["space_id"] == space_id
    assert payload["knowledge_base_id"] == knowledge_base["id"]
    assert payload["source_name"] == "lesson.pdf"
    assert payload["version_number"] == 1
    assert payload["content_sha256"] == sha256(content).hexdigest()
    assert payload["content_type"] == "application/pdf"
    assert payload["document_state"] == "active"
    assert payload["version_state"] == "uploaded"
    assert payload["job_state"] == "queued"
    assert storage is not None

    with sessionmaker(bind=engine)() as session:
        document = session.get(Document, UUID(payload["document_id"]))
        version = session.get(DocumentVersion, UUID(payload["document_version_id"]))
        job = session.get(IngestionJob, UUID(payload["ingestion_job_id"]))
        assert document is not None and version is not None and job is not None
        assert document.owner_user_id == UUID(registration["user"]["id"])
        assert document.created_by_user_id == UUID(registration["user"]["id"])
        assert document.source_kind == "upload"
        assert document.source_key == "lesson.pdf"
        assert version.object_key == (
            f"spaces/{space_id}/documents/{document.id}/versions/{version.id}/lesson.pdf"
        )
        assert storage.get_object(version.object_key).data == content
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 1
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1
    engine.dispose()


SUPPORTED_FILES = [
    ("book.pdf", b"%PDF-1.4\nbody", "application/pdf", "application/pdf"),
    (
        "book.docx",
        b"PK\x03\x04docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ("notes.md", "你好 Markdown".encode(), "text/markdown; charset=utf-8", "text/markdown"),
    ("photo.jpg", b"\xff\xd8\xffjpeg", "image/jpeg", "image/jpeg"),
    ("photo.JPEG", b"\xff\xd8jpeg", "image/jpeg", "image/jpeg"),
    ("diagram.PNG", b"\x89PNG\r\n\x1a\nbody", "image/png", "image/png"),
    ("vault.zip", b"PK\x03\x04zip", "application/zip", "application/zip"),
]


@pytest.mark.parametrize(
    ("name", "content", "content_type", "stored_content_type"), SUPPORTED_FILES
)
def test_supported_extension_mime_and_signature_pairs_upload(
    name: str, content: bytes, content_type: str, stored_content_type: str
) -> None:
    client, engine, _ = make_client()
    registration = register(client, f"format-{name.replace('.', '-').casefold()}")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])

    response = upload(
        client,
        knowledge_base["id"],
        name=name,
        content=content,
        content_type=content_type,
        key=f"key-{name}",
    )

    assert response.status_code == 201, response.text
    assert response.json()["content_type"] == stored_content_type
    engine.dispose()


@pytest.mark.parametrize(
    ("name", "content", "content_type", "expected_status"),
    [
        ("book.pdf", b"%PDF-1.4", "image/png", 415),
        ("book.exe", b"MZ", "application/octet-stream", 415),
        ("book.pdf", b"not-a-pdf", "application/pdf", 422),
        ("image.png", b"not-a-png", "image/png", 422),
        ("image.jpg", b"not-a-jpeg", "image/jpeg", 422),
        ("vault.zip", b"not-a-zip", "application/zip", 422),
        ("notes.md", b"\xff", "text/markdown", 422),
        ("notes.md", b"hello\x00world", "text/markdown", 422),
    ],
)
def test_invalid_type_or_signature_is_rejected_without_metadata(
    name: str, content: bytes, content_type: str, expected_status: int
) -> None:
    client, engine, storage = make_client()
    registration = register(client, f"invalid-{expected_status}-{uuid4().hex[:8]}")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])

    response = upload(
        client,
        knowledge_base["id"],
        name=name,
        content=content,
        content_type=content_type,
    )

    assert response.status_code == expected_status
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 0
    assert storage is not None and len(storage._objects) == 0
    engine.dispose()


@pytest.mark.parametrize(
    "name",
    [
        "../secret.pdf",
        "folder/book.pdf",
        "folder\\book.pdf",
        "/root.pdf",
        "book..pdf",
        "bad\u200b.pdf",
        "x" * 252 + ".pdf",
        "   ",
    ],
)
def test_unsafe_filenames_are_rejected(name: str) -> None:
    client, engine, _ = make_client()
    registration = register(client, f"filename-{uuid4().hex[:8]}")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    response = upload(client, knowledge_base["id"], name=name)
    assert response.status_code == 422
    engine.dispose()


@pytest.mark.parametrize("name", ["C:\\book.pdf", "bad\x00.pdf"])
def test_raw_unsafe_filename_values_are_rejected_before_storage(name: str) -> None:
    with pytest.raises(HTTPException) as error:
        _normalize_source_name(name)
    assert getattr(error.value, "status_code", None) == 422


@pytest.mark.parametrize(
    "name",
    ["\tbook.pdf", "book.pdf\n", "\x1cbook.pdf", "\u200bbook.pdf", "book.pdf\u200b"],
)
def test_source_name_rejects_raw_control_and_format_characters(name: str) -> None:
    with pytest.raises(HTTPException) as error:
        _normalize_source_name(name)
    assert error.value.status_code == 422


def test_raw_multipart_filename_control_is_rejected_without_side_effects() -> None:
    client, engine, storage = make_client()
    registration = register(client, "raw-control-filename")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    boundary = "raw-control-boundary"
    body = (
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"file\"; "
        "filename=\"\tlesson.pdf\"\r\n"
        "Content-Type: application/pdf\r\n"
        "\r\n"
    ).encode() + b"%PDF-1.7\nminimal" + f"\r\n--{boundary}--\r\n".encode()

    response = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/documents",
        headers={
            "Idempotency-Key": "raw-control-filename",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        content=body,
    )

    assert response.status_code == 422
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 0
        assert session.scalar(select(func.count()).select_from(KnowledgeUploadRequest)) == 0
    assert storage is not None and len(storage._objects) == 0
    engine.dispose()


def test_filename_is_nfc_normalized_before_identity_and_storage() -> None:
    client, engine, _ = make_client()
    registration = register(client, "unicode-name")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    decomposed = "Cafe\u0301.md"

    response = upload(
        client,
        knowledge_base["id"],
        name=decomposed,
        content=b"markdown",
        content_type="text/markdown",
    )

    assert response.status_code == 201, response.text
    assert response.json()["source_name"] == unicodedata.normalize("NFC", decomposed)
    engine.dispose()


@pytest.mark.parametrize(
    ("content", "expected_status"),
    [(b"", 422), (b"%PDF-123456789", 413)],
)
def test_empty_and_oversized_uploads_are_rejected(
    content: bytes, expected_status: int
) -> None:
    client, engine, storage = make_client(max_bytes=8)
    registration = register(client, f"size-{expected_status}")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])

    response = upload(client, knowledge_base["id"], content=content)

    assert response.status_code == expected_status
    assert storage is not None and len(storage._objects) == 0
    engine.dispose()


def add_classroom_member(
    owner: TestClient, classroom: dict, username: str, role: ClassroomRole
) -> TestClient:
    member = TestClient(owner.app)
    registration = register(member, username)
    invite = owner.post(
        f"/api/v1/classrooms/{classroom['id']}/invites",
        json={"expires_in_hours": 24, "max_uses": 1},
    )
    assert invite.status_code == 201
    joined = member.post("/api/v1/classrooms/join", json={"code": invite.json()["code"]})
    assert joined.status_code == 200
    if role == ClassroomRole.TEACHER:
        promoted = owner.patch(
            f"/api/v1/classrooms/{classroom['id']}/members/{registration['user']['id']}",
            json={"role": "teacher"},
        )
        assert promoted.status_code == 200
    return member


def test_classroom_upload_permissions_and_hidden_nonmembership() -> None:
    owner, engine, _ = make_client()
    register(owner, "upload-classroom-owner")
    classroom_response = owner.post("/api/v1/classrooms", json={"name": "上传课堂"})
    assert classroom_response.status_code == 201
    classroom = classroom_response.json()
    knowledge_base = create_knowledge_base(owner, classroom["space"]["id"])
    teacher = add_classroom_member(
        owner, classroom, "upload-teacher", ClassroomRole.TEACHER
    )
    student = add_classroom_member(
        owner, classroom, "upload-student", ClassroomRole.STUDENT
    )
    outsider = TestClient(owner.app)
    register(outsider, "upload-outsider")

    assert upload(owner, knowledge_base["id"], key="owner-key").status_code == 201
    assert upload(
        teacher,
        knowledge_base["id"],
        name="teacher.pdf",
        key="teacher-key",
    ).status_code == 201
    assert upload(student, knowledge_base["id"], key="student-key").status_code == 403
    assert upload(outsider, knowledge_base["id"], key="outsider-key").status_code == 404
    assert upload(outsider, str(uuid4()), key="unknown-key").status_code == 404
    engine.dispose()


def test_personal_nonowner_and_known_uuid_cannot_upload() -> None:
    owner, engine, _ = make_client()
    registration = register(owner, "personal-upload-owner")
    knowledge_base = create_knowledge_base(owner, registration["personal_space"]["id"])
    outsider = TestClient(owner.app)
    register(outsider, "personal-upload-outsider")

    response = upload(outsider, knowledge_base["id"])

    assert response.status_code == 404
    engine.dispose()


def test_versions_sha_dedupe_and_distinct_source_history() -> None:
    client, engine, storage = make_client()
    registration = register(client, "version-owner")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    first = upload(client, knowledge_base["id"], content=b"%PDF-first", key="v1").json()
    second_response = upload(
        client, knowledge_base["id"], content=b"%PDF-second", key="v2"
    )
    dedupe_response = upload(
        client, knowledge_base["id"], content=b"%PDF-first", key="v1-alias"
    )
    other_response = upload(
        client,
        knowledge_base["id"],
        name="other.pdf",
        content=b"%PDF-first",
        key="other-source",
    )

    assert second_response.status_code == dedupe_response.status_code == 201
    second = second_response.json()
    dedupe = dedupe_response.json()
    other = other_response.json()
    assert second["document_id"] == first["document_id"]
    assert second["version_number"] == 2
    assert dedupe["document_version_id"] == first["document_version_id"]
    assert dedupe["ingestion_job_id"] == first["ingestion_job_id"]
    assert other["document_id"] != first["document_id"]
    assert other["content_sha256"] == first["content_sha256"]
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 2
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 3
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 3
        assert session.scalar(select(func.count()).select_from(KnowledgeUploadRequest)) == 4
    assert storage is not None and len(storage._objects) == 3
    engine.dispose()


def test_idempotency_exact_replay_and_payload_conflict_are_stable() -> None:
    client, engine, storage = make_client()
    registration = register(client, "idempotency-owner")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    first_response = upload(client, knowledge_base["id"], key=" stable-key ")
    replay_response = upload(client, knowledge_base["id"], key="stable-key")
    name_conflict = upload(
        client, knowledge_base["id"], name="other.pdf", key="stable-key"
    )
    body_conflict = upload(
        client, knowledge_base["id"], content=b"%PDF-changed", key="stable-key"
    )

    assert first_response.status_code == replay_response.status_code == 201
    assert replay_response.json() == first_response.json()
    assert name_conflict.status_code == body_conflict.status_code == 409
    assert "stable-key" not in name_conflict.text
    follow_up = upload(
        client, knowledge_base["id"], name="after.pdf", key="after-conflict"
    )
    assert follow_up.status_code == 201
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 2
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 2
    assert storage is not None and len(storage._objects) == 2
    engine.dispose()


@pytest.mark.parametrize(
    "key",
    ["\tstable-key", "stable-key\n", "\x1cstable-key", "\u200bstable-key", "stable-key\u200b"],
)
def test_idempotency_key_rejects_raw_control_and_format_characters(key: str) -> None:
    with pytest.raises(HTTPException) as error:
        _normalize_idempotency_key(key)
    assert error.value.status_code == 422


def test_control_prefixed_idempotency_key_does_not_replay_trimmed_key() -> None:
    client, engine, storage = make_client()
    registration = register(client, "control-idempotency")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    first = upload(client, knowledge_base["id"], key="control-key")

    rejected = upload(client, knowledge_base["id"], key="\tcontrol-key")

    assert first.status_code == 201
    assert rejected.status_code == 422
    assert first.json()["document_id"] not in rejected.text
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 1
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1
        assert session.scalar(select(func.count()).select_from(KnowledgeUploadRequest)) == 1
    assert storage is not None and len(storage._objects) == 1
    engine.dispose()


@pytest.mark.parametrize("key", ["", "   ", "bad key", "bad\x00key", "x" * 256])
def test_unsafe_idempotency_keys_are_rejected_without_echo(key: str) -> None:
    client, engine, _ = make_client()
    registration = register(client, f"unsafe-key-{uuid4().hex[:8]}")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    response = upload(client, knowledge_base["id"], key=key)
    assert response.status_code == 422
    if key.strip():
        assert key.strip() not in response.text
    engine.dispose()


def test_missing_idempotency_key_is_rejected() -> None:
    client, engine, _ = make_client()
    registration = register(client, "missing-key")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    response = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/documents",
        files={"file": ("lesson.pdf", b"%PDF-data", "application/pdf")},
    )
    assert response.status_code == 422
    engine.dispose()


class LeakingHttpStorage(MemoryObjectStorage):
    def put_file_if_absent(self, key, data, *, content_type):
        raise HTTPException(
            status_code=418, detail="provider secret /internal/bucket"
        )


def test_storage_http_exception_is_redacted_and_rolls_back_metadata() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    app = create_app(
        Settings(app_env="test", knowledge_upload_max_bytes=1024),
        sessionmaker(bind=engine),
        object_storage=LeakingHttpStorage(),
    )
    client = TestClient(app)
    registration = register(client, "storage-http-failure")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])

    response = upload(client, knowledge_base["id"])

    assert response.status_code == 503
    assert response.json() == {"detail": "上传服务暂不可用"}
    assert "provider secret" not in response.text
    assert "/internal/bucket" not in response.text
    assert "HTTPException" not in response.text
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 0
        assert session.scalar(select(func.count()).select_from(KnowledgeUploadRequest)) == 0
        assert session.scalar(select(1)) == 1
    engine.dispose()


class FailingStorage(MemoryObjectStorage):
    def put_file_if_absent(self, key, data, *, content_type):
        raise RuntimeError("provider secret C:/internal/object/path")


def test_storage_failure_is_redacted_and_rolls_back_metadata() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    app = create_app(
        Settings(app_env="test", knowledge_upload_max_bytes=1024),
        sessionmaker(bind=engine),
        object_storage=FailingStorage(),
    )
    client = TestClient(app)
    registration = register(client, "storage-failure")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])

    response = upload(client, knowledge_base["id"])

    assert response.status_code == 503
    assert "provider secret" not in response.text
    assert "internal" not in response.text
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 0
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 0
    engine.dispose()


def test_uploads_are_isolated_by_space_and_knowledge_base() -> None:
    first, engine, storage = make_client()
    first_registration = register(first, "tenant-one")
    first_kb = create_knowledge_base(first, first_registration["personal_space"]["id"])
    second = TestClient(first.app)
    second_registration = register(second, "tenant-two")
    second_kb = create_knowledge_base(second, second_registration["personal_space"]["id"])

    first_upload = upload(first, first_kb["id"], key="same-client-key").json()
    second_upload = upload(second, second_kb["id"], key="same-client-key").json()

    assert first_upload["document_id"] != second_upload["document_id"]
    assert first_upload["document_version_id"] != second_upload["document_version_id"]
    assert first_upload["space_id"] != second_upload["space_id"]
    assert storage is not None
    with sessionmaker(bind=engine)() as session:
        first_version = session.get(DocumentVersion, UUID(first_upload["document_version_id"]))
        second_version = session.get(DocumentVersion, UUID(second_upload["document_version_id"]))
        assert first_version is not None and second_version is not None
        assert first_version.object_key != second_version.object_key
        assert first_version.object_key.startswith(f"spaces/{first_upload['space_id']}/")
        assert second_version.object_key.startswith(f"spaces/{second_upload['space_id']}/")
    engine.dispose()
