from datetime import UTC, datetime
from math import inf, nan
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.knowledge.indexing import (
    _embedding_contract_signature,
    content_sha256,
    normalize_lexical_terms,
)
from tutor_api.knowledge.models import (
    Chunk,
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    IndexVersion,
    IndexVersionState,
    Page,
)
from tutor_api.knowledge.retrieval import MAX_EXCERPT_CHARACTERS, reciprocal_rank_fusion
from tutor_api.main import create_app


class FixedEmbeddingAdapter:
    def __init__(
        self,
        vectors: dict[str, list[float]] | None = None,
        *,
        backend: str = "hash",
        model: str = "feature-hash-v1",
        dimension: int = 8,
        signature: str = "hash:feature-hash-v1:8",
    ) -> None:
        self.vectors = vectors or {}
        self.backend = backend
        self.model = model
        self.dimension = dimension
        self.signature = signature

    def embed(self, text: str) -> list[float]:
        return self.vectors.get(text, [1.0] + [0.0] * (self.dimension - 1))


class ControlledEmbeddingAdapter(FixedEmbeddingAdapter):
    def __init__(self, result: object) -> None:
        super().__init__()
        self._result = result
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        del text
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return cast(list[float], self._result)


class FailingPreviewStorage:
    def __init__(self) -> None:
        self.read_calls = 0

    def get_object_range(self, key: str, *, start: int, length: int):
        del start, length
        self.read_calls += 1
        raise RuntimeError(f"provider credentials leaked for {key}")


class UnexpectedReadStorage:
    def __init__(self) -> None:
        self.read_calls = 0

    def get_object_range(self, key: str, *, start: int, length: int):
        del key, start, length
        self.read_calls += 1
        raise AssertionError("citation target must be authorized before object read")


def make_client(
    adapter: FixedEmbeddingAdapter | None = None, object_storage: object | None = None
) -> tuple[TestClient, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    app = create_app(
        Settings(app_env="test"), sessionmaker(bind=engine), object_storage=object_storage
    )
    app.state.embedding_adapter = adapter or FixedEmbeddingAdapter()
    return TestClient(app), engine


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


def create_knowledge_base(client: TestClient, space_id: str) -> dict:
    response = client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": "检索教材"}
    )
    assert response.status_code == 201
    return response.json()


def seed_chunk(
    session: Session,
    *,
    user_id: UUID,
    space_id: UUID,
    knowledge_base_id: UUID,
    source_name: str,
    content: str,
    vector: list[float],
    index_state: IndexVersionState = IndexVersionState.ACTIVE,
    index_version: int = 1,
    existing_index: IndexVersion | None = None,
    ordinal: int = 0,
    page_number: int = 7,
    content_type: str = "application/pdf",
) -> UUID:
    document = Document(
        space_id=space_id,
        knowledge_base_id=knowledge_base_id,
        owner_user_id=user_id,
        created_by_user_id=user_id,
        title=source_name,
        source_kind="upload",
        source_key=source_name,
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document.id,
        version_number=1,
        content_sha256=content_sha256(content),
        object_key=f"objects/{source_name}",
        content_type=content_type,
        state=DocumentVersionState.READY,
        created_by_user_id=user_id,
    )
    session.add(version)
    session.flush()
    page = Page(
        space_id=space_id,
        document_version_id=version.id,
        page_number=page_number,
        source_pointer=f"{source_name}#page={page_number}",
        content_sha256=content_sha256(content),
        source_metadata={},
    )
    session.add(page)
    session.flush()
    index = existing_index
    if index is None:
        index = IndexVersion(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            version_number=index_version,
            state=index_state,
            parser_signature="parser:1",
            ocr_signature="ocr:1",
            chunking_signature="chunking:1",
            embedding_backend="hash",
            embedding_model="feature-hash-v1",
            embedding_dimension=8,
            embedding_contract_signature=_embedding_contract_signature(FixedEmbeddingAdapter()),
            index_signature=f"index:{index_version}",
            created_by_user_id=user_id,
            completed_at=datetime.now(UTC),
            activated_at=datetime.now(UTC) if index_state is IndexVersionState.ACTIVE else None,
        )
        session.add(index)
        session.flush()
    chunk = Chunk(
        space_id=space_id,
        knowledge_base_id=knowledge_base_id,
        index_version_id=index.id,
        document_version_id=version.id,
        page_id=page.id,
        block_id=None,
        ordinal=ordinal,
        source_pointer=f"{source_name}#page={page_number}#chunk={ordinal}",
        content_sha256=content_sha256(content),
        content=content,
        lexical_terms=normalize_lexical_terms(content),
        embedding_dimension=8,
        index_signature=index.index_signature,
        embedding=vector,
    )
    session.add(chunk)
    session.flush()
    return chunk.id


def test_search_returns_exact_lexical_match_with_opaque_page_citation() -> None:
    client, engine = make_client()
    try:
        registration = register(client, "retrieval-owner")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            chunk_id = seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="algebra.md",
                content="The quadratic formula solves ax squared plus bx plus c.",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            session.commit()

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "quadratic formula"},
        )

        assert response.status_code == 200, response.text
        result = response.json()["results"]
        assert result == [
            {
                "excerpt": "The quadratic formula solves ax squared plus bx plus c.",
                "citation": {
                    "id": result[0]["citation"]["id"],
                    "source_name": "algebra.md",
                    "page_number": 7,
                },
            }
        ]
        citation_id = result[0]["citation"]["id"]
        assert citation_id.startswith("cite_")
        assert chunk_id.hex not in citation_id
        assert "objects/algebra.md" not in response.text
        assert "#chunk=" not in response.text
    finally:
        client.close()
        engine.dispose()


def test_search_omits_synthetic_page_number_for_docx_citations() -> None:
    client, engine = make_client()
    try:
        registration = register(client, "retrieval-docx-owner")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="wireless.docx",
                content="The final chapter explains cellular handoff procedures.",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                page_number=1,
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            )
            session.commit()

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "cellular handoff"},
        )

        assert response.status_code == 200, response.text
        citation = response.json()["results"][0]["citation"]
        assert citation["source_name"] == "wireless.docx"
        assert citation["page_number"] is None
    finally:
        client.close()
        engine.dispose()


def test_search_combines_lexical_and_vector_recall_with_deterministic_rrf() -> None:
    adapter = FixedEmbeddingAdapter(
        {"quadratic": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}
    )
    client, engine = make_client(adapter)
    try:
        registration = register(client, "rrf-owner")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            common = {
                "user_id": UUID(registration["user"]["id"]),
                "space_id": UUID(registration["personal_space"]["id"]),
                "knowledge_base_id": UUID(knowledge_base["id"]),
            }
            seed_chunk(
                session,
                **common,
                source_name="lexical.md",
                content="quadratic equations use a discriminant",
                vector=[0.8, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            active_index = session.scalar(
                select(IndexVersion).where(
                    IndexVersion.knowledge_base_id == common["knowledge_base_id"],
                    IndexVersion.state == IndexVersionState.ACTIVE,
                )
            )
            assert active_index is not None
            seed_chunk(
                session,
                **common,
                source_name="semantic.md",
                content="the discriminant determines the roots",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                existing_index=active_index,
                ordinal=1,
            )
            session.commit()

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "quadratic", "limit": 2},
        )

        assert response.status_code == 200, response.text
        assert [item["citation"]["source_name"] for item in response.json()["results"]] == [
            "lexical.md",
            "semantic.md",
        ]
        assert reciprocal_rank_fusion((["a", "b"], ["b", "a"])) == ["a", "b"]
    finally:
        client.close()
        engine.dispose()


def test_search_uses_vector_recall_but_excludes_non_active_indexes() -> None:
    adapter = FixedEmbeddingAdapter(
        {"meaning": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}
    )
    client, engine = make_client(adapter)
    try:
        registration = register(client, "active-index-owner")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            common = {
                "user_id": UUID(registration["user"]["id"]),
                "space_id": UUID(registration["personal_space"]["id"]),
                "knowledge_base_id": UUID(knowledge_base["id"]),
            }
            seed_chunk(
                session,
                **common,
                source_name="active.md",
                content="a vector-only answer from the active index",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            seed_chunk(
                session,
                **common,
                source_name="retired.md",
                content="meaning hidden in retired index",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                index_version=2,
                index_state=IndexVersionState.RETIRED,
            )
            session.commit()

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "meaning"},
        )

        assert response.status_code == 200, response.text
        assert [item["citation"]["source_name"] for item in response.json()["results"]] == [
            "active.md"
        ]
    finally:
        client.close()
        engine.dispose()


def test_search_hides_other_tenant_knowledge_base_before_result_access() -> None:
    owner, engine = make_client()
    outsider = TestClient(owner.app)
    try:
        registration = register(owner, "search-owner")
        knowledge_base = create_knowledge_base(owner, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="private.md",
                content="private exact answer",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            session.commit()
        register(outsider, "search-outsider")

        response = outsider.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "private"},
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "资源不存在"}
    finally:
        outsider.close()
        owner.close()
        engine.dispose()


def test_search_rejects_unbounded_query_and_result_count_and_bounds_excerpt() -> None:
    client, engine = make_client()
    try:
        registration = register(client, "search-bounds")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        content = "prefix " + ("quadratic filler " * 80)
        with sessionmaker(bind=engine)() as session:
            seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="long.md",
                content=content,
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            session.commit()

        too_long = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "q" * 501},
        )
        too_many = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "quadratic", "limit": 21},
        )
        bounded = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "quadratic"},
        )

        assert too_long.status_code == too_many.status_code == 422
        assert len(bounded.json()["results"][0]["excerpt"]) <= MAX_EXCERPT_CHARACTERS
    finally:
        client.close()
        engine.dispose()

def test_search_degrades_to_lexical_only_when_active_embedding_contract_differs() -> None:
    adapter = FixedEmbeddingAdapter(
        {"contract": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
        model="feature-hash-v2",
        signature="hash:feature-hash-v2:8",
    )
    client, engine = make_client(adapter)
    try:
        registration = register(client, "retrieval-contract-mismatch")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            common = {
                "user_id": UUID(registration["user"]["id"]),
                "space_id": UUID(registration["personal_space"]["id"]),
                "knowledge_base_id": UUID(knowledge_base["id"]),
            }
            seed_chunk(
                session,
                **common,
                source_name="lexical.md",
                content="contract exact lexical answer",
                vector=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            seed_chunk(
                session,
                **common,
                source_name="stale-vector.md",
                content="semantic-only stale embedding",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                existing_index=session.scalar(
                    select(IndexVersion).where(
                        IndexVersion.knowledge_base_id == common["knowledge_base_id"],
                        IndexVersion.state == IndexVersionState.ACTIVE,
                    )
                ),
                ordinal=1,
            )
            session.commit()

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "contract"},
        )

        assert response.status_code == 200, response.text
        assert [item["citation"]["source_name"] for item in response.json()["results"]] == [
            "lexical.md"
        ]
    finally:
        client.close()
        engine.dispose()


def test_search_finds_lexical_hit_beyond_first_thousand_active_chunks() -> None:
    client, engine = make_client(FixedEmbeddingAdapter(signature="hash:feature-hash-v2:8"))
    try:
        registration = register(client, "retrieval-full-index")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            first_chunk_id = seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="large.md",
                content="ordinary filler zero",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            first_chunk = session.get(Chunk, first_chunk_id)
            assert first_chunk is not None
            for ordinal in range(1, 1_000):
                content = f"ordinary filler {ordinal}"
                session.add(
                    Chunk(
                        space_id=first_chunk.space_id,
                        knowledge_base_id=first_chunk.knowledge_base_id,
                        index_version_id=first_chunk.index_version_id,
                        document_version_id=first_chunk.document_version_id,
                        page_id=first_chunk.page_id,
                        block_id=None,
                        ordinal=ordinal,
                        source_pointer=f"large.md#page=7#chunk={ordinal}",
                        content_sha256=content_sha256(content),
                        content=content,
                        lexical_terms=normalize_lexical_terms(content),
                        embedding_dimension=8,
                        index_signature=first_chunk.index_signature,
                        embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    )
                )
            target_content = "needle-beyond-bound exact lexical answer"
            session.add(
                Chunk(
                    space_id=first_chunk.space_id,
                    knowledge_base_id=first_chunk.knowledge_base_id,
                    index_version_id=first_chunk.index_version_id,
                    document_version_id=first_chunk.document_version_id,
                    page_id=first_chunk.page_id,
                    block_id=None,
                    ordinal=1_000,
                    source_pointer="large.md#page=7#chunk=1000",
                    content_sha256=content_sha256(target_content),
                    content=target_content,
                    lexical_terms=normalize_lexical_terms(target_content),
                    embedding_dimension=8,
                    index_signature=first_chunk.index_signature,
                    embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                )
            )
            session.commit()

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "needle-beyond-bound", "limit": 1},
        )

        assert response.status_code == 200, response.text
        assert response.json()["results"][0]["excerpt"] == target_content
    finally:
        client.close()
        engine.dispose()


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(RuntimeError("provider backend secret"), id="provider-exception"),
        pytest.param([1.0, 0.0], id="wrong-dimension"),
        pytest.param([True] + [0.0] * 7, id="bool-component"),
        pytest.param([nan] + [0.0] * 7, id="nan-component"),
        pytest.param([inf] + [0.0] * 7, id="positive-infinity"),
        pytest.param([-inf] + [0.0] * 7, id="negative-infinity"),
    ],
)
def test_search_rejects_invalid_embedding_results_without_unsafe_retrieval(result: object) -> None:
    adapter = ControlledEmbeddingAdapter(result)
    client, engine = make_client(adapter)
    try:
        registration = register(client, "retrieval-invalid-embedding")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="valid-index.md",
                content="a lexical result must not bypass invalid query embedding",
                vector=[1.0] + [0.0] * 7,
            )
            session.commit()

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "lexical result"},
        )

        assert response.status_code == 503, response.text
        assert response.json() == {"detail": "检索服务暂不可用"}
        assert "provider backend secret" not in response.text
        assert adapter.calls == 1
    finally:
        client.close()
        engine.dispose()


def test_search_without_active_index_skips_embedding_provider() -> None:
    adapter = ControlledEmbeddingAdapter(RuntimeError("embedding provider must not be called"))
    client, engine = make_client(adapter)
    try:
        registration = register(client, "retrieval-no-active-index")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "nothing indexed yet"},
        )

        assert response.status_code == 200, response.text
        assert response.json() == {"results": []}
        assert adapter.calls == 0
    finally:
        client.close()
        engine.dispose()


@pytest.mark.parametrize("endpoint", ["source", "page"])
def test_cited_preview_hides_valid_citation_from_nonmember_before_object_read(
    endpoint: str,
) -> None:
    storage = UnexpectedReadStorage()
    owner, engine = make_client(object_storage=storage)
    outsider = TestClient(owner.app)
    try:
        registration = register(owner, f"preview-nonmember-owner-{endpoint}")
        knowledge_base = create_knowledge_base(owner, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            chunk_id = seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name=f"nonmember-{endpoint}.md",
                content="active cited content",
                vector=[1.0] + [0.0] * 7,
            )
            if endpoint == "page":
                chunk = session.get(Chunk, chunk_id)
                assert chunk is not None
                page = session.get(Page, chunk.page_id)
                assert page is not None
                page.text_object_key = "objects/nonmember-page.txt"
            session.commit()

        search = owner.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "active cited"},
        )
        assert search.status_code == 200, search.text
        citation_id = search.json()["results"][0]["citation"]["id"]
        register(outsider, f"preview-other-{endpoint}")

        response = outsider.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/citations/{citation_id}/{endpoint}"
        )

        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "\u8d44\u6e90\u4e0d\u5b58\u5728"}
        assert storage.read_calls == 0
    finally:
        outsider.close()
        owner.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("endpoint", "ineligible_target"),
    [
        pytest.param("source", "index", id="retired-index-source"),
        pytest.param("page", "document", id="archived-document-page"),
    ],
)
def test_cited_preview_rejects_ineligible_targets_before_object_read(
    endpoint: str, ineligible_target: str
) -> None:
    storage = UnexpectedReadStorage()
    client, engine = make_client(object_storage=storage)
    try:
        registration = register(client, f"preview-ineligible-{ineligible_target}")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            chunk_id = seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name=f"{ineligible_target}.md",
                content="cited content",
                vector=[1.0] + [0.0] * 7,
            )
            session.commit()

        search = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "cited"},
        )
        assert search.status_code == 200, search.text
        citation_id = search.json()["results"][0]["citation"]["id"]

        with sessionmaker(bind=engine)() as session:
            chunk = session.get(Chunk, chunk_id)
            assert chunk is not None
            if ineligible_target == "index":
                index = session.get(IndexVersion, chunk.index_version_id)
                assert index is not None
                index.state = IndexVersionState.RETIRED
            else:
                page = session.get(Page, chunk.page_id)
                assert page is not None
                page.text_object_key = "objects/archived-document-page.txt"
                version = session.get(DocumentVersion, chunk.document_version_id)
                assert version is not None
                document = session.get(Document, version.document_id)
                assert document is not None
                document.state = DocumentState.ARCHIVED
            session.commit()

        response = client.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/citations/{citation_id}/{endpoint}"
        )

        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "资源不存在"}
        assert storage.read_calls == 0
    finally:
        client.close()
        engine.dispose()


def test_page_preview_redacts_storage_failures() -> None:
    storage = FailingPreviewStorage()
    client, engine = make_client(object_storage=storage)
    try:
        registration = register(client, "preview-page-storage-failure")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            chunk_id = seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="page-preview.md",
                content="page preview content",
                vector=[1.0] + [0.0] * 7,
            )
            chunk = session.get(Chunk, chunk_id)
            assert chunk is not None
            page = session.get(Page, chunk.page_id)
            assert page is not None
            page.text_object_key = "objects/page-preview.txt"
            session.commit()

        search = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "page preview"},
        )
        assert search.status_code == 200, search.text
        citation_id = search.json()["results"][0]["citation"]["id"]

        response = client.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/citations/{citation_id}/page",
            headers={"Range": "bytes=0-3"},
        )

        assert response.status_code == 503, response.text
        assert response.json() == {"detail": "检索服务暂不可用"}
        assert "provider credentials" not in response.text
        assert "objects/page-preview.txt" not in response.text
        assert storage.read_calls == 1
    finally:
        client.close()
        engine.dispose()


def test_bounded_excerpt_maps_casefold_expansion_back_to_original_offsets() -> None:
    from tutor_api.knowledge.retrieval import bounded_excerpt

    # "ß" casefolds to "ss": folding the whole string first shifts every offset
    # after it by +1, so the old implementation sliced the window at the wrong
    # original position and the hit term landed outside the excerpt.
    content = (
        "Weiß " + "filler " * 120 + " the quadratic formula appears here "
        + "filler " * 120
    )
    excerpt = bounded_excerpt(content, ["quadratic"])

    assert len(excerpt) <= MAX_EXCERPT_CHARACTERS + 2  # ellipses
    assert "quadratic formula" in excerpt

    # The ligature "ﬁ" casefolds to "fi" (length 2 -> 2, but ﬃ -> ffi grows);
    # a leading expandable character must not displace the window either.
    ligature_content = "ﬁ" + "x" * 900 + " quadratic endpoint"
    ligature_excerpt = bounded_excerpt(ligature_content, ["quadratic"])
    assert "quadratic endpoint" in ligature_excerpt
    assert ligature_excerpt.endswith("quadratic endpoint")


def test_bounded_excerpt_without_any_hit_starts_at_the_beginning() -> None:
    from tutor_api.knowledge.retrieval import bounded_excerpt

    content = "y" * 900
    assert bounded_excerpt(content, ["absent"]) == content


def test_vector_only_hits_below_similarity_floor_return_no_results() -> None:
    # The chunk's stored vector is orthogonal to the query embedding
    # (cosine similarity = 0), and the query shares no lexical term with the
    # content: with the floor in place RRF has no ranking to fuse and the
    # search must return an empty result instead of a confident-looking
    # irrelevant excerpt.
    adapter = FixedEmbeddingAdapter(
        {"unrelated question": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}
    )
    client, engine = make_client(adapter)
    try:
        registration = register(client, "floor-owner")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="orthogonal.md",
                content="completely different storage internals",
                vector=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            session.commit()

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "unrelated question"},
        )

        assert response.status_code == 200
        assert response.json() == {"results": []}
    finally:
        client.close()
        engine.dispose()


def test_vector_hits_above_similarity_floor_are_still_returned() -> None:
    adapter = FixedEmbeddingAdapter(
        {"path loss": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}
    )
    client, engine = make_client(adapter)
    try:
        registration = register(client, "floor-pass-owner")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="aligned.md",
                content="path loss increases with transmission distance",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            session.commit()

        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "path loss"},
        )

        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert "path loss" in results[0]["excerpt"]
    finally:
        client.close()
        engine.dispose()


def test_search_full_content_returns_untruncated_chunk_text() -> None:
    """导师模式返回完整原文块;默认检索仍是有界摘录,面板不受影响。"""

    from tutor_api.identity.models import User
    from tutor_api.knowledge.retrieval import search_knowledge

    client, engine = make_client()
    try:
        registration = register(client, "full-content-owner")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        filler = "推导步骤 " * 400  # 约 2000 字符,远超 500 字摘录上限
        long_content = f"quadratic {filler} 收尾同样包含 quadratic 关键词。"
        with sessionmaker(bind=engine)() as session:
            seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="algebra.md",
                content=long_content,
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            user = session.get(User, UUID(registration["user"]["id"]))
            assert user is not None
            kb_id = UUID(knowledge_base["id"])

            bounded = search_knowledge(
                session,
                user,
                kb_id,
                query="quadratic",
                limit=5,
                embedding_adapter=FixedEmbeddingAdapter(),
                citation_secret="test-secret",
            )
            full = search_knowledge(
                session,
                user,
                kb_id,
                query="quadratic",
                limit=5,
                embedding_adapter=FixedEmbeddingAdapter(),
                citation_secret="test-secret",
                full_content=True,
            )

        assert bounded, "lexical hit expected"
        assert len(bounded[0].excerpt) <= MAX_EXCERPT_CHARACTERS + 2
        assert full, "full-content hit expected"
        assert full[0].excerpt == " ".join(long_content.split())
        assert len(full[0].excerpt) > MAX_EXCERPT_CHARACTERS
        assert full[0].citation.source_name == "algebra.md"
    finally:
        client.close()
        engine.dispose()


def test_search_endpoint_full_flag_returns_untruncated_chunk_text() -> None:
    """`full: true` 走 API 层直通 full_content，返回完整分块而非 500 字摘要。"""

    client, engine = make_client()
    try:
        registration = register(client, "retrieval-full-endpoint")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        long_content = " ".join(
            f"第{number}段讲解二次方程的配方法与判别式的含义。" for number in range(1, 60)
        )
        with sessionmaker(bind=engine)() as session:
            seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="algebra.md",
                content=long_content,
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
            session.commit()

        bounded = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "判别式", "limit": 5},
        )
        full = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/search",
            json={"query": "判别式", "limit": 5, "full": True},
        )

        assert bounded.status_code == 200, bounded.text
        assert full.status_code == 200, full.text
        bounded_excerpt = bounded.json()["results"][0]["excerpt"]
        full_excerpt = full.json()["results"][0]["excerpt"]
        assert len(bounded_excerpt) <= MAX_EXCERPT_CHARACTERS + 2
        assert full_excerpt == " ".join(long_content.split())
        assert len(full_excerpt) > MAX_EXCERPT_CHARACTERS
    finally:
        client.close()
        engine.dispose()


def test_document_chunks_endpoint_returns_full_chunk_content_in_order() -> None:
    """资料查看器按序拿到整份文档的详细分块（含页码），未索引文档返回空列表。"""

    client, engine = make_client()
    try:
        registration = register(client, "retrieval-chunks")
        knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
        with sessionmaker(bind=engine)() as session:
            seed_chunk(
                session,
                user_id=UUID(registration["user"]["id"]),
                space_id=UUID(registration["personal_space"]["id"]),
                knowledge_base_id=UUID(knowledge_base["id"]),
                source_name="physics.md",
                content="第一块：牛顿第一定律描述惯性。",
                vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ordinal=0,
                page_number=3,
            )
            document = session.scalar(select(Document).where(Document.source_key == "physics.md"))
            assert document is not None
            document_id = document.id
            version = session.scalar(
                select(DocumentVersion).where(DocumentVersion.document_id == document.id)
            )
            index = session.scalar(select(IndexVersion).limit(1))
            assert version is not None and index is not None
            page = Page(
                space_id=document.space_id,
                document_version_id=version.id,
                page_number=4,
                source_pointer="physics.md#page=4",
                content_sha256=content_sha256("第二块：牛顿第二定律描述加速度与力的关系。"),
                source_metadata={},
            )
            session.add(page)
            session.flush()
            session.add(
                Chunk(
                    space_id=document.space_id,
                    knowledge_base_id=document.knowledge_base_id,
                    index_version_id=index.id,
                    document_version_id=version.id,
                    page_id=page.id,
                    block_id=None,
                    ordinal=1,
                    source_pointer="physics.md#page=4#chunk=1",
                    content_sha256=content_sha256("第二块：牛顿第二定律描述加速度与力的关系。"),
                    content="第二块：牛顿第二定律描述加速度与力的关系。",
                    lexical_terms=[],
                    embedding_dimension=8,
                    index_signature=index.index_signature,
                    embedding=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                )
            )
            session.commit()

        response = client.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/documents/{document_id}/chunks"
        )

        assert response.status_code == 200, response.text
        chunks = response.json()
        assert [chunk["ordinal"] for chunk in chunks] == [0, 1]
        assert chunks[0]["content"] == "第一块：牛顿第一定律描述惯性。"
        assert chunks[1]["content"] == "第二块：牛顿第二定律描述加速度与力的关系。"
        assert [chunk["page_number"] for chunk in chunks] == [3, 4]

        other_response = client.post(
            f"/api/v1/spaces/{registration['personal_space']['id']}/knowledge-bases",
            json={"name": "另一个检索教材"},
        )
        assert other_response.status_code == 201
        other_kb = other_response.json()
        missing = client.get(
            f"/api/v1/knowledge-bases/{other_kb['id']}/documents/{document_id}/chunks"
        )
        assert missing.status_code == 200
        assert missing.json() == []
    finally:
        client.close()
        engine.dispose()
