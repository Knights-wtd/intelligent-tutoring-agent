from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_knowledge_retrieval import (
    FixedEmbeddingAdapter,
    create_knowledge_base,
    make_client,
    register,
)

from tutor_api.knowledge.models import IngestionJobKind, Page
from tutor_api.knowledge.storage import MemoryObjectStorage
from tutor_api.knowledge.worker import (
    WorkerConfig,
    make_build_index_handler,
    make_parse_document_handler,
    run_worker_once,
)


class TrackingStorage(MemoryObjectStorage):
    def __init__(self) -> None:
        super().__init__()
        self.read_calls = 0

    def get_object_range(self, key: str, *, start: int, length: int):
        self.read_calls += 1
        return super().get_object_range(key, start=start, length=length)


class FailingStorage(TrackingStorage):
    def get_object_range(self, key: str, *, start: int, length: int):
        self.read_calls += 1
        raise RuntimeError(f"provider credentials leaked for {key}")


def _ingest_preview_target(
    client: TestClient,
    engine: object,
    storage: MemoryObjectStorage,
    *,
    username: str,
) -> tuple[dict, dict, str, bytes, bytes]:
    registration = register(client, username)
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    source_bytes = b"# Quadratic\n\nquadratic source preview\n"
    upload = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/documents",
        files={"file": ("chapter-1.md", source_bytes, "text/markdown")},
        headers={"Idempotency-Key": f"preview-{username}"},
    )
    assert upload.status_code == 201, upload.text

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    adapter = client.app.state.embedding_adapter
    config = WorkerConfig(worker_id=f"preview-{username}")
    assert run_worker_once(
        factory,
        {
            IngestionJobKind.PARSE_DOCUMENT: make_parse_document_handler(
                storage, adapter
            )
        },
        config=config,
    )
    assert run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: make_build_index_handler(adapter)},
        config=config,
    )

    with factory() as session:
        page = session.scalar(
            select(Page).where(
                Page.document_version_id == UUID(upload.json()["document_version_id"])
            )
        )
        assert page is not None
        assert page.text_object_key is not None
        page_preview = storage.get_object(page.text_object_key).data

    search = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
        json={"query": "quadratic"},
    )
    assert search.status_code == 200, search.text
    return (
        registration,
        knowledge_base,
        search.json()["results"][0]["citation"]["id"],
        source_bytes,
        page_preview,
    )


def test_normal_ingestion_persists_cited_page_preview_and_serves_bounded_ranges() -> None:
    storage = TrackingStorage()
    client, engine = make_client(FixedEmbeddingAdapter(), storage)
    try:
        _, knowledge_base, citation_id, source_bytes, page_preview = _ingest_preview_target(
            client, engine, storage, username="preview-owner"
        )

        source = client.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/citations/{citation_id}/source",
            headers={"Range": "bytes=2-5"},
        )
        page = client.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/citations/{citation_id}/page",
            headers={"Range": "bytes=0-3"},
        )

        assert source.status_code == page.status_code == 206
        assert source.content == source_bytes[2:6]
        assert source.headers["content-range"] == f"bytes 2-5/{len(source_bytes)}"
        assert source.headers["accept-ranges"] == "bytes"
        assert source.headers["x-content-type-options"] == "nosniff"
        assert page.content == page_preview[:4]
        assert page.headers["content-range"] == f"bytes 0-3/{len(page_preview)}"
        serialized = source.text + str(source.headers) + page.text + str(page.headers)
        assert "spaces/" not in serialized
        assert "credentials" not in serialized
        assert storage.read_calls == 2
    finally:
        client.close()
        engine.dispose()


def test_preview_authorizes_before_any_object_read_and_hides_other_tenant() -> None:
    storage = TrackingStorage()
    owner, engine = make_client(FixedEmbeddingAdapter(), storage)
    outsider = TestClient(owner.app)
    try:
        _, knowledge_base, citation_id, _, _ = _ingest_preview_target(
            owner, engine, storage, username="source-owner"
        )
        register(outsider, "source-outsider")

        response = outsider.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/citations/{citation_id}/source",
            headers={"Range": "bytes=0-3"},
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "资源不存在"}
        assert storage.read_calls == 0
    finally:
        outsider.close()
        owner.close()
        engine.dispose()


def test_preview_rejects_malicious_and_out_of_range_headers_without_leaking_errors() -> None:
    storage = TrackingStorage()
    client, engine = make_client(FixedEmbeddingAdapter(), storage)
    try:
        _, knowledge_base, citation_id, _, _ = _ingest_preview_target(
            client, engine, storage, username="range-owner"
        )
        endpoint = (
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/citations/{citation_id}/source"
        )

        malformed = client.get(endpoint, headers={"Range": "bytes=-5"})
        backwards = client.get(endpoint, headers={"Range": "bytes=5-1"})
        out_of_range = client.get(endpoint, headers={"Range": "bytes=999999-"})

        assert malformed.status_code == backwards.status_code == out_of_range.status_code == 416
        assert malformed.json() == {"detail": "请求范围无效"}
        assert backwards.json() == {"detail": "请求范围无效"}
        assert out_of_range.json() == {"detail": "请求范围无效"}
        assert storage.read_calls == 1
    finally:
        client.close()
        engine.dispose()


def test_preview_redacts_storage_exception_and_accepts_only_opaque_citation() -> None:
    storage = FailingStorage()
    client, engine = make_client(FixedEmbeddingAdapter(), storage)
    try:
        _, knowledge_base, citation_id, _, _ = _ingest_preview_target(
            client, engine, storage, username="redacted-owner"
        )
        endpoint = f"/api/v1/knowledge-bases/{knowledge_base['id']}/citations/{citation_id}/source"

        failure = client.get(endpoint, headers={"Range": "bytes=0-3"})
        forged = client.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/citations/cite_not-a-real-token/source"
        )

        assert failure.status_code == 503
        assert failure.json() == {"detail": "检索服务暂不可用"}
        assert "credentials" not in failure.text
        assert "spaces/" not in failure.text
        assert forged.status_code == 404
        assert storage.read_calls == 1
    finally:
        client.close()
        engine.dispose()
