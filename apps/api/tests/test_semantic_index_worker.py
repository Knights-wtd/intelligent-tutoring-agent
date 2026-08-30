from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.agent import models as agent_models  # noqa: F401
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.embeddings import HashEmbeddingAdapter
from tutor_api.knowledge.indexing import (
    ChunkingConfig,
    IndexBuildRequest,
    IndexingError,
    build_index,
    content_sha256,
    make_pipeline_signature,
)
from tutor_api.knowledge.models import (
    Block,
    BlockKind,
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
from tutor_api.knowledge.semantic_plan import SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT
from tutor_api.knowledge.semantic_worker import (
    FilesystemRawSidecarWriter,
    SemanticJobState,
    run_semantic_index_job,
)
from tutor_api.knowledge.service import enqueue_index_build
from tutor_api.knowledge.worker import make_build_index_handler
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault.models import (
    SemanticIndexPlan,
    SemanticIndexPlanState,
    VaultChangeSet,
    VaultChangeSetState,
    VaultChangeSource,
    VaultFile,
    VaultFileKind,
    VaultSyncState,
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as active:
        yield active
    Base.metadata.drop_all(engine)
    engine.dispose()


class Planner:
    provider = "test-provider"
    model = "test-model"

    def __init__(self, payload: object | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0
        self.after_call = None

    def generate(self, *, prompt: str, source_text: str, source_hash: str) -> object:
        self.calls += 1
        assert SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT in prompt
        assert source_text
        if self.after_call is not None:
            self.after_call()
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return self.payload


def graph(session: Session) -> tuple[User, Space, KnowledgeBase]:
    user = User(email="semantic@example.com", username="semantic", password_hash="h")
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Semantic")
    session.add(space)
    session.flush()
    kb = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name="Semantic KB",
    )
    session.add(kb)
    session.flush()
    return user, space, kb


def add_version(
    session: Session, user: User, space: Space, kb: KnowledgeBase, name: str, text: str
) -> DocumentVersion:
    document = Document(
        space_id=space.id,
        knowledge_base_id=kb.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title=name,
        source_kind="upload",
        source_key=f"{name}.md",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=kb.id,
        document_id=document.id,
        version_number=1,
        content_sha256=content_sha256(text),
        object_key=f"objects/{name}",
        content_type="text/markdown",
        state=DocumentVersionState.READY,
        created_by_user_id=user.id,
    )
    session.add(version)
    session.flush()
    page = Page(
        space_id=space.id,
        document_version_id=version.id,
        page_number=1,
        source_pointer=f"{name}.md#page=1",
        content_sha256=version.content_sha256,
        source_metadata={},
    )
    session.add(page)
    session.flush()
    session.add(
        Block(
            space_id=space.id,
            page_id=page.id,
            ordinal=0,
            kind=BlockKind.PARAGRAPH,
            source_pointer=f"{name}.md#block=0",
            content_sha256=content_sha256(text),
            text=text,
        )
    )
    session.flush()
    return version


def build_request(
    user: User, space: Space, kb: KnowledgeBase, versions: tuple[UUID, ...]
) -> IndexBuildRequest:
    return IndexBuildRequest(
        space_id=space.id,
        knowledge_base_id=kb.id,
        created_by_user_id=user.id,
        document_version_ids=versions,
        parser_signature=make_pipeline_signature("parser", "markdown", "1"),
        ocr_signature=make_pipeline_signature("ocr", "disabled", "1"),
        chunking=ChunkingConfig(max_chars=1200, overlap_chars=0),
    )


def plan_payload(source_hash: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "source_hash": source_hash,
        "chunks": [
            {
                "ordinal": 0,
                "heading": "核心",
                "start": 0,
                "end": 8,
                "concepts": ["原子激活"],
                "tags": ["迁移"],
            }
        ],
        "concepts": [
            {
                "name": "原子激活",
                "aliases": ["atomic activation"],
                "tags": ["索引"],
                "provenance": "source",
                "confidence": 1.0,
            }
        ],
        "terms": [
            {
                "term": "shadow sync",
                "definition": "双写校验阶段",
                "provenance": "model",
                "confidence": 0.8,
            }
        ],
        "links": [],
    }


def add_vault_file(session: Session, space: Space, kb: KnowledgeBase, text: str) -> VaultFile:
    raw = text.encode("utf-8")
    file = VaultFile(
        space_id=space.id,
        knowledge_base_id=kb.id,
        relative_path="notes/source.md",
        file_kind=VaultFileKind.MARKDOWN,
        content_hash=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        sync_state=VaultSyncState.SYNCED,
        revision=1,
    )
    session.add(file)
    session.flush()
    return file


def test_planner_failure_keeps_previous_active_index(session: Session, tmp_path: Path) -> None:
    user, space, kb = graph(session)
    old = add_version(session, user, space, kb, "old", "old active material")
    adapter = HashEmbeddingAdapter(dimension=8)
    old_result = build_index(session, build_request(user, space, kb, (old.id,)), adapter)
    active_id = old_result.index_version_id
    new = add_version(session, user, space, kb, "new", "new semantic material")
    vault_file = add_vault_file(session, space, kb, "new semantic material")

    result = run_semantic_index_job(
        session,
        request=build_request(user, space, kb, (old.id, new.id)),
        adapter=adapter,
        vault_file_id=vault_file.id,
        source_text="new semantic material",
        planner=Planner(error=RuntimeError("provider unavailable secret")),
        sidecar_writer=FilesystemRawSidecarWriter(tmp_path / "sidecars"),
    )

    session.expire_all()
    active = session.get(IndexVersion, active_id)
    assert result.state is SemanticJobState.FAILED
    assert result.error_code == "semantic_provider_unavailable"
    assert active is not None and active.state is IndexVersionState.ACTIVE
    assert active.activated_at is not None
    failed = session.get(IndexVersion, result.index_version_id)
    assert failed is not None and failed.state is IndexVersionState.FAILED


def test_semantic_success_enriches_chunks_then_atomically_activates(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    old = add_version(session, user, space, kb, "old", "old active material")
    adapter = HashEmbeddingAdapter(dimension=8)
    old_id = build_index(
        session, build_request(user, space, kb, (old.id,)), adapter
    ).index_version_id
    new = add_version(session, user, space, kb, "new", "new semantic material")
    vault_file = add_vault_file(session, space, kb, "new semantic material")
    planner = Planner(plan_payload(vault_file.content_hash))

    result = run_semantic_index_job(
        session,
        request=build_request(user, space, kb, (old.id, new.id)),
        adapter=adapter,
        vault_file_id=vault_file.id,
        source_text="new semantic material",
        planner=planner,
        sidecar_writer=FilesystemRawSidecarWriter(tmp_path / "sidecars"),
    )

    assert result.state is SemanticJobState.ACTIVE
    assert planner.calls == 1
    session.expire_all()
    old_index = session.get(IndexVersion, old_id)
    new_index = session.get(IndexVersion, result.index_version_id)
    plan = session.get(SemanticIndexPlan, result.semantic_plan_id)
    chunks = list(
        session.scalars(
            select(Chunk)
            .where(Chunk.index_version_id == result.index_version_id)
            .order_by(Chunk.ordinal)
        )
    )
    assert old_index is not None and old_index.state is IndexVersionState.RETIRED
    assert new_index is not None and new_index.state is IndexVersionState.ACTIVE
    assert new_index.source_snapshot_hash == vault_file.content_hash
    assert new_index.activation_status == "semantic_active"
    assert plan is not None and plan.state is SemanticIndexPlanState.APPLIED
    assert plan.raw_sidecar_reference is not None
    raw_sidecar = Path(plan.raw_sidecar_reference)
    assert raw_sidecar.is_file()
    assert hashlib.sha256(raw_sidecar.read_bytes()).hexdigest() == hashlib.sha256(
        json.dumps(
            planner.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert any("原子激活" in chunk.lexical_terms for chunk in chunks)
    assert any("shadow" in chunk.lexical_terms for chunk in chunks)


def test_invalid_plan_is_classified_and_keeps_previous_active_index(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    old = add_version(session, user, space, kb, "old-invalid", "old active material")
    adapter = HashEmbeddingAdapter(dimension=8)
    old_id = build_index(
        session, build_request(user, space, kb, (old.id,)), adapter
    ).index_version_id
    new = add_version(session, user, space, kb, "new-invalid", "new semantic material")
    vault_file = add_vault_file(session, space, kb, "new semantic material")
    invalid = plan_payload(vault_file.content_hash)
    invalid["chunks"][0]["end"] = 0

    result = run_semantic_index_job(
        session,
        request=build_request(user, space, kb, (old.id, new.id)),
        adapter=adapter,
        vault_file_id=vault_file.id,
        source_text="new semantic material",
        planner=Planner(invalid),
        sidecar_writer=FilesystemRawSidecarWriter(tmp_path / "sidecars"),
    )

    assert result.state is SemanticJobState.FAILED
    assert result.error_code == "semantic_plan_invalid"
    session.expire_all()
    assert session.get(IndexVersion, old_id).state is IndexVersionState.ACTIVE
    assert session.get(IndexVersion, result.index_version_id).state is IndexVersionState.FAILED
    plan = session.get(SemanticIndexPlan, result.semantic_plan_id)
    assert plan is not None and plan.failure_code == "semantic_plan_invalid"
    assert plan.raw_sidecar_reference is not None
    assert Path(plan.raw_sidecar_reference).is_file()


def test_source_change_after_provider_response_marks_plan_stale(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    old = add_version(session, user, space, kb, "old", "old active material")
    adapter = HashEmbeddingAdapter(dimension=8)
    old_id = build_index(
        session, build_request(user, space, kb, (old.id,)), adapter
    ).index_version_id
    new = add_version(session, user, space, kb, "new", "new semantic material")
    vault_file = add_vault_file(session, space, kb, "new semantic material")
    planner = Planner(plan_payload(vault_file.content_hash))

    def mutate() -> None:
        vault_file.content_hash = "f" * 64
        vault_file.revision += 1
        session.flush()

    planner.after_call = mutate
    result = run_semantic_index_job(
        session,
        request=build_request(user, space, kb, (old.id, new.id)),
        adapter=adapter,
        vault_file_id=vault_file.id,
        source_text="new semantic material",
        planner=planner,
        sidecar_writer=FilesystemRawSidecarWriter(tmp_path / "sidecars"),
    )

    assert result.state is SemanticJobState.STALE
    session.expire_all()
    assert session.get(IndexVersion, old_id).state is IndexVersionState.ACTIVE
    assert session.get(IndexVersion, result.index_version_id).state is IndexVersionState.FAILED
    assert (
        session.get(SemanticIndexPlan, result.semantic_plan_id).state
        is SemanticIndexPlanState.STALE
    )


def test_validated_plan_is_reused_for_same_source_contract(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    version = add_version(session, user, space, kb, "one", "semantic material")
    vault_file = add_vault_file(session, space, kb, "semantic material")
    adapter = HashEmbeddingAdapter(dimension=8)
    first = Planner(plan_payload(vault_file.content_hash))
    request = build_request(user, space, kb, (version.id,))
    first_result = run_semantic_index_job(
        session,
        request=request,
        adapter=adapter,
        vault_file_id=vault_file.id,
        source_text="semantic material",
        planner=first,
        sidecar_writer=FilesystemRawSidecarWriter(tmp_path / "sidecars"),
    )
    second = Planner(error=AssertionError("provider must not be called"))
    second_result = run_semantic_index_job(
        session,
        request=request,
        adapter=adapter,
        vault_file_id=vault_file.id,
        source_text="semantic material",
        planner=second,
        sidecar_writer=FilesystemRawSidecarWriter(tmp_path / "sidecars"),
    )
    assert first_result.semantic_plan_id == second_result.semantic_plan_id
    assert second_result.reused_plan is True
    assert second.calls == 0


def test_enqueued_build_preserves_snapshot_and_semantic_contract(session: Session) -> None:
    user, space, kb = graph(session)
    version = add_version(session, user, space, kb, "contract", "semantic material")
    vault_file = add_vault_file(session, space, kb, "semantic material")
    semantic_plan_id = UUID("11111111-1111-1111-1111-111111111111")
    source_change_set_id = UUID("22222222-2222-2222-2222-222222222222")
    change_set = VaultChangeSet(
        id=source_change_set_id,
        space_id=space.id,
        knowledge_base_id=kb.id,
        source=VaultChangeSource.API,
        state=VaultChangeSetState.COMMITTED,
        after_snapshot_hash=vault_file.content_hash,
    )
    plan = SemanticIndexPlan(
        id=semantic_plan_id,
        space_id=space.id,
        knowledge_base_id=kb.id,
        vault_file_id=vault_file.id,
        change_set_id=source_change_set_id,
        input_hash=vault_file.content_hash,
        provider="test-provider",
        model="test-model",
        schema_version="1",
        prompt_hash=hashlib.sha256(
            SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT.encode("utf-8")
        ).hexdigest(),
        state=SemanticIndexPlanState.VALIDATED,
    )
    session.add(change_set)
    session.flush()
    session.add(plan)
    session.flush()
    request = replace(
        build_request(user, space, kb, (version.id,)),
        source_snapshot_hash=vault_file.content_hash,
        semantic_plan_id=semantic_plan_id,
        source_change_set_id=source_change_set_id,
    )
    adapter = HashEmbeddingAdapter(dimension=8)
    job = enqueue_index_build(
        session,
        request=request,
        embedding_adapter=adapter,
    )
    assert job.checkpoint["source_snapshot_hash"] == vault_file.content_hash
    assert job.checkpoint["semantic_plan_id"] == str(semantic_plan_id)
    assert job.checkpoint["source_change_set_id"] == str(source_change_set_id)

    make_build_index_handler(adapter)(session, job)
    target = session.get(IndexVersion, job.index_version_id)
    assert target is not None and target.state is IndexVersionState.ACTIVE
    assert target.source_snapshot_hash == vault_file.content_hash
    assert target.source_change_set_id == source_change_set_id


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("source_snapshot_hash", "A" * 64),
        ("source_change_set_id", "22222222222222222222222222222222"),
        ("semantic_plan_id", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
    ],
)
def test_build_worker_rejects_invalid_semantic_checkpoint(
    session: Session, key: str, value: object
) -> None:
    user, space, kb = graph(session)
    version = add_version(session, user, space, kb, f"invalid-{key}", "material")
    adapter = HashEmbeddingAdapter(dimension=8)
    job = enqueue_index_build(
        session,
        request=build_request(user, space, kb, (version.id,)),
        embedding_adapter=adapter,
    )
    job.checkpoint[key] = value

    with pytest.raises(IndexingError, match="index_job_checkpoint_invalid"):
        make_build_index_handler(adapter)(session, job)




def test_semantic_plan_persists_change_set_on_create_and_reuse(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    version = add_version(session, user, space, kb, "plan-provenance", "semantic material")
    vault_file = add_vault_file(session, space, kb, "semantic material")
    first_change_set = VaultChangeSet(
        space_id=space.id,
        knowledge_base_id=kb.id,
        source=VaultChangeSource.API,
        state=VaultChangeSetState.COMMITTED,
        after_snapshot_hash=vault_file.content_hash,
    )
    second_change_set = VaultChangeSet(
        space_id=space.id,
        knowledge_base_id=kb.id,
        source=VaultChangeSource.API,
        state=VaultChangeSetState.COMMITTED,
        after_snapshot_hash=vault_file.content_hash,
    )
    session.add_all([first_change_set, second_change_set])
    session.flush()
    adapter = HashEmbeddingAdapter(dimension=8)
    first = Planner(plan_payload(vault_file.content_hash))
    first_result = run_semantic_index_job(
        session,
        request=replace(
            build_request(user, space, kb, (version.id,)),
            source_change_set_id=first_change_set.id,
        ),
        adapter=adapter,
        vault_file_id=vault_file.id,
        source_text="semantic material",
        planner=first,
        sidecar_writer=FilesystemRawSidecarWriter(tmp_path / "sidecars"),
    )
    plan = session.get(SemanticIndexPlan, first_result.semantic_plan_id)
    assert plan is not None and plan.change_set_id == first_change_set.id

    second = Planner(error=AssertionError("provider must not be called"))
    second_result = run_semantic_index_job(
        session,
        request=replace(
            build_request(user, space, kb, (version.id,)),
            source_change_set_id=second_change_set.id,
        ),
        adapter=adapter,
        vault_file_id=vault_file.id,
        source_text="semantic material",
        planner=second,
        sidecar_writer=FilesystemRawSidecarWriter(tmp_path / "sidecars"),
    )
    assert second_result.semantic_plan_id == first_result.semantic_plan_id
    assert second_result.reused_plan is True
    assert plan.change_set_id == second_change_set.id
