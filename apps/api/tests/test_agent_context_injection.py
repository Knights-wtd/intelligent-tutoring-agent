from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

import tutor_api.agent.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.agent.schemas import RuntimeStartResponse
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.identity.router import get_current_user
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
    KnowledgeBase,
    Page,
)
from tutor_api.main import create_app
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault.models import VaultFile, VaultFileKind


class RecordingRuntime:
    def __init__(self) -> None:
        self.payloads = []

    async def start_turn(self, payload, *, request_id=None):
        del request_id
        self.payloads.append(payload)
        return RuntimeStartResponse(
            execution_id="execution-context",
            native_session_id="native-context",
            accepted_sequence=0,
        )


@pytest.fixture
def context_api(tmp_path: Path) -> Generator[tuple[TestClient, dict[str, object]], None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        user = User(
            email="context-owner@example.com",
            username="context-owner",
            password_hash="hash",
        )
        db.add(user)
        db.flush()
        space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Context owner")
        db.add(space)
        db.flush()
        knowledge_base = KnowledgeBase(
            space_id=space.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            name="Context KB",
        )
        db.add(knowledge_base)
        db.flush()
        ids: dict[str, object] = {
            "user_id": user.id,
            "space_id": space.id,
            "knowledge_base_id": knowledge_base.id,
        }

    settings = Settings(
        app_env="test",
        agent_runtime_url="http://127.0.0.1:8765",
        agent_runtime_callback_url="http://127.0.0.1:8000/api/v1/agent/runtime/events",
        agent_runtime_token="runtime-token",
        agent_capability_secret="capability-secret-capability-secret",
        agent_vault_root=str(tmp_path / "vault"),
        agent_sidecar_root=str(tmp_path / "sidecars"),
    )
    app = create_app(settings, factory)
    runtime = RecordingRuntime()
    app.state.agent_runtime_client = runtime

    def current_user() -> User:
        with factory() as db:
            user = db.get(User, ids["user_id"])
            assert user is not None
            db.expunge(user)
            return user

    app.dependency_overrides[get_current_user] = current_user
    with TestClient(app) as client:
        ids.update({"app": app, "factory": factory, "runtime": runtime})
        yield client, ids
    engine.dispose()


def _create_agent_session(client: TestClient, knowledge_base_id: UUID) -> str:
    response = client.post(
        "/api/v1/agent/sessions",
        json={
            "knowledge_base_id": str(knowledge_base_id),
            "provider": "faro",
            "model": "gemini-3.7-flash-tiered",
            "context_window": 32_000,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_indexed_chunk(
    db: Session,
    *,
    user_id: UUID,
    space_id: UUID,
    knowledge_base_id: UUID,
    source_name: str,
    content: str,
    embedding_adapter,
) -> None:
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
    db.add(document)
    db.flush()
    version = DocumentVersion(
        space_id=space_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document.id,
        version_number=1,
        content_sha256=content_sha256(content),
        object_key=f"objects/{source_name}",
        content_type="application/pdf",
        state=DocumentVersionState.READY,
        created_by_user_id=user_id,
    )
    db.add(version)
    db.flush()
    page = Page(
        space_id=space_id,
        document_version_id=version.id,
        page_number=7,
        source_pointer=f"{source_name}#page=7",
        content_sha256=content_sha256(content),
        source_metadata={},
    )
    db.add(page)
    db.flush()
    index = IndexVersion(
        space_id=space_id,
        knowledge_base_id=knowledge_base_id,
        version_number=1,
        state=IndexVersionState.ACTIVE,
        parser_signature="parser:context-test",
        ocr_signature="ocr:context-test",
        chunking_signature="chunking:context-test",
        embedding_backend=embedding_adapter.backend,
        embedding_model=embedding_adapter.model,
        embedding_dimension=embedding_adapter.dimension,
        embedding_contract_signature=_embedding_contract_signature(embedding_adapter),
        index_signature="index:context-test",
        created_by_user_id=user_id,
        completed_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
    )
    db.add(index)
    db.flush()
    db.add(
        Chunk(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            index_version_id=index.id,
            document_version_id=version.id,
            page_id=page.id,
            block_id=None,
            ordinal=0,
            source_pointer=f"{source_name}#page=7#chunk=0",
            content_sha256=content_sha256(content),
            content=content,
            lexical_terms=normalize_lexical_terms(content),
            embedding_dimension=embedding_adapter.dimension,
            index_signature=index.index_signature,
            embedding=embedding_adapter.embed(content),
        )
    )


def test_linked_knowledge_base_injects_real_search_results_with_source_name(
    context_api: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = context_api
    app = context["app"]
    factory = context["factory"]
    runtime = context["runtime"]
    assert isinstance(app, FastAPI)
    assert isinstance(runtime, RecordingRuntime)
    with factory.begin() as db:
        _seed_indexed_chunk(
            db,
            user_id=context["user_id"],
            space_id=context["space_id"],
            knowledge_base_id=context["knowledge_base_id"],
            source_name="algebra.md",
            content="The quadratic formula solves ax squared plus bx plus c.",
            embedding_adapter=app.state.embedding_adapter,
        )
    session_id = _create_agent_session(client, context["knowledge_base_id"])

    response = client.post(
        f"/api/v1/agent/sessions/{session_id}/turns",
        json={
            "prompt": "quadratic formula",
            "linked_contexts": [
                {
                    "knowledge_base_id": str(context["knowledge_base_id"]),
                    "label": "知识库：Context KB",
                    "source_name": "reference.pdf",
                }
            ],
        },
    )

    assert response.status_code == 202, response.text
    assert len(runtime.payloads) == 1
    assert runtime.payloads[0].input[0] == {"type": "text", "text": "quadratic formula"}
    injected = runtime.payloads[0].input[1]
    assert injected["type"] == "text"
    assert "algebra.md" in injected["text"]
    assert "第 7 页" in injected["text"]
    assert "The quadratic formula solves" in injected["text"]
    assert len(injected["text"]) <= 4_000


def test_linked_knowledge_base_without_results_preserves_original_runtime_input(
    context_api: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = context_api
    runtime = context["runtime"]
    assert isinstance(runtime, RecordingRuntime)
    session_id = _create_agent_session(client, context["knowledge_base_id"])

    response = client.post(
        f"/api/v1/agent/sessions/{session_id}/turns",
        json={
            "prompt": "no indexed result",
            "linked_contexts": [{"knowledge_base_id": str(context["knowledge_base_id"])}],
        },
    )

    assert response.status_code == 202, response.text
    assert runtime.payloads[0].input == [{"type": "text", "text": "no indexed result"}]


def test_unreadable_linked_knowledge_base_is_rejected_before_runtime(
    context_api: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = context_api
    factory = context["factory"]
    runtime = context["runtime"]
    assert isinstance(runtime, RecordingRuntime)
    with factory.begin() as db:
        outsider = User(email="outsider@example.com", username="outsider", password_hash="hash")
        db.add(outsider)
        db.flush()
        outsider_space = Space(owner_id=outsider.id, kind=SpaceKind.PERSONAL, name="Outsider")
        db.add(outsider_space)
        db.flush()
        outsider_kb = KnowledgeBase(
            space_id=outsider_space.id,
            owner_user_id=outsider.id,
            created_by_user_id=outsider.id,
            name="Outsider KB",
        )
        db.add(outsider_kb)
        db.flush()
        outsider_kb_id = outsider_kb.id
    session_id = _create_agent_session(client, context["knowledge_base_id"])

    response = client.post(
        f"/api/v1/agent/sessions/{session_id}/turns",
        json={
            "prompt": "private material",
            "linked_contexts": [{"knowledge_base_id": str(outsider_kb_id)}],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "资源不存在"}
    assert runtime.payloads == []


def test_linked_vault_file_must_match_its_linked_knowledge_base(
    context_api: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = context_api
    factory = context["factory"]
    runtime = context["runtime"]
    assert isinstance(runtime, RecordingRuntime)
    with factory.begin() as db:
        second_kb = KnowledgeBase(
            space_id=context["space_id"],
            owner_user_id=context["user_id"],
            created_by_user_id=context["user_id"],
            name="Second readable KB",
        )
        db.add(second_kb)
        db.flush()
        vault_file = VaultFile(
            space_id=context["space_id"],
            knowledge_base_id=second_kb.id,
            relative_path="notes/second.md",
            file_kind=VaultFileKind.MARKDOWN,
            content_hash="a" * 64,
            size_bytes=12,
        )
        db.add(vault_file)
        db.flush()
        vault_file_id = vault_file.id
    session_id = _create_agent_session(client, context["knowledge_base_id"])

    response = client.post(
        f"/api/v1/agent/sessions/{session_id}/turns",
        json={
            "prompt": "mismatched file",
            "linked_contexts": [
                {
                    "knowledge_base_id": str(context["knowledge_base_id"]),
                    "vault_file_id": str(vault_file_id),
                }
            ],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "资源不存在"}
    assert runtime.payloads == []


def test_readable_vault_file_resolves_its_knowledge_base_for_retrieval(
    context_api: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = context_api
    app = context["app"]
    factory = context["factory"]
    runtime = context["runtime"]
    assert isinstance(app, FastAPI)
    assert isinstance(runtime, RecordingRuntime)
    with factory.begin() as db:
        vault_file = VaultFile(
            space_id=context["space_id"],
            knowledge_base_id=context["knowledge_base_id"],
            relative_path="geometry.md",
            file_kind=VaultFileKind.MARKDOWN,
            content_hash="b" * 64,
            size_bytes=24,
        )
        db.add(vault_file)
        db.flush()
        vault_file_id = vault_file.id
        _seed_indexed_chunk(
            db,
            user_id=context["user_id"],
            space_id=context["space_id"],
            knowledge_base_id=context["knowledge_base_id"],
            source_name="geometry.md",
            content="The Pythagorean theorem relates the sides of a right triangle.",
            embedding_adapter=app.state.embedding_adapter,
        )
    session_id = _create_agent_session(client, context["knowledge_base_id"])

    response = client.post(
        f"/api/v1/agent/sessions/{session_id}/turns",
        json={
            "prompt": "Pythagorean theorem",
            "linked_contexts": [{"vault_file_id": str(vault_file_id)}],
        },
    )

    assert response.status_code == 202, response.text
    assert "geometry.md" in runtime.payloads[0].input[1]["text"]
