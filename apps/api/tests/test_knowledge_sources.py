from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_knowledge_retrieval import (
    FixedEmbeddingAdapter,
    create_knowledge_base,
    make_client,
    register,
    seed_chunk,
)

from tutor_api.knowledge.models import Document, DocumentVersion, Page
from tutor_api.knowledge.storage import MemoryObjectStorage


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


def _seed_preview_target(
    client: TestClient,
    engine: object,
    storage: MemoryObjectStorage,
    *,
    username: str,
) -> tuple[dict, dict, str]:
    registration = register(client, username)
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    source_key = f"private/{username}/original.pdf"
    page_key = f"private/{username}/page-7.txt"
    storage.put_if_absent(source_key, b"source-preview-bytes", content_type="application/pdf")
    storage.put_if_absent(page_key, b"page-preview-bytes", content_type="text/plain")
    with sessionmaker(bind=engine)() as session:
        seed_chunk(
            session,
            user_id=UUID(registration["user"]["id"]),
            space_id=UUID(registration["personal_space"]["id"]),
            knowledge_base_id=UUID(knowledge_base["id"]),
            source_name="chapter-1.pdf",
            content="previewable quadratic content",
            vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            page_number=7,
        )
        version = session.scalar(
            select(DocumentVersion)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.source_key == "chapter-1.pdf")
        )
        assert version is not None
        version.object_key = source_key
        page = session.scalar(select(Page).where(Page.document_version_id == version.id))
        assert page is not None
        page.text_object_key = page_key
        session.commit()
    search = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
        json={"query": "quadratic"},
    )
    assert search.status_code == 200, search.text
    return registration, knowledge_base, search.json()["results"][0]["citation"]["id"]


def test_cited_source_and_page_preview_map_to_correct_objects_with_bounded_range() -> None:
    storage = TrackingStorage()
    client, engine = make_client(FixedEmbeddingAdapter(), storage)
    try:
        _, knowledge_base, citation_id = _seed_preview_target(
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
        assert source.content == b"urce"
        assert source.headers["content-range"] == "bytes 2-5/20"
        assert source.headers["accept-ranges"] == "bytes"
        assert source.headers["x-content-type-options"] == "nosniff"
        assert page.content == b"page"
        assert page.headers["content-range"] == "bytes 0-3/18"
        serialized = source.text + str(source.headers) + page.text + str(page.headers)
        assert "private/preview-owner" not in serialized
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
        _, knowledge_base, citation_id = _seed_preview_target(
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
        _, knowledge_base, citation_id = _seed_preview_target(
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
        _, knowledge_base, citation_id = _seed_preview_target(
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
        assert "private/" not in failure.text
        assert forged.status_code == 404
        assert storage.read_calls == 1
    finally:
        client.close()
        engine.dispose()
