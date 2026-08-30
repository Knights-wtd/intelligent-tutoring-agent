import binascii
import hashlib
import struct
import zlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

import tutor_api.knowledge.worker as worker_module
from tutor_api.agent import models as agent_models  # noqa: F401
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.candidates import CandidateValidationError
from tutor_api.knowledge.embeddings import HashEmbeddingAdapter
from tutor_api.knowledge.indexing import ChunkingConfig, IndexingError
from tutor_api.knowledge.models import (
    Block,
    Chunk,
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    IndexVersion,
    IndexVersionState,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeBase,
    Page,
)
from tutor_api.knowledge.ocr import RenderedPage
from tutor_api.knowledge.parsers import ParsedDocument, ParsedPage, parse_markdown
from tutor_api.knowledge.service import (
    PreparedUpload,
    persist_parsed_document_and_enqueue_build,
    upload_prepared_knowledge_document,
)
from tutor_api.knowledge.storage import MemoryObjectStorage, StoredObject
from tutor_api.knowledge.worker import (
    DurableJobKind,
    WorkerConfig,
    claim_job_statement,
    claim_next_job,
    complete_job,
    fail_job,
    make_build_index_handler,
    make_parse_document_handler,
    make_semantic_plan_handler,
    make_vault_project_handler,
    make_vault_scan_handler,
    run_worker_once,
)
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault import models as vault_models  # noqa: F401
from tutor_api.vault.models import (
    VaultChangeEntry,
    VaultChangeOperation,
    VaultChangeSet,
    VaultChangeSetState,
    VaultChangeSource,
    VaultFile,
    VaultFileKind,
    VaultSyncCursor,
)


@pytest.fixture
def factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    value = sessionmaker(bind=engine, expire_on_commit=False)
    yield value
    Base.metadata.drop_all(engine)
    engine.dispose()


def target(session: Session, suffix: str = "worker") -> tuple[User, KnowledgeBase, IndexVersion]:
    user = User(email=f"{suffix}@example.com", username=f"user-{suffix}", password_hash="h")
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name=suffix)
    session.add(space)
    session.flush()
    kb = KnowledgeBase(
        space_id=space.id, owner_user_id=user.id, created_by_user_id=user.id, name=suffix
    )
    session.add(kb)
    session.flush()
    index = IndexVersion(
        space_id=space.id,
        knowledge_base_id=kb.id,
        version_number=1,
        parser_signature="tutor:parser:v1:" + "a" * 64,
        ocr_signature="tutor:ocr:v1:" + "b" * 64,
        chunking_signature="tutor:chunking:v1:" + "c" * 64,
        embedding_backend="hash",
        embedding_model="feature-hash-v1",
        embedding_dimension=8,
        embedding_contract_signature="tutor:embedding:v1:" + "e" * 64,
        index_signature="tutor:index:v1:" + "d" * 64,
        created_by_user_id=user.id,
    )
    session.add(index)
    session.flush()
    return user, kb, index


def add_job(
    session: Session,
    user: User,
    kb: KnowledgeBase,
    index: IndexVersion,
    *,
    now: datetime,
    state: IngestionJobState = IngestionJobState.QUEUED,
    attempts: int = 0,
    maximum: int = 3,
    owner: str | None = None,
    expires: datetime | None = None,
    started: datetime | None = None,
) -> IngestionJob:
    job = IngestionJob(
        space_id=kb.space_id,
        knowledge_base_id=kb.id,
        index_version_id=index.id,
        kind=IngestionJobKind.BUILD_INDEX,
        state=state,
        idempotency_key=f"build:{uuid4()}",
        attempt_count=attempts,
        max_attempts=maximum,
        available_at=now,
        lease_owner=owner,
        lease_expires_at=expires,
        checkpoint={},
        created_by_user_id=user.id,
        started_at=started,
    )
    session.add(job)
    session.flush()
    return job


def real_build_target(
    session: Session, *, suffix: str, now: datetime
) -> tuple[HashEmbeddingAdapter, IndexVersion, IndexVersion, IngestionJob, DocumentVersion]:
    user, kb, old_active = target(session, suffix)
    old_active.state = IndexVersionState.ACTIVE
    old_active.completed_at = now
    old_active.activated_at = now
    document = Document(
        space_id=kb.space_id,
        knowledge_base_id=kb.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title=f"{suffix}.md",
        source_kind="upload",
        source_key=f"{suffix}.md",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    raw = f"# {suffix}\n\nWorker build body.\n".encode()
    version = DocumentVersion(
        space_id=kb.space_id,
        knowledge_base_id=kb.id,
        document_id=document.id,
        version_number=1,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        object_key=f"objects/{suffix}",
        content_type="text/markdown",
        state=DocumentVersionState.PARSING,
        created_by_user_id=user.id,
    )
    session.add(version)
    session.flush()
    adapter = HashEmbeddingAdapter(dimension=8)
    job = persist_parsed_document_and_enqueue_build(
        session,
        document_version_id=version.id,
        parsed_document=parse_markdown(raw, source_name=f"{suffix}.md"),
        parser_signature="tutor:parser:v1:" + "f" * 64,
        ocr_signature="tutor:ocr:v1:" + "0" * 64,
        chunking=ChunkingConfig(),
        object_storage=MemoryObjectStorage(),
        embedding_adapter=adapter,
    )
    job.available_at = now
    build_target = session.get(IndexVersion, job.index_version_id)
    page = session.scalar(select(Page).where(Page.document_version_id == version.id))
    block = session.scalar(select(Block).where(Block.page_id == page.id)) if page else None
    assert build_target and page and block
    partial_content = "partial build artifact"
    session.add(
        Chunk(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            index_version_id=build_target.id,
            document_version_id=version.id,
            page_id=page.id,
            block_id=block.id,
            ordinal=0,
            source_pointer=f"{suffix}:partial:0",
            content_sha256=hashlib.sha256(partial_content.encode()).hexdigest(),
            content=partial_content,
            lexical_terms=["artifact", "build", "partial"],
            embedding_dimension=build_target.embedding_dimension,
            index_signature=build_target.index_signature,
            embedding=[0.0] * build_target.embedding_dimension,
        )
    )
    session.flush()
    return adapter, old_active, build_target, job, version


def test_postgresql_claim_contract_uses_for_update_skip_locked() -> None:
    sql = str(
        claim_job_statement(datetime(2026, 8, 17, tzinfo=UTC)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).upper()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert all(state in sql for state in ("QUEUED", "RETRY_WAIT", "RUNNING"))


def test_worker_claims_only_registered_handler_kinds(factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "registered-kinds")
        build = add_job(session, user, kb, index, now=now)
        document = Document(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            title="parse",
            source_kind="upload",
            source_key="parse.md",
            state=DocumentState.ACTIVE,
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            document_id=document.id,
            version_number=1,
            content_sha256="a" * 64,
            object_key="objects/parse",
            content_type="text/markdown",
            state=DocumentVersionState.UPLOADED,
            created_by_user_id=user.id,
        )
        session.add(version)
        session.flush()
        parse = IngestionJob(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            document_id=document.id,
            document_version_id=version.id,
            kind=IngestionJobKind.PARSE_DOCUMENT,
            state=IngestionJobState.QUEUED,
            idempotency_key=f"parse:{uuid4()}",
            available_at=now - timedelta(seconds=1),
            checkpoint={},
            created_by_user_id=user.id,
        )
        session.add(parse)
        session.flush()

    with factory.begin() as session:
        claimed = claim_next_job(
            session,
            worker_id="build-only",
            now=now,
            lease_duration=timedelta(seconds=30),
            kinds=(IngestionJobKind.BUILD_INDEX,),
        )
        assert claimed and claimed.id == build.id
        untouched = session.get(IngestionJob, parse.id)
        assert untouched and untouched.state is IngestionJobState.QUEUED


def test_uploaded_parse_job_runs_full_worker_pipeline_idempotently(
    factory: sessionmaker[Session],
) -> None:

    from tutor_api.knowledge.embeddings import HashEmbeddingAdapter

    now = datetime.now(UTC)
    storage = MemoryObjectStorage()
    adapter = HashEmbeddingAdapter(dimension=8)
    with factory.begin() as session:
        user = User(email="pipeline@example.com", username="pipeline", password_hash="h")
        session.add(user)
        session.flush()
        space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Pipeline")
        session.add(space)
        session.flush()
        kb = KnowledgeBase(
            space_id=space.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            name="Pipeline",
        )
        session.add(kb)
        session.flush()
        raw = b"# Reliable indexing\n\nWorker parsed body.\n"
        uploaded = upload_prepared_knowledge_document(
            session,
            user,
            kb.id,
            PreparedUpload(
                source_name="pipeline.md",
                content_type="text/markdown",
                content_sha256=hashlib.sha256(raw).hexdigest(),
                temporary_file=BytesIO(raw),
            ),
            "pipeline-request",
            storage,
        )
        uploaded.job.available_at = now
        parse_job_id = uploaded.job.id
        version_id = uploaded.version.id

    parse_handler = make_parse_document_handler(storage, adapter)
    config = WorkerConfig(worker_id="pipeline-worker", retry_delay=timedelta(0))
    assert run_worker_once(
        factory,
        {IngestionJobKind.PARSE_DOCUMENT: parse_handler},
        config=config,
        now=now,
    )

    with factory() as session:
        parse_job = session.get(IngestionJob, parse_job_id)
        version = session.get(DocumentVersion, version_id)
        build_job = session.scalar(
            select(IngestionJob).where(IngestionJob.kind == IngestionJobKind.BUILD_INDEX)
        )
        assert parse_job and parse_job.state is IngestionJobState.COMPLETED
        assert version and version.state is DocumentVersionState.READY
        assert session.scalar(select(func.count()).select_from(Page)) == 1
        assert session.scalar(select(func.count()).select_from(Block)) == 2
        assert build_job and build_job.state is IngestionJobState.QUEUED
        build_job_id = build_job.id
        target_index_id = build_job.index_version_id

    assert run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: make_build_index_handler(adapter)},
        config=config,
        now=now + timedelta(seconds=1),
    )

    with factory() as session:
        chunk_count = session.scalar(select(func.count()).select_from(Chunk))
        assert chunk_count and chunk_count > 0

    with factory.begin() as session:
        parse_job = session.get(IngestionJob, parse_job_id)
        build_job = session.get(IngestionJob, build_job_id)
        assert parse_job and build_job
        parse_handler(session, parse_job)
        make_build_index_handler(adapter)(session, build_job)

    with factory() as session:
        active = session.get(IndexVersion, target_index_id)
        assert active and active.state is IndexVersionState.ACTIVE
        assert session.scalar(select(func.count()).select_from(Page)) == 1
        assert session.scalar(select(func.count()).select_from(Block)) == 2
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 2
        assert session.scalar(select(func.count()).select_from(IndexVersion)) == 1
        assert session.scalar(select(func.count()).select_from(Chunk)) == chunk_count


def test_parse_worker_fails_closed_when_ocr_is_disabled(factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    storage = MemoryObjectStorage()
    adapter = HashEmbeddingAdapter(dimension=8)
    with factory.begin() as session:
        user, kb, _ = target(session, "ocr-disabled")
        uploaded = upload_prepared_knowledge_document(
            session,
            user,
            kb.id,
            PreparedUpload(
                source_name="scan.png",
                content_type="image/png",
                content_sha256=hashlib.sha256(raw).hexdigest(),
                temporary_file=BytesIO(raw),
            ),
            "ocr-disabled-request",
            storage,
        )
        uploaded.job.max_attempts = 1
        uploaded.job.available_at = now
        job_id = uploaded.job.id
        version_id = uploaded.version.id

    assert run_worker_once(
        factory,
        {IngestionJobKind.PARSE_DOCUMENT: make_parse_document_handler(storage, adapter)},
        config=WorkerConfig(worker_id="ocr-disabled-worker", retry_delay=timedelta(0)),
        now=now,
    )

    with factory() as session:
        job = session.get(IngestionJob, job_id)
        version = session.get(DocumentVersion, version_id)
        assert job and job.state is IngestionJobState.FAILED
        assert job.last_error_code == "ocr_disabled" and job.last_error_detail is None
        assert version and version.state is DocumentVersionState.FAILED
        assert session.scalar(select(func.count()).select_from(Page)) == 0


def test_parse_worker_persists_content_when_a_completed_ocr_page_is_blank(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 18, 12, tzinfo=UTC)
    raw = b"%PDF-mixed-ocr"
    source_name = "mixed-ocr.pdf"
    parsed = ParsedDocument(
        source_name=source_name,
        media_type="application/pdf",
        pages=(
            ParsedPage(page_number=1, blocks=(), needs_ocr=True),
            ParsedPage(page_number=2, blocks=(), needs_ocr=True),
        ),
    )

    class Renderer:
        def render_page(
            self,
            pdf: bytes,
            *,
            page_number: int,
            max_pixels: int,
            timeout_seconds: float,
        ) -> RenderedPage:
            assert pdf == raw
            return RenderedPage(
                image=f"page-{page_number}".encode(),
                media_type="image/png",
                width=1,
                height=1,
            )

    class OCR:
        backend = "test"

        def extract_text(
            self,
            image: bytes,
            *,
            languages: tuple[str, ...],
            timeout_seconds: float | None = None,
        ) -> str:
            return "Indexed OCR text" if image == b"page-1" else "   "

    monkeypatch.setattr(worker_module, "_parse_uploaded_document", lambda *_args, **_kwargs: parsed)
    storage = MemoryObjectStorage()
    adapter = HashEmbeddingAdapter(dimension=8)
    with factory.begin() as session:
        user, kb, _ = target(session, "mixed-ocr")
        uploaded = upload_prepared_knowledge_document(
            session,
            user,
            kb.id,
            PreparedUpload(
                source_name=source_name,
                content_type="application/pdf",
                content_sha256=hashlib.sha256(raw).hexdigest(),
                temporary_file=BytesIO(raw),
            ),
            "mixed-ocr-request",
            storage,
        )
        uploaded.job.max_attempts = 1
        uploaded.job.available_at = now
        job_id = uploaded.job.id
        version_id = uploaded.version.id

    assert run_worker_once(
        factory,
        {
            IngestionJobKind.PARSE_DOCUMENT: make_parse_document_handler(
                storage, adapter, ocr_adapter=OCR(), renderer=Renderer()
            )
        },
        config=WorkerConfig(worker_id="mixed-ocr-worker", retry_delay=timedelta(0)),
        now=now,
    )

    with factory() as session:
        job = session.get(IngestionJob, job_id)
        version = session.get(DocumentVersion, version_id)
        pages = list(session.scalars(select(Page).order_by(Page.page_number)))
        blocks = list(session.scalars(select(Block).order_by(Block.ordinal)))
        assert job and job.state is IngestionJobState.COMPLETED
        assert version and version.state is DocumentVersionState.READY
        assert [page.page_number for page in pages] == [1, 2]
        assert [block.text for block in blocks] == ["Indexed OCR text"]
        assert blocks[0].page_id == pages[0].id


def test_parse_worker_fails_closed_for_completed_empty_ocr_result(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 18, 12, tzinfo=UTC)
    raw = b"%PDF-empty-ocr"
    source_name = "empty-ocr.pdf"
    parsed = ParsedDocument(
        source_name=source_name,
        media_type="application/pdf",
        pages=(ParsedPage(page_number=1, blocks=(), needs_ocr=True),),
    )

    class Renderer:
        def render_page(
            self,
            pdf: bytes,
            *,
            page_number: int,
            max_pixels: int,
            timeout_seconds: float,
        ) -> RenderedPage:
            assert pdf == raw
            return RenderedPage(
                image=b"blank-page",
                media_type="image/png",
                width=1,
                height=1,
            )

    class OCR:
        backend = "test"

        def extract_text(
            self,
            image: bytes,
            *,
            languages: tuple[str, ...],
            timeout_seconds: float | None = None,
        ) -> str:
            return "   "

    monkeypatch.setattr(worker_module, "_parse_uploaded_document", lambda *_args, **_kwargs: parsed)
    storage = MemoryObjectStorage()
    adapter = HashEmbeddingAdapter(dimension=8)
    with factory.begin() as session:
        user, kb, _ = target(session, "empty-ocr")
        uploaded = upload_prepared_knowledge_document(
            session,
            user,
            kb.id,
            PreparedUpload(
                source_name=source_name,
                content_type="application/pdf",
                content_sha256=hashlib.sha256(raw).hexdigest(),
                temporary_file=BytesIO(raw),
            ),
            "empty-ocr-request",
            storage,
        )
        uploaded.job.max_attempts = 1
        uploaded.job.available_at = now
        job_id = uploaded.job.id
        version_id = uploaded.version.id

    assert run_worker_once(
        factory,
        {
            IngestionJobKind.PARSE_DOCUMENT: make_parse_document_handler(
                storage, adapter, ocr_adapter=OCR(), renderer=Renderer()
            )
        },
        config=WorkerConfig(worker_id="empty-ocr-worker", retry_delay=timedelta(0)),
        now=now,
    )

    with factory() as session:
        job = session.get(IngestionJob, job_id)
        version = session.get(DocumentVersion, version_id)
        assert job and job.state is IngestionJobState.FAILED
        assert job.last_error_code == "ocr_empty_result" and job.last_error_detail is None
        assert version and version.state is DocumentVersionState.FAILED
        assert session.scalar(select(func.count()).select_from(Page)) == 0


def test_worker_main_registers_parse_build_and_candidate_handlers() -> None:
    from tutor_api.core.config import Settings
    from tutor_api.worker_main import create_handlers

    handlers = create_handlers(
        Settings(
            app_env="test",
            embedding_dimension=8,
            agent_mcp_config_paths=(),
            agent_skill_paths=(),
        )
    )
    assert set(handlers) == {
        IngestionJobKind.PARSE_DOCUMENT,
        IngestionJobKind.BUILD_INDEX,
        IngestionJobKind.GENERATE_MARKDOWN,
        DurableJobKind.VAULT_SCAN,
        DurableJobKind.VAULT_PROJECT,
        DurableJobKind.SEMANTIC_PLAN,
    }


def test_claim_leases_job_and_does_not_reclaim_live_lease(factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session)
        queued = add_job(session, user, kb, index, now=now)
    with factory.begin() as session:
        claimed = claim_next_job(
            session, worker_id="a", now=now, lease_duration=timedelta(seconds=30)
        )
        assert claimed and claimed.id == queued.id and claimed.state is IngestionJobState.RUNNING
        assert claimed.attempt_count == 1 and claimed.started_at == now
        assert claimed.lease_owner == "a" and claimed.lease_expires_at == now + timedelta(
            seconds=30
        )
    with factory.begin() as session:
        assert (
            claim_next_job(
                session,
                worker_id="b",
                now=now + timedelta(seconds=10),
                lease_duration=timedelta(seconds=30),
            )
            is None
        )


def test_stale_lease_recovers_but_live_lease_does_not(factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "stale")
        stale = add_job(
            session,
            user,
            kb,
            index,
            now=now - timedelta(minutes=2),
            state=IngestionJobState.RUNNING,
            attempts=1,
            owner="dead",
            expires=now - timedelta(seconds=1),
            started=now - timedelta(minutes=2),
        )
        add_job(
            session,
            user,
            kb,
            index,
            now=now - timedelta(minutes=2),
            state=IngestionJobState.RUNNING,
            attempts=1,
            owner="live",
            expires=now + timedelta(minutes=1),
            started=now - timedelta(minutes=2),
        )
    with factory.begin() as session:
        claimed = claim_next_job(
            session, worker_id="replacement", now=now, lease_duration=timedelta(seconds=30)
        )
        assert claimed and claimed.id == stale.id and claimed.attempt_count == 2
        assert claimed.lease_owner == "replacement"


def test_retry_is_bounded_and_error_detail_is_redacted(factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "retry")
        job = add_job(
            session,
            user,
            kb,
            index,
            now=now,
            state=IngestionJobState.RUNNING,
            attempts=1,
            maximum=2,
            owner="a",
            expires=now + timedelta(seconds=30),
            started=now,
        )
        fail_job(
            session,
            job_id=job.id,
            worker_id="a",
            now=now,
            error=RuntimeError("secret traceback /private"),
            retry_delay=timedelta(seconds=5),
        )
        assert job.state is IngestionJobState.RETRY_WAIT
        assert job.available_at == now + timedelta(seconds=5)
        assert job.last_error_code == "worker_unhandled_error" and job.last_error_detail is None
        assert job.lease_owner is None and job.lease_expires_at is None
    with factory.begin() as session:
        claimed = claim_next_job(
            session,
            worker_id="b",
            now=now + timedelta(seconds=5),
            lease_duration=timedelta(seconds=30),
        )
        assert claimed and claimed.attempt_count == 2
        fail_job(
            session,
            job_id=claimed.id,
            worker_id="b",
            now=now + timedelta(seconds=6),
            error=RuntimeError("secret"),
            retry_delay=timedelta(seconds=5),
        )
        assert claimed.state is IngestionJobState.FAILED
        assert claimed.completed_at == now + timedelta(seconds=6)
        assert claimed.attempt_count == claimed.max_attempts and claimed.last_error_detail is None


def test_candidate_validation_failure_preserves_stable_public_code(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 30, 10, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "candidate-validation")
        job = add_job(
            session,
            user,
            kb,
            index,
            now=now,
            state=IngestionJobState.RUNNING,
            attempts=1,
            maximum=1,
            owner="candidate-worker",
            expires=now + timedelta(seconds=30),
            started=now,
        )
        fail_job(
            session,
            job_id=job.id,
            worker_id="candidate-worker",
            now=now,
            error=CandidateValidationError(
                "candidate_formula_verification_invalid: model payload redacted"
            ),
        )

        assert job.last_error_code == "candidate_formula_verification_invalid"
        assert job.last_error_detail is None


def test_terminal_build_failure_fails_target_and_cleans_partial_chunks(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        adapter, old_active, build_target, job, _ = real_build_target(
            session, suffix="terminal-build", now=now
        )
        job.max_attempts = 1
        old_active_id = old_active.id
        target_id = build_target.id
        job_id = job.id

    class FailingEmbedding:
        backend = adapter.backend
        model = adapter.model
        dimension = adapter.dimension
        signature = adapter.signature

        def embed(self, text: str) -> list[float]:
            raise RuntimeError("private provider failure")

    assert run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: make_build_index_handler(FailingEmbedding())},
        config=WorkerConfig(worker_id="terminal-worker", retry_delay=timedelta(0)),
        now=now,
    )

    with factory() as session:
        failed_job = session.get(IngestionJob, job_id)
        failed_target = session.get(IndexVersion, target_id)
        active = session.get(IndexVersion, old_active_id)
        assert failed_job and failed_job.state is IngestionJobState.FAILED
        assert failed_target and failed_target.state is IndexVersionState.FAILED
        assert active and active.state is IndexVersionState.ACTIVE
        assert (
            session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.index_version_id == target_id)
            )
            == 0
        )


def test_terminal_semantic_plan_failure_preserves_inherited_index_and_chunks(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 12, 5, tzinfo=UTC)
    with factory.begin() as session:
        _, _, inherited_index, parent, _ = real_build_target(
            session, suffix="terminal-semantic", now=now
        )
        inherited_index.state = IndexVersionState.READY
        inherited_index.activation_status = "deterministic_ready"
        inherited_index.completed_at = now
        change_set = VaultChangeSet(
            space_id=parent.space_id,
            knowledge_base_id=parent.knowledge_base_id,
            source=VaultChangeSource.EXTERNAL_EDITOR,
            state=VaultChangeSetState.INDEXING,
            after_snapshot_hash="a" * 64,
            committed_at=now,
        )
        session.add(change_set)
        session.flush()
        semantic_job = worker_module._enqueue_durable_job(
            session,
            parent=parent,
            logical_kind=DurableJobKind.SEMANTIC_PLAN,
            idempotency_key=f"semantic-plan:{change_set.id}:{uuid4()}",
            checkpoint={"source_change_set_id": str(change_set.id)},
        )
        semantic_job.state = IngestionJobState.RUNNING
        semantic_job.attempt_count = semantic_job.max_attempts
        semantic_job.started_at = now
        semantic_job.lease_owner = "terminal-semantic-worker"
        semantic_job.lease_expires_at = now + timedelta(minutes=5)
        semantic_job_id = semantic_job.id
        change_set_id = change_set.id
        inherited_index_id = inherited_index.id

        fail_job(
            session,
            job_id=semantic_job.id,
            worker_id="terminal-semantic-worker",
            error=worker_module.WorkerPublicError("semantic_plan_failed"),
            now=now,
        )

    with factory() as session:
        failed_job = session.get(IngestionJob, semantic_job_id)
        failed_change_set = session.get(VaultChangeSet, change_set_id)
        preserved_index = session.get(IndexVersion, inherited_index_id)
        assert failed_job is not None and failed_job.state is IngestionJobState.FAILED
        assert failed_job.last_error_code == "semantic_plan_failed"
        assert failed_change_set is not None
        assert failed_change_set.state is VaultChangeSetState.FAILED
        assert failed_change_set.failure_code == "semantic_plan_failed"
        assert preserved_index is not None and preserved_index.state is IndexVersionState.READY
        assert preserved_index.activation_status == "deterministic_ready"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.index_version_id == inherited_index_id)
            )
            == 1
        )


def test_changed_embedding_contract_requeues_build_without_replacing_active_index(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        adapter, old_active, old_target, old_job, version = real_build_target(
            session, suffix="changed-contract", now=now
        )
        old_active_id = old_active.id
        old_target_id = old_target.id
        old_job_id = old_job.id
        old_job_key = old_job.idempotency_key

    class SignatureChangedEmbedding:
        backend = adapter.backend
        model = adapter.model
        dimension = adapter.dimension
        signature = f"{adapter.signature}:adapter-v2"

        def embed(self, text: str) -> list[float]:
            return adapter.embed(text)

    replacement_adapter = SignatureChangedEmbedding()
    config = WorkerConfig(worker_id="changed-contract-worker", retry_delay=timedelta(0))
    assert run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: make_build_index_handler(replacement_adapter)},
        config=config,
        now=now,
    )

    with factory() as session:
        completed_old_job = session.get(IngestionJob, old_job_id)
        failed_old_target = session.get(IndexVersion, old_target_id)
        preserved_active = session.get(IndexVersion, old_active_id)
        replacements = list(
            session.scalars(
                select(IngestionJob).where(
                    IngestionJob.kind == IngestionJobKind.BUILD_INDEX,
                    IngestionJob.idempotency_key != old_job_key,
                )
            )
        )
        assert completed_old_job and completed_old_job.state is IngestionJobState.COMPLETED
        assert completed_old_job.completed_at is not None
        assert completed_old_job.completed_at.replace(tzinfo=UTC) == now
        assert completed_old_job.index_version_id == old_target_id
        assert completed_old_job.idempotency_key == old_job_key
        assert failed_old_target and failed_old_target.state is IndexVersionState.FAILED
        assert failed_old_target.completed_at is not None
        assert failed_old_target.completed_at.replace(tzinfo=UTC) == now
        assert preserved_active and preserved_active.state is IndexVersionState.ACTIVE
        assert (
            session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.index_version_id == old_target_id)
            )
            == 0
        )
        assert len(replacements) == 1
        replacement = replacements[0]
        replacement_target = session.get(IndexVersion, replacement.index_version_id)
        assert replacement.state is IngestionJobState.QUEUED
        assert replacement_target and replacement_target.state is IndexVersionState.BUILDING
        assert replacement.index_version_id != old_target_id
        assert replacement.idempotency_key == f"build:{replacement_target.index_signature}"
        assert replacement.checkpoint == {
            "document_version_ids": [str(version.id)],
            "parser_signature": old_target.parser_signature,
            "ocr_signature": old_target.ocr_signature,
            "chunk_max_chars": ChunkingConfig().max_chars,
            "chunk_overlap_chars": ChunkingConfig().overlap_chars,
        }
        replacement_job_id = replacement.id
        replacement_target_id = replacement_target.id
        replacement_available_at = replacement.available_at

    with factory.begin() as session:
        completed_old_job = session.get(IngestionJob, old_job_id)
        assert completed_old_job is not None
        make_build_index_handler(replacement_adapter)(session, completed_old_job)
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.kind == IngestionJobKind.BUILD_INDEX)
            )
            == 2
        )

    assert run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: make_build_index_handler(replacement_adapter)},
        config=config,
        now=replacement_available_at + timedelta(seconds=1),
    )

    with factory() as session:
        replacement_job = session.get(IngestionJob, replacement_job_id)
        replacement_target = session.get(IndexVersion, replacement_target_id)
        previous_active = session.get(IndexVersion, old_active_id)
        assert replacement_job and replacement_job.state is IngestionJobState.COMPLETED
        assert replacement_target and replacement_target.state is IndexVersionState.ACTIVE
        assert previous_active and previous_active.state is IndexVersionState.RETIRED


def test_stale_exhausted_build_fails_only_its_target(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        _, _, build_target, build_job, version = real_build_target(
            session, suffix="stale-terminal", now=now
        )
        build_job.state = IngestionJobState.RUNNING
        build_job.attempt_count = build_job.max_attempts
        build_job.lease_owner = "dead-build-worker"
        build_job.lease_expires_at = now - timedelta(seconds=1)
        build_job.started_at = now - timedelta(minutes=1)
        unrelated = IndexVersion(
            space_id=build_target.space_id,
            knowledge_base_id=build_target.knowledge_base_id,
            version_number=build_target.version_number + 1,
            state=IndexVersionState.BUILDING,
            parser_signature="tutor:parser:v1:" + "1" * 64,
            ocr_signature="tutor:ocr:v1:" + "2" * 64,
            chunking_signature="tutor:chunking:v1:" + "3" * 64,
            embedding_backend="hash",
            embedding_model="feature-hash-v1",
            embedding_dimension=8,
            embedding_contract_signature="tutor:embedding:v1:" + "4" * 64,
            index_signature="tutor:index:v1:" + "5" * 64,
            created_by_user_id=build_target.created_by_user_id,
        )
        session.add(unrelated)
        session.flush()
        parse_job = IngestionJob(
            space_id=version.space_id,
            knowledge_base_id=version.knowledge_base_id,
            document_id=version.document_id,
            document_version_id=version.id,
            kind=IngestionJobKind.PARSE_DOCUMENT,
            state=IngestionJobState.RUNNING,
            idempotency_key=f"parse-stale:{version.id}",
            attempt_count=1,
            max_attempts=1,
            available_at=now - timedelta(minutes=1),
            lease_owner="dead-parse-worker",
            lease_expires_at=now - timedelta(seconds=1),
            checkpoint={},
            created_by_user_id=version.created_by_user_id,
            started_at=now - timedelta(minutes=1),
        )
        session.add(parse_job)
        session.flush()
        target_id = build_target.id
        unrelated_id = unrelated.id
        parse_job_id = parse_job.id

    with factory.begin() as session:
        assert (
            claim_next_job(
                session,
                worker_id="replacement",
                now=now,
                kinds=(IngestionJobKind.BUILD_INDEX, IngestionJobKind.PARSE_DOCUMENT),
            )
            is None
        )

    with factory() as session:
        failed_target = session.get(IndexVersion, target_id)
        untouched = session.get(IndexVersion, unrelated_id)
        stale_parse = session.get(IngestionJob, parse_job_id)
        stale_version = session.get(DocumentVersion, version.id)
        assert failed_target and failed_target.state is IndexVersionState.FAILED
        assert untouched and untouched.state is IndexVersionState.BUILDING
        assert stale_parse and stale_parse.state is IngestionJobState.FAILED
        assert stale_version and stale_version.state is DocumentVersionState.FAILED
        assert (
            session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.index_version_id == target_id)
            )
            == 0
        )


def test_restart_after_commit_does_not_duplicate_side_effect(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "restart")
        job = add_job(session, user, kb, index, now=now)
    calls: list[str] = []

    def handler(session: Session, claimed: IngestionJob) -> None:
        if claimed.checkpoint.get("effect_done"):
            return
        calls.append(str(claimed.id))
        claimed.checkpoint["effect_done"] = True

    config = WorkerConfig(
        worker_id="restart-worker",
        lease_duration=timedelta(seconds=30),
        retry_delay=timedelta(seconds=1),
    )
    assert run_worker_once(factory, {IngestionJobKind.BUILD_INDEX: handler}, config=config, now=now)
    assert not run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: handler},
        config=config,
        now=now + timedelta(seconds=1),
    )
    with factory() as session:
        persisted = session.get(IngestionJob, job.id)
        assert persisted and persisted.state is IngestionJobState.COMPLETED
        assert persisted.checkpoint == {"effect_done": True}
        assert persisted.lease_owner is None and persisted.lease_expires_at is None
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1
    assert calls == [str(job.id)]


def test_compose_worker_reuses_api_image_without_ports_or_root() -> None:
    from pathlib import Path

    import yaml

    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "compose.yaml").read_text(encoding="utf-8")
    )
    api = compose["services"]["api"]
    worker = compose["services"]["worker"]
    assert worker["image"] == api["image"]
    assert worker["build"] == api["build"]
    assert worker["environment"] == api["environment"]
    assert worker["command"] == ["python", "-m", "tutor_api.worker_main"]
    assert "ports" not in worker
    assert worker.get("user") not in {"root", "0", 0}


def test_completion_refreshes_lease_owner_before_committing(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "lease-race")
        job = add_job(
            session,
            user,
            kb,
            index,
            now=now,
            state=IngestionJobState.RUNNING,
            attempts=1,
            owner="original",
            expires=now + timedelta(seconds=30),
            started=now,
        )
        session.get(IngestionJob, job.id)
        session.execute(
            update(IngestionJob).where(IngestionJob.id == job.id).values(lease_owner="replacement"),
            execution_options={"synchronize_session": False},
        )

        with pytest.raises(RuntimeError, match="worker_lease_lost"):
            complete_job(
                session,
                job_id=job.id,
                worker_id="original",
                now=now + timedelta(seconds=1),
            )

        session.expire_all()
        persisted = session.get(IngestionJob, job.id)
        assert persisted and persisted.state is IngestionJobState.RUNNING
        assert persisted.lease_owner == "replacement"


@pytest.mark.parametrize(
    ("stored_data", "stored_content_type", "request_key"),
    (
        (b"# different immutable bytes\n", "text/markdown", "bytes"),
        (b"# trusted immutable bytes\n", "application/pdf", "content-type"),
    ),
)
def test_parse_worker_rejects_object_bytes_or_content_type_mismatched_to_version(
    factory: sessionmaker[Session],
    stored_data: bytes,
    stored_content_type: str,
    request_key: str,
) -> None:
    now = datetime(2026, 8, 19, 12, tzinfo=UTC)
    trusted = b"# trusted immutable bytes\n"
    upload_storage = MemoryObjectStorage()
    adapter = HashEmbeddingAdapter(dimension=8)

    with factory.begin() as session:
        user, kb, _ = target(session, "immutable-object")
        uploaded = upload_prepared_knowledge_document(
            session,
            user,
            kb.id,
            PreparedUpload(
                source_name="immutable.md",
                content_type="text/markdown",
                content_sha256=hashlib.sha256(trusted).hexdigest(),
                temporary_file=BytesIO(trusted),
            ),
            f"immutable-object-{request_key}",
            upload_storage,
        )
        uploaded.job.available_at = now
        uploaded.job.max_attempts = 1
        job_id = uploaded.job.id
        version_id = uploaded.version.id

    class MismatchedObjectStorage:
        def get_object(self, key: str) -> StoredObject:
            assert key
            return StoredObject(data=stored_data, content_type=stored_content_type)

    assert run_worker_once(
        factory,
        {
            IngestionJobKind.PARSE_DOCUMENT: make_parse_document_handler(
                MismatchedObjectStorage(), adapter
            )
        },
        config=WorkerConfig(worker_id="immutable-object-worker", retry_delay=timedelta(0)),
        now=now,
    )

    with factory() as session:
        job = session.get(IngestionJob, job_id)
        version = session.get(DocumentVersion, version_id)
        assert job and job.state is IngestionJobState.FAILED
        assert job.last_error_code == "object_content_mismatch"
        assert job.last_error_detail is None
        assert version and version.state is DocumentVersionState.FAILED
        assert session.scalar(select(func.count()).select_from(Page)) == 0
        assert session.scalar(select(func.count()).select_from(Block)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.kind == IngestionJobKind.BUILD_INDEX)
            )
            == 0
        )


def test_build_worker_terminally_rejects_tampered_checkpoint(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 19, 12, tzinfo=UTC)
    with factory.begin() as session:
        adapter, _, build_target, job, _ = real_build_target(
            session, suffix="tampered-checkpoint", now=now
        )
        job.max_attempts = 1
        job.checkpoint = {"document_version_ids": []}
        job_id = job.id
        target_id = build_target.id

    assert run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: make_build_index_handler(adapter)},
        config=WorkerConfig(worker_id="tampered-checkpoint-worker", retry_delay=timedelta(0)),
        now=now,
    )

    with factory() as session:
        job = session.get(IngestionJob, job_id)
        target_index = session.get(IndexVersion, target_id)
        assert job and job.state is IngestionJobState.FAILED
        assert job.last_error_code == "index_job_checkpoint_invalid"
        assert job.last_error_detail is None
        assert target_index and target_index.state is IndexVersionState.FAILED
        assert (
            session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.index_version_id == target_id)
            )
            == 0
        )
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1


def test_parse_worker_terminal_parse_failure_does_not_enqueue_or_retry(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 19, 12, tzinfo=UTC)
    raw = b"# parse failure boundary\n"
    storage = MemoryObjectStorage()
    adapter = HashEmbeddingAdapter(dimension=8)

    def fail_parse(*_args: object, **_kwargs: object) -> ParsedDocument:
        raise worker_module.WorkerPublicError("parse_document_invalid")

    monkeypatch.setattr(worker_module, "_parse_uploaded_document", fail_parse)
    with factory.begin() as session:
        user, kb, _ = target(session, "terminal-parse-failure")
        uploaded = upload_prepared_knowledge_document(
            session,
            user,
            kb.id,
            PreparedUpload(
                source_name="broken.md",
                content_type="text/markdown",
                content_sha256=hashlib.sha256(raw).hexdigest(),
                temporary_file=BytesIO(raw),
            ),
            "terminal-parse-failure",
            storage,
        )
        uploaded.job.available_at = now
        uploaded.job.max_attempts = 1
        job_id = uploaded.job.id
        version_id = uploaded.version.id

    assert run_worker_once(
        factory,
        {IngestionJobKind.PARSE_DOCUMENT: make_parse_document_handler(storage, adapter)},
        config=WorkerConfig(worker_id="terminal-parse-worker", retry_delay=timedelta(0)),
        now=now,
    )

    with factory() as session:
        job = session.get(IngestionJob, job_id)
        version = session.get(DocumentVersion, version_id)
        assert job and job.state is IngestionJobState.FAILED
        assert job.attempt_count == 1
        assert job.last_error_code == "parse_document_invalid"
        assert job.last_error_detail is None
        assert version and version.state is DocumentVersionState.FAILED
        assert session.scalar(select(func.count()).select_from(Page)) == 0
        assert session.scalar(select(func.count()).select_from(Block)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.kind == IngestionJobKind.BUILD_INDEX)
            )
            == 0
        )


def test_complete_job_lease_loss_preserves_replacement_owner_status_and_result(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "worker-lease-loss.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 8, 19, 12, tzinfo=UTC)
    replacement_now = now + timedelta(minutes=6)
    replacement_expiry = replacement_now + timedelta(minutes=10)
    try:
        with factory.begin() as session:
            user, kb, index = target(session, "complete-lease-loss")
            job = add_job(session, user, kb, index, now=now)
            claimed = claim_next_job(
                session,
                worker_id="original-worker",
                now=now,
                lease_duration=timedelta(minutes=5),
            )
            assert claimed and claimed.id == job.id
            job_id = job.id

        with factory.begin() as replacement:
            claimed = claim_next_job(
                replacement,
                worker_id="replacement-worker",
                now=replacement_now,
                lease_duration=timedelta(minutes=10),
            )
            assert claimed and claimed.id == job_id
            claimed.checkpoint = {"replacement_result": "preserve"}
            claimed.completed_at = None
            claimed.last_error_code = "replacement_error"
            claimed.last_error_detail = "replacement detail"

        with factory.begin() as stale_worker:
            with pytest.raises(RuntimeError, match="^worker_lease_lost$"):
                complete_job(
                    stale_worker,
                    job_id=job_id,
                    worker_id="original-worker",
                    now=replacement_now,
                )

        with factory() as session:
            persisted = session.get(IngestionJob, job_id)
            assert persisted and persisted.state is IngestionJobState.RUNNING
            assert persisted.lease_owner == "replacement-worker"
            assert persisted.lease_expires_at == replacement_expiry.replace(tzinfo=None)
            assert persisted.completed_at is None
            assert persisted.last_error_code == "replacement_error"
            assert persisted.last_error_detail == "replacement detail"
            assert persisted.checkpoint == {"replacement_result": "preserve"}
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_fail_job_lease_loss_preserves_replacement_owner_status_and_result(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "worker-lease-loss-failure.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 8, 19, 12, tzinfo=UTC)
    replacement_now = now + timedelta(minutes=6)
    replacement_expiry = replacement_now + timedelta(minutes=10)
    try:
        with factory.begin() as session:
            user, kb, index = target(session, "failure-lease-loss")
            job = add_job(session, user, kb, index, now=now)
            claimed = claim_next_job(
                session,
                worker_id="original-worker",
                now=now,
                lease_duration=timedelta(minutes=5),
            )
            assert claimed and claimed.id == job.id
            job_id = job.id

        with factory.begin() as replacement:
            claimed = claim_next_job(
                replacement,
                worker_id="replacement-worker",
                now=replacement_now,
                lease_duration=timedelta(minutes=10),
            )
            assert claimed and claimed.id == job_id
            claimed.checkpoint = {"replacement_result": "preserve"}
            claimed.completed_at = None
            claimed.last_error_code = "replacement_error"
            claimed.last_error_detail = "replacement detail"

        with factory.begin() as stale_worker:
            with pytest.raises(RuntimeError, match="^worker_lease_lost$"):
                fail_job(
                    stale_worker,
                    job_id=job_id,
                    worker_id="original-worker",
                    error=worker_module.WorkerPublicError("original_worker_failed"),
                    retry_delay=timedelta(0),
                    now=replacement_now,
                )

        with factory() as session:
            persisted = session.get(IngestionJob, job_id)
            assert persisted and persisted.state is IngestionJobState.RUNNING
            assert persisted.lease_owner == "replacement-worker"
            assert persisted.lease_expires_at == replacement_expiry.replace(tzinfo=None)
            assert persisted.completed_at is None
            assert persisted.last_error_code == "replacement_error"
            assert persisted.last_error_detail == "replacement detail"
            assert persisted.checkpoint == {"replacement_result": "preserve"}
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_worker_main_injects_real_formula_evidence_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tutor_api import worker_main
    from tutor_api.core.config import Settings

    sentinel = object()
    captured: dict[str, object] = {}
    original = worker_main.make_markdown_draft_handler

    def capture(adapter, **kwargs):
        captured.update(kwargs)
        return original(adapter, **kwargs)

    monkeypatch.setattr(worker_main, "WikipediaFormulaEvidenceProvider", lambda: sentinel)
    monkeypatch.setattr(worker_main, "make_markdown_draft_handler", capture)

    worker_main.create_handlers(
        Settings(
            app_env="test",
            embedding_dimension=8,
            agent_mcp_config_paths=(),
            agent_skill_paths=(),
        )
    )

    assert captured["formula_evidence_provider"] is sentinel


def test_durable_logical_job_dispatches_through_existing_lease_queue(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 1, tzinfo=UTC)
    handled: list[str] = []
    with factory.begin() as session:
        user, kb, index = target(session, "durable-dispatch")
        job = add_job(session, user, kb, index, now=now)
        job.checkpoint["worker_job_kind"] = DurableJobKind.SEMANTIC_PLAN.value
        job_id = job.id

    assert run_worker_once(
        factory,
        {DurableJobKind.SEMANTIC_PLAN: lambda session, job: handled.append(str(job.id))},
        config=WorkerConfig(worker_id="durable-worker"),
        now=now,
    )

    with factory() as session:
        persisted = session.get(IngestionJob, job_id)
        assert persisted is not None and persisted.state is IngestionJobState.COMPLETED
        assert persisted.completed_at.replace(tzinfo=UTC) == now
    assert handled == [str(job_id)]


def test_durable_logical_job_retries_then_dead_letters(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 2, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "durable-dead-letter")
        job = add_job(session, user, kb, index, now=now, maximum=2)
        job.checkpoint["worker_job_kind"] = DurableJobKind.VAULT_PROJECT.value
        job_id = job.id

    def fail_projection(session: Session, job: IngestionJob) -> None:
        del session, job
        raise worker_module.WorkerPublicError("vault_projection_failed")

    handlers = {DurableJobKind.VAULT_PROJECT: fail_projection}
    config = WorkerConfig(worker_id="durable-worker", retry_delay=timedelta(0))
    assert run_worker_once(factory, handlers, config=config, now=now)
    with factory() as session:
        first = session.get(IngestionJob, job_id)
        assert first is not None and first.state is IngestionJobState.RETRY_WAIT
        assert first.attempt_count == 1
        assert first.available_at.replace(tzinfo=UTC) == now

    assert run_worker_once(factory, handlers, config=config, now=now + timedelta(seconds=1))
    with factory() as session:
        terminal = session.get(IngestionJob, job_id)
        assert terminal is not None and terminal.state is IngestionJobState.FAILED
        assert terminal.attempt_count == 2
        assert terminal.last_error_code == "vault_projection_failed"
        assert terminal.completed_at.replace(tzinfo=UTC) == now + timedelta(seconds=1)
        target_index = session.get(IndexVersion, index.id)
        assert target_index is not None and target_index.state is IndexVersionState.BUILDING



def test_run_worker_once_uses_supplied_time_for_terminal_target_failure(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 2, 30, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "terminal-clock")
        job = add_job(session, user, kb, index, now=now, maximum=1)
        job_id = job.id
        index_id = index.id

    def fail_build(session: Session, job: IngestionJob) -> None:
        del session, job
        raise worker_module.WorkerPublicError("index_build_failed")

    assert run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: fail_build},
        config=WorkerConfig(worker_id="terminal-clock-worker"),
        now=now,
    )

    with factory() as session:
        persisted = session.get(IngestionJob, job_id)
        target_index = session.get(IndexVersion, index_id)
        assert persisted is not None and persisted.completed_at is not None
        assert persisted.completed_at.replace(tzinfo=UTC) == now
        assert target_index is not None and target_index.completed_at is not None
        assert target_index.completed_at.replace(tzinfo=UTC) == now


def test_failed_vault_scan_persists_recovery_cursor_after_handler_rollback(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 29, 2, 45, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "scan-failure-cursor")
        root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
        root.mkdir(parents=True)
        job = add_job(session, user, kb, index, now=now, maximum=1)
        job.checkpoint["worker_job_kind"] = DurableJobKind.VAULT_SCAN.value
        job_id = job.id
        kb_id = kb.id

    def fail_snapshot(service: object) -> object:
        del service
        raise OSError("private filesystem detail")

    monkeypatch.setattr(worker_module.VaultSyncService, "_disk_snapshot", fail_snapshot)
    assert run_worker_once(
        factory,
        {DurableJobKind.VAULT_SCAN: make_vault_scan_handler(tmp_path)},
        config=WorkerConfig(worker_id="scan-failure-worker"),
        now=now,
    )

    with factory() as session:
        persisted = session.get(IngestionJob, job_id)
        cursor = session.scalar(
            select(VaultSyncCursor).where(VaultSyncCursor.knowledge_base_id == kb_id)
        )
        assert persisted is not None and persisted.state is IngestionJobState.FAILED
        assert cursor is not None and cursor.requires_full_scan is True
        assert cursor.pending_count >= 1
        assert cursor.last_error == "worker_unhandled_error"


def test_terminal_vault_project_failure_marks_change_set_failed(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 2, 50, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "project-failure-state")
        change_set = VaultChangeSet(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            source=VaultChangeSource.EXTERNAL_EDITOR,
            state=VaultChangeSetState.COMMITTED,
            after_snapshot_hash="a" * 64,
            committed_at=now,
        )
        session.add(change_set)
        session.flush()
        job = add_job(session, user, kb, index, now=now, maximum=1)
        job.checkpoint.update(
            worker_job_kind=DurableJobKind.VAULT_PROJECT.value,
            change_set_id=str(change_set.id),
        )
        change_set_id = change_set.id

    def fail_projection(session: Session, job: IngestionJob) -> None:
        del session, job
        raise worker_module.WorkerPublicError("vault_projection_failed")

    assert run_worker_once(
        factory,
        {DurableJobKind.VAULT_PROJECT: fail_projection},
        config=WorkerConfig(worker_id="project-failure-worker"),
        now=now,
    )

    with factory() as session:
        persisted = session.get(VaultChangeSet, change_set_id)
        assert persisted is not None and persisted.state is VaultChangeSetState.FAILED
        assert persisted.failure_code == "vault_projection_failed"
        assert persisted.failure_message is None


def test_durable_logical_job_recovers_stale_lease_after_restart(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 3, tzinfo=UTC)
    handled: list[str] = []
    with factory.begin() as session:
        user, kb, index = target(session, "durable-restart")
        job = add_job(
            session,
            user,
            kb,
            index,
            now=now - timedelta(minutes=10),
            state=IngestionJobState.RUNNING,
            attempts=1,
            owner="dead-worker",
            expires=now - timedelta(seconds=1),
            started=now - timedelta(minutes=10),
        )
        job.checkpoint["worker_job_kind"] = DurableJobKind.VAULT_SCAN.value
        job_id = job.id

    assert run_worker_once(
        factory,
        {DurableJobKind.VAULT_SCAN: lambda session, job: handled.append(str(job.id))},
        config=WorkerConfig(worker_id="replacement-worker"),
        now=now,
    )
    with factory() as session:
        persisted = session.get(IngestionJob, job_id)
        assert persisted is not None and persisted.state is IngestionJobState.COMPLETED
        assert persisted.attempt_count == 2
    assert handled == [str(job_id)]


def test_worker_exposes_vault_and_semantic_handler_factories() -> None:
    assert callable(make_vault_scan_handler)
    assert callable(make_vault_project_handler)
    assert callable(make_semantic_plan_handler)


def test_worker_main_registers_durable_vault_and_semantic_handlers() -> None:
    from tutor_api import worker_main
    from tutor_api.core.config import Settings

    handlers = worker_main.create_handlers(
        Settings(
            app_env="test",
            embedding_dimension=8,
            agent_mcp_config_paths=(),
            agent_skill_paths=(),
        )
    )

    assert DurableJobKind.VAULT_SCAN in handlers
    assert DurableJobKind.VAULT_PROJECT in handlers
    assert DurableJobKind.SEMANTIC_PLAN in handlers


def test_logical_worker_does_not_claim_plain_build_transport(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 4, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "logical-filter")
        job = add_job(session, user, kb, index, now=now)
        job_id = job.id

    assert not run_worker_once(
        factory,
        {DurableJobKind.VAULT_SCAN: lambda session, job: None},
        config=WorkerConfig(worker_id="logical-filter-worker"),
        now=now,
    )
    with factory() as session:
        persisted = session.get(IngestionJob, job_id)
        assert persisted is not None and persisted.state is IngestionJobState.QUEUED
        assert persisted.attempt_count == 0


def test_plain_build_worker_does_not_claim_logical_transport(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 5, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "plain-filter")
        job = add_job(session, user, kb, index, now=now)
        job.checkpoint["worker_job_kind"] = DurableJobKind.VAULT_SCAN.value
        job_id = job.id

    assert not run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: lambda session, job: None},
        config=WorkerConfig(worker_id="plain-filter-worker"),
        now=now,
    )
    with factory() as session:
        persisted = session.get(IngestionJob, job_id)
        assert persisted is not None and persisted.state is IngestionJobState.QUEUED
        assert persisted.attempt_count == 0


def test_vault_scan_handler_resumes_cursor_and_is_idempotent(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    now = datetime(2026, 8, 29, 6, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "vault-scan-handler")
        root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
        root.mkdir(parents=True)
        (root / "external.md").write_text("# External", encoding="utf-8")
        job = add_job(session, user, kb, index, now=now)
        job.checkpoint.update(
            worker_job_kind=DurableJobKind.VAULT_SCAN.value,
            force_full_scan=True,
        )
        handler = make_vault_scan_handler(tmp_path)
        handler(session, job)
        assert job.checkpoint["change_count"] == 1

        (root / "after-restart.md").write_text("# Restart", encoding="utf-8")
        job.checkpoint["force_full_scan"] = False
        handler(session, job)
        assert job.checkpoint["change_count"] == 1

        handler(session, job)
        assert job.checkpoint["change_count"] == 0
        assert job.checkpoint["cursor"]
        assert (
            session.scalar(
                select(func.count(VaultFile.id)).where(VaultFile.knowledge_base_id == kb.id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count(VaultChangeSet.id)).where(
                    VaultChangeSet.knowledge_base_id == kb.id
                )
            )
            == 2
        )


def test_vault_project_handler_is_idempotent(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    now = datetime(2026, 8, 29, 7, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "vault-project-handler")
        root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
        root.mkdir(parents=True)
        (root / "project.md").write_text("# Project", encoding="utf-8")
        scan_job = add_job(session, user, kb, index, now=now)
        scan_job.checkpoint["worker_job_kind"] = DurableJobKind.VAULT_SCAN.value
        make_vault_scan_handler(tmp_path)(session, scan_job)
        change_set_id = scan_job.checkpoint["change_set_id"]

        project_job = add_job(session, user, kb, index, now=now)
        project_job.checkpoint.update(
            worker_job_kind=DurableJobKind.VAULT_PROJECT.value,
            change_set_id=change_set_id,
            document_version_ids=[str(uuid4())],
            parser_signature=index.parser_signature,
            ocr_signature=index.ocr_signature,
            chunk_max_chars=1200,
            chunk_overlap_chars=120,
        )
        handler = make_vault_project_handler(tmp_path)
        handler(session, project_job)
        assert project_job.checkpoint["projected_count"] == 1
        handler(session, project_job)
        assert project_job.checkpoint["projected_count"] == 0
        assert project_job.checkpoint["projected_change_set_id"] == change_set_id


def test_semantic_plan_handler_reads_vault_and_persists_result(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 29, 8, tzinfo=UTC)
    adapter = HashEmbeddingAdapter(dimension=8)

    class Planner:
        provider = "test"
        model = "planner"

        def generate(self, *, prompt: str, source_text: str, source_hash: str) -> object:
            raise AssertionError("semantic worker was stubbed")

    captured: dict[str, object] = {}

    def fake_run(session: Session, **kwargs):
        del session
        captured.update(kwargs)
        return worker_module.SemanticIndexJobResult(
            state=worker_module.SemanticJobState.ACTIVE,
            index_version_id=kwargs["request"].knowledge_base_id,
            semantic_plan_id=kwargs["vault_file_id"],
            reused_plan=True,
        )

    monkeypatch.setattr(worker_module, "run_semantic_index_job", fake_run)
    with factory.begin() as session:
        user, kb, index = target(session, "semantic-handler")
        root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
        root.mkdir(parents=True)
        source = "# Semantic\n\nSource body"
        path = root / "semantic.md"
        path.write_text(source, encoding="utf-8")
        vault_file = VaultFile(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            relative_path="semantic.md",
            file_kind=VaultFileKind.MARKDOWN,
            content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            size_bytes=len(path.read_bytes()),
        )
        session.add(vault_file)
        session.flush()
        job = add_job(session, user, kb, index, now=now)
        job.checkpoint.update(
            worker_job_kind=DurableJobKind.SEMANTIC_PLAN.value,
            vault_file_id=str(vault_file.id),
            document_version_ids=[str(uuid4())],
            parser_signature="tutor:parser:v1:" + "a" * 64,
            ocr_signature="tutor:ocr:v1:" + "b" * 64,
            chunk_max_chars=1200,
            chunk_overlap_chars=120,
            source_snapshot_hash=vault_file.content_hash,
        )
        handler = make_semantic_plan_handler(
            adapter,
            Planner(),
            vault_root=tmp_path,
            sidecar_root=tmp_path / "sidecars",
        )
        handler(session, job)

        request = captured["request"]
        assert captured["source_text"] == path.read_bytes().decode("utf-8")
        assert request.space_id == kb.space_id
        assert request.knowledge_base_id == kb.id
        assert request.source_snapshot_hash == vault_file.content_hash
        assert job.checkpoint["semantic_state"] == "active"
        assert job.checkpoint["semantic_plan_id"] == str(vault_file.id)
        assert job.checkpoint["semantic_reused_plan"] is True

        snapshot_hash = job.checkpoint.pop("source_snapshot_hash")
        with pytest.raises(worker_module.WorkerPublicError) as missing_hash:
            handler(session, job)
        assert missing_hash.value.code == "semantic_job_checkpoint_invalid"

        job.checkpoint["source_snapshot_hash"] = snapshot_hash
        path.write_text("changed after scheduling", encoding="utf-8")
        with pytest.raises(worker_module.WorkerPublicError) as stale_source:
            handler(session, job)
        assert stale_source.value.code == "semantic_source_stale"


def test_faro_semantic_planner_reports_invalid_json_with_stable_code() -> None:
    from tutor_api.worker_main import FaroSemanticPlanner

    class Adapter:
        def complete_markdown(self, source_text: str):
            del source_text
            return type("Completion", (), {"text": "not-json"})()

    planner = FaroSemanticPlanner(Adapter(), model="test-model")
    with pytest.raises(IndexingError) as captured:
        planner.generate(prompt="plan", source_text="source", source_hash="a" * 64)
    assert captured.value.code == "semantic_plan_invalid"



def test_vault_handlers_enqueue_project_and_semantic_jobs_idempotently(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    now = datetime(2026, 8, 29, 9, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "vault-handler-chain")
        index.chunking_signature = ChunkingConfig().signature
        document = Document(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            title="Chain source",
            source_kind="upload",
            source_key="chain.md",
            state=DocumentState.ACTIVE,
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            document_id=document.id,
            version_number=1,
            content_sha256="c" * 64,
            object_key="objects/chain",
            content_type="text/markdown",
            state=DocumentVersionState.READY,
            created_by_user_id=user.id,
        )
        session.add(version)
        root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
        root.mkdir(parents=True)
        (root / "chain.md").write_text("# Chain", encoding="utf-8")
        scan_job = add_job(session, user, kb, index, now=now)
        scan_job.checkpoint["worker_job_kind"] = DurableJobKind.VAULT_SCAN.value

        scan_handler = make_vault_scan_handler(tmp_path)
        scan_handler(session, scan_job)
        scan_handler(session, scan_job)
        change_set_id = scan_job.checkpoint["change_set_id"]
        project_jobs = list(
            session.scalars(
                select(IngestionJob).where(
                    IngestionJob.knowledge_base_id == kb.id,
                    IngestionJob.idempotency_key == f"vault-project:{change_set_id}",
                )
            )
        )
        assert len(project_jobs) == 1

        project_handler = make_vault_project_handler(tmp_path)
        project_handler(session, project_jobs[0])
        project_handler(session, project_jobs[0])
        semantic_jobs = list(
            session.scalars(
                select(IngestionJob).where(
                    IngestionJob.knowledge_base_id == kb.id,
                    IngestionJob.checkpoint["worker_job_kind"].as_string()
                    == DurableJobKind.SEMANTIC_PLAN.value,
                )
            )
        )
        assert len(semantic_jobs) == 1
        semantic = semantic_jobs[0]
        assert semantic.checkpoint["source_change_set_id"] == change_set_id
        assert semantic.checkpoint["source_snapshot_hash"]
        assert semantic.checkpoint["vault_file_id"]
        assert semantic.checkpoint["document_version_ids"] == [str(version.id)]


def test_semantic_handler_validates_change_set_scope_snapshot_and_relative_source(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 29, 10, tzinfo=UTC)
    adapter = HashEmbeddingAdapter(dimension=8)

    class Planner:
        provider = "test"
        model = "planner"

        def generate(self, *, prompt: str, source_text: str, source_hash: str) -> object:
            raise AssertionError("semantic worker was stubbed")

    monkeypatch.setattr(
        worker_module,
        "run_semantic_index_job",
        lambda session, **kwargs: worker_module.SemanticIndexJobResult(
            state=worker_module.SemanticJobState.ACTIVE,
            index_version_id=kwargs["request"].knowledge_base_id,
            semantic_plan_id=kwargs["vault_file_id"],
            reused_plan=False,
        ),
    )
    with factory.begin() as session:
        user, kb, index = target(session, "semantic-change-set-validation")
        root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
        root.mkdir(parents=True)
        path = root / "semantic.md"
        path.write_text("# Semantic", encoding="utf-8")
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        vault_file = VaultFile(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            relative_path="semantic.md",
            file_kind=VaultFileKind.MARKDOWN,
            content_hash=source_hash,
            size_bytes=len(path.read_bytes()),
        )
        session.add(vault_file)
        session.flush()
        change_set = VaultChangeSet(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            source=VaultChangeSource.EXTERNAL_EDITOR,
            state=VaultChangeSetState.INDEXING,
            after_snapshot_hash=source_hash,
            committed_at=now,
        )
        session.add(change_set)
        session.flush()
        vault_file.last_change_set_id = change_set.id
        entry = VaultChangeEntry(
            change_set_id=change_set.id,
            vault_file_id=vault_file.id,
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            ordinal=0,
            operation=VaultChangeOperation.UPDATE,
            after_path=vault_file.relative_path,
            after_hash=vault_file.content_hash,
            size_delta_bytes=0,
        )
        session.add(entry)
        session.flush()
        job = add_job(session, user, kb, index, now=now)
        job.checkpoint.update(
            worker_job_kind=DurableJobKind.SEMANTIC_PLAN.value,
            vault_file_id=str(vault_file.id),
            document_version_ids=[str(uuid4())],
            parser_signature=index.parser_signature,
            ocr_signature=index.ocr_signature,
            chunk_max_chars=1200,
            chunk_overlap_chars=120,
            source_snapshot_hash=source_hash,
            source_change_set_id=str(change_set.id),
            semantic_job_ids=[str(job.id)],
            semantic_vault_file_ids=[str(vault_file.id)],
        )
        handler = make_semantic_plan_handler(
            adapter,
            Planner(),
            vault_root=tmp_path,
            sidecar_root=tmp_path / "sidecars",
        )
        handler(session, job)

        change_set.after_snapshot_hash = "b" * 64
        with pytest.raises(worker_module.WorkerPublicError) as snapshot_mismatch:
            handler(session, job)
        assert snapshot_mismatch.value.code == "semantic_change_set_snapshot_mismatch"

        change_set.after_snapshot_hash = source_hash
        entry.after_path = "other.md"
        with pytest.raises(worker_module.WorkerPublicError) as source_mismatch:
            handler(session, job)
        assert source_mismatch.value.code == "semantic_change_set_source_invalid"


def test_semantic_handler_rejects_foreign_knowledge_base_change_set(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    now = datetime(2026, 8, 29, 11, tzinfo=UTC)
    adapter = HashEmbeddingAdapter(dimension=8)

    class Planner:
        provider = "test"
        model = "planner"

        def generate(self, *, prompt: str, source_text: str, source_hash: str) -> object:
            raise AssertionError("must fail before provider")

    with factory.begin() as session:
        user, kb, index = target(session, "semantic-local")
        foreign_user, foreign_kb, _ = target(session, "semantic-foreign")
        del foreign_user
        root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
        root.mkdir(parents=True)
        path = root / "semantic.md"
        path.write_text("# Semantic", encoding="utf-8")
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        vault_file = VaultFile(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            relative_path="semantic.md",
            file_kind=VaultFileKind.MARKDOWN,
            content_hash=source_hash,
            size_bytes=len(path.read_bytes()),
        )
        session.add(vault_file)
        foreign_change_set = VaultChangeSet(
            space_id=foreign_kb.space_id,
            knowledge_base_id=foreign_kb.id,
            source=VaultChangeSource.API,
            state=VaultChangeSetState.COMMITTED,
            after_snapshot_hash=source_hash,
            committed_at=now,
        )
        session.add(foreign_change_set)
        session.flush()
        job = add_job(session, user, kb, index, now=now)
        job.checkpoint.update(
            worker_job_kind=DurableJobKind.SEMANTIC_PLAN.value,
            vault_file_id=str(vault_file.id),
            document_version_ids=[str(uuid4())],
            parser_signature=index.parser_signature,
            ocr_signature=index.ocr_signature,
            chunk_max_chars=1200,
            chunk_overlap_chars=120,
            source_snapshot_hash=source_hash,
            source_change_set_id=str(foreign_change_set.id),
        )
        handler = make_semantic_plan_handler(
            adapter,
            Planner(),
            vault_root=tmp_path,
            sidecar_root=tmp_path / "sidecars",
        )
        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, job)
        assert captured.value.code == "semantic_change_set_invalid"



def test_unknown_logical_job_kind_retries_then_dead_letters(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 13, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "unknown-logical-kind")
        job = add_job(session, user, kb, index, now=now, maximum=2)
        job.checkpoint["worker_job_kind"] = "future_workspace_job"
        job_id = job.id

    handlers = {DurableJobKind.VAULT_SCAN: lambda session, job: None}
    config = WorkerConfig(worker_id="unknown-logical-worker", retry_delay=timedelta(0))

    assert run_worker_once(factory, handlers, config=config, now=now)
    with factory() as session:
        retried = session.get(IngestionJob, job_id)
        assert retried is not None and retried.state is IngestionJobState.RETRY_WAIT
        assert retried.attempt_count == 1
        assert retried.last_error_code == "worker_job_kind_invalid"

    terminal_at = now + timedelta(seconds=1)
    assert run_worker_once(factory, handlers, config=config, now=terminal_at)
    with factory() as session:
        terminal = session.get(IngestionJob, job_id)
        assert terminal is not None and terminal.state is IngestionJobState.FAILED
        assert terminal.attempt_count == 2
        assert terminal.last_error_code == "worker_job_kind_invalid"
        assert terminal.completed_at.replace(tzinfo=UTC) == terminal_at


def test_unknown_logical_job_kind_recovers_stale_lease_and_dead_letters(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 13, 10, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "unknown-logical-stale")
        job = add_job(
            session,
            user,
            kb,
            index,
            now=now - timedelta(minutes=5),
            state=IngestionJobState.RUNNING,
            attempts=1,
            maximum=2,
            owner="lost-worker",
            expires=now - timedelta(seconds=1),
            started=now - timedelta(minutes=5),
        )
        job.checkpoint["worker_job_kind"] = "future_workspace_job"
        job_id = job.id

    assert run_worker_once(
        factory,
        {DurableJobKind.VAULT_PROJECT: lambda session, job: None},
        config=WorkerConfig(worker_id="replacement-worker"),
        now=now,
    )
    with factory() as session:
        terminal = session.get(IngestionJob, job_id)
        assert terminal is not None and terminal.state is IngestionJobState.FAILED
        assert terminal.attempt_count == 2
        assert terminal.last_error_code == "worker_job_kind_invalid"
        assert terminal.completed_at.replace(tzinfo=UTC) == now


def test_unknown_logical_job_kind_terminalizes_exhausted_stale_lease(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 13, 20, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "unknown-logical-exhausted")
        job = add_job(
            session,
            user,
            kb,
            index,
            now=now - timedelta(minutes=5),
            state=IngestionJobState.RUNNING,
            attempts=2,
            maximum=2,
            owner="lost-worker",
            expires=now - timedelta(seconds=1),
            started=now - timedelta(minutes=5),
        )
        job.checkpoint["worker_job_kind"] = "future_workspace_job"
        job_id = job.id

    assert not run_worker_once(
        factory,
        {DurableJobKind.SEMANTIC_PLAN: lambda session, job: None},
        config=WorkerConfig(worker_id="replacement-worker"),
        now=now,
    )
    with factory() as session:
        terminal = session.get(IngestionJob, job_id)
        assert terminal is not None and terminal.state is IngestionJobState.FAILED
        assert terminal.last_error_code == "worker_lease_exhausted"
        assert terminal.completed_at.replace(tzinfo=UTC) == now


@pytest.mark.parametrize("missing_contract", ["chunking", "ready-version"])
def test_project_job_retries_then_fails_when_semantic_contract_is_missing(
    factory: sessionmaker[Session], tmp_path: Path, missing_contract: str
) -> None:
    now = datetime(2026, 8, 29, 13, 30, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, f"missing-contract-{missing_contract}")
        if missing_contract == "ready-version":
            index.chunking_signature = ChunkingConfig().signature
        root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
        root.mkdir(parents=True)
        path = root / "source.md"
        path.write_text("# Missing semantic contract", encoding="utf-8")
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        vault_file = VaultFile(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            relative_path="source.md",
            file_kind=VaultFileKind.MARKDOWN,
            content_hash=source_hash,
            size_bytes=len(path.read_bytes()),
        )
        session.add(vault_file)
        change_set = VaultChangeSet(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            source=VaultChangeSource.EXTERNAL_EDITOR,
            state=VaultChangeSetState.COMMITTED,
            after_snapshot_hash=source_hash,
            committed_at=now,
        )
        session.add(change_set)
        session.flush()
        vault_file.last_change_set_id = change_set.id
        session.add(
            VaultChangeEntry(
                change_set_id=change_set.id,
                vault_file_id=vault_file.id,
                space_id=kb.space_id,
                knowledge_base_id=kb.id,
                ordinal=0,
                operation=VaultChangeOperation.CREATE,
                after_path=vault_file.relative_path,
                after_hash=vault_file.content_hash,
                size_delta_bytes=vault_file.size_bytes,
            )
        )
        job = add_job(session, user, kb, index, now=now, maximum=2)
        job.checkpoint.update(
            worker_job_kind=DurableJobKind.VAULT_PROJECT.value,
            change_set_id=str(change_set.id),
        )
        job_id = job.id
        change_set_id = change_set.id

    handlers = {DurableJobKind.VAULT_PROJECT: make_vault_project_handler(tmp_path)}
    config = WorkerConfig(worker_id="missing-contract-worker", retry_delay=timedelta(0))
    assert run_worker_once(factory, handlers, config=config, now=now)
    with factory() as session:
        retried = session.get(IngestionJob, job_id)
        persisted = session.get(VaultChangeSet, change_set_id)
        assert retried is not None and retried.state is IngestionJobState.RETRY_WAIT
        assert retried.last_error_code == "semantic_contract_unavailable"
        assert persisted is not None and persisted.state is VaultChangeSetState.COMMITTED

    terminal_at = now + timedelta(seconds=1)
    assert run_worker_once(factory, handlers, config=config, now=terminal_at)
    with factory() as session:
        terminal = session.get(IngestionJob, job_id)
        persisted = session.get(VaultChangeSet, change_set_id)
        assert terminal is not None and terminal.state is IngestionJobState.FAILED
        assert terminal.last_error_code == "semantic_contract_unavailable"
        assert persisted is not None and persisted.state is VaultChangeSetState.FAILED
        assert persisted.failure_code == "semantic_contract_unavailable"



def test_missing_semantic_index_target_is_an_explicit_contract_error(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 29, 13, 50, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "missing-contract-target")
        job = add_job(session, user, kb, index, now=now)
        change_set = VaultChangeSet(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            source=VaultChangeSource.EXTERNAL_EDITOR,
            state=VaultChangeSetState.INDEXING,
            after_snapshot_hash="a" * 64,
            committed_at=now,
        )
        session.add(change_set)
        session.flush()
        vault_file = VaultFile(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            relative_path="eligible.md",
            file_kind=VaultFileKind.MARKDOWN,
            content_hash="b" * 64,
            size_bytes=1,
        )
        session.add(vault_file)
        session.flush()
        vault_file.last_change_set_id = change_set.id
        session.add(
            VaultChangeEntry(
                change_set_id=change_set.id,
                vault_file_id=vault_file.id,
                space_id=kb.space_id,
                knowledge_base_id=kb.id,
                ordinal=0,
                operation=VaultChangeOperation.CREATE,
                after_path=vault_file.relative_path,
                after_hash=vault_file.content_hash,
                size_delta_bytes=1,
            )
        )
        session.flush()
        original_target = job.index_version_id
        job.index_version_id = uuid4()
        with session.no_autoflush:
            with pytest.raises(worker_module.WorkerPublicError) as captured:
                worker_module._enqueue_semantic_jobs(
                    session, parent=job, change_set=change_set
                )
        job.index_version_id = original_target
        assert captured.value.code == "semantic_contract_unavailable"


def test_worker_stderr_redacts_exception_message_traceback_and_absolute_paths(
    factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 8, 29, 14, tzinfo=UTC)
    secret_path = r"C:\Users\alice\private-vault\lesson.md"
    with factory.begin() as session:
        user, kb, index = target(session, "stderr-redaction")
        add_job(session, user, kb, index, now=now, maximum=1)

    def fail_with_sensitive_path(session: Session, job: IngestionJob) -> None:
        del session, job
        raise RuntimeError(f"could not read {secret_path}")

    assert run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: fail_with_sensitive_path},
        config=WorkerConfig(worker_id="stderr-redaction-worker"),
        now=now,
    )
    stderr = capsys.readouterr().err
    assert "code=worker_unhandled_error" in stderr
    assert "type=RuntimeError" in stderr
    assert "could not read" not in stderr
    assert "alice" not in stderr
    assert "private-vault" not in stderr
    assert secret_path not in stderr
    assert "Traceback" not in stderr


def test_run_worker_once_propagates_one_clock_through_vault_and_semantic_success(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    scan_at = datetime(2026, 8, 29, 14, 10, tzinfo=UTC)
    project_at = scan_at + timedelta(minutes=1)
    semantic_at = scan_at + timedelta(minutes=2)
    with factory.begin() as session:
        adapter, _, _, scan_job, version = real_build_target(
            session, suffix="worker-clock-chain", now=scan_at
        )
        kb = session.get(KnowledgeBase, scan_job.knowledge_base_id)
        assert kb is not None
        root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
        root.mkdir(parents=True)
        source = "# Worker clock\n\nSemantic source."
        path = root / "clock.md"
        path.write_text(source, encoding="utf-8")
        scan_job.checkpoint = {"worker_job_kind": DurableJobKind.VAULT_SCAN.value}
        scan_job_id = scan_job.id

    assert run_worker_once(
        factory,
        {DurableJobKind.VAULT_SCAN: make_vault_scan_handler(tmp_path)},
        config=WorkerConfig(worker_id="clock-scan-worker"),
        now=scan_at,
    )
    with factory() as session:
        persisted_scan = session.get(IngestionJob, scan_job_id)
        assert persisted_scan is not None
        change_set_id = UUID(persisted_scan.checkpoint["change_set_id"])
        change_set = session.get(VaultChangeSet, change_set_id)
        assert change_set is not None and change_set.committed_at is not None
        assert change_set.committed_at.replace(tzinfo=UTC) == scan_at
        project_job = session.scalar(
            select(IngestionJob).where(
                IngestionJob.checkpoint["worker_job_kind"].as_string()
                == DurableJobKind.VAULT_PROJECT.value
            )
        )
        assert project_job is not None
        project_job_id = project_job.id

    assert run_worker_once(
        factory,
        {DurableJobKind.VAULT_PROJECT: make_vault_project_handler(tmp_path)},
        config=WorkerConfig(worker_id="clock-project-worker"),
        now=project_at,
    )
    with factory() as session:
        project_job = session.get(IngestionJob, project_job_id)
        assert project_job is not None and project_job.state is IngestionJobState.COMPLETED
        change_set = session.get(VaultChangeSet, change_set_id)
        assert change_set is not None and change_set.state is VaultChangeSetState.INDEXING
        cursor = session.scalar(
            select(VaultSyncCursor).where(
                VaultSyncCursor.knowledge_base_id == change_set.knowledge_base_id,
                VaultSyncCursor.space_id == change_set.space_id,
            )
        )
        assert cursor is not None and cursor.last_success_at is not None
        assert cursor.last_success_at.replace(tzinfo=UTC) == project_at
        semantic_job = session.scalar(
            select(IngestionJob).where(
                IngestionJob.checkpoint["worker_job_kind"].as_string()
                == DurableJobKind.SEMANTIC_PLAN.value
            )
        )
        assert semantic_job is not None
        assert semantic_job.checkpoint["document_version_ids"] == [str(version.id)]
        semantic_job_id = semantic_job.id

    class Planner:
        provider = "clock-test"
        model = "clock-test"

        def generate(self, *, prompt: str, source_text: str, source_hash: str) -> object:
            assert prompt and source_text
            return {
                "schema_version": "1.0",
                "source_hash": source_hash,
                "chunks": [],
                "concepts": [],
                "terms": [],
                "links": [],
            }

    assert run_worker_once(
        factory,
        {
            DurableJobKind.SEMANTIC_PLAN: make_semantic_plan_handler(
                adapter,
                Planner(),
                vault_root=tmp_path,
                sidecar_root=tmp_path / "sidecars",
            )
        },
        config=WorkerConfig(worker_id="clock-semantic-worker"),
        now=semantic_at,
    )
    with factory() as session:
        semantic_job = session.get(IngestionJob, semantic_job_id)
        assert semantic_job is not None and semantic_job.state is IngestionJobState.COMPLETED
        semantic_index = session.get(
            IndexVersion, UUID(semantic_job.checkpoint["semantic_index_version_id"])
        )
        assert semantic_index is not None and semantic_index.completed_at is not None
        assert semantic_index.activated_at is not None
        assert semantic_index.completed_at.replace(tzinfo=UTC) == semantic_at
        assert semantic_index.activated_at.replace(tzinfo=UTC) == semantic_at
        change_set = session.get(VaultChangeSet, change_set_id)
        assert change_set is not None and change_set.indexed_at is not None
        assert change_set.state is VaultChangeSetState.INDEXED
        assert change_set.indexed_at.replace(tzinfo=UTC) == semantic_at
        cursor = session.scalar(
            select(VaultSyncCursor).where(
                VaultSyncCursor.knowledge_base_id == change_set.knowledge_base_id,
                VaultSyncCursor.space_id == change_set.space_id,
            )
        )
        assert cursor is not None and cursor.last_success_at is not None
        assert cursor.last_success_at.replace(tzinfo=UTC) == semantic_at



def _seed_semantic_chain(
    session: Session,
    tmp_path: Path,
    *,
    suffix: str,
    files: tuple[tuple[str, VaultFileKind, bool, bool], ...],
    maximum: int = 3,
) -> tuple[KnowledgeBase, IngestionJob, VaultChangeSet, dict[str, VaultFile]]:
    now = datetime(2026, 8, 29, 15, tzinfo=UTC)
    user, kb, index = target(session, suffix)
    index.chunking_signature = ChunkingConfig().signature
    document = Document(
        space_id=kb.space_id,
        knowledge_base_id=kb.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title=f"{suffix} contract",
        source_kind="upload",
        source_key=f"{suffix}-contract.md",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=kb.space_id,
        knowledge_base_id=kb.id,
        document_id=document.id,
        version_number=1,
        content_sha256=hashlib.sha256(suffix.encode()).hexdigest(),
        object_key=f"objects/{suffix}-contract",
        content_type="text/markdown",
        state=DocumentVersionState.READY,
        created_by_user_id=user.id,
    )
    session.add(version)
    change_set = VaultChangeSet(
        space_id=kb.space_id,
        knowledge_base_id=kb.id,
        source=VaultChangeSource.EXTERNAL_EDITOR,
        state=VaultChangeSetState.COMMITTED,
        after_snapshot_hash=hashlib.sha256(f"snapshot:{suffix}".encode()).hexdigest(),
        committed_at=now,
    )
    session.add(change_set)
    session.flush()
    root = tmp_path / "spaces" / str(kb.space_id) / str(kb.id)
    root.mkdir(parents=True, exist_ok=True)
    vault_files: dict[str, VaultFile] = {}
    for ordinal, (relative_path, file_kind, tombstoned, entry_matches) in enumerate(files):
        payload = f"# {relative_path}\n\nSemantic source {ordinal}.\n".encode()
        content_hash = hashlib.sha256(payload).hexdigest()
        if not tombstoned:
            target_path = root / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(payload)
        vault_file = VaultFile(
            space_id=kb.space_id,
            knowledge_base_id=kb.id,
            relative_path=relative_path,
            file_kind=file_kind,
            content_hash=content_hash,
            size_bytes=len(payload),
            is_tombstoned=tombstoned,
            tombstoned_at=now if tombstoned else None,
            last_change_set_id=change_set.id,
        )
        session.add(vault_file)
        session.flush()
        vault_files[relative_path] = vault_file
        session.add(
            VaultChangeEntry(
                change_set_id=change_set.id,
                vault_file_id=vault_file.id,
                space_id=kb.space_id,
                knowledge_base_id=kb.id,
                ordinal=ordinal,
                operation=(
                    VaultChangeOperation.DELETE
                    if tombstoned
                    else VaultChangeOperation.CREATE
                ),
                before_path=relative_path if tombstoned else None,
                after_path=(relative_path if not tombstoned and entry_matches else None),
                before_hash=content_hash if tombstoned else None,
                after_hash=(content_hash if not tombstoned and entry_matches else None),
                size_delta_bytes=-len(payload) if tombstoned else len(payload),
            )
        )
    parent = add_job(session, user, kb, index, now=now, maximum=maximum)
    parent.checkpoint = {
        "worker_job_kind": DurableJobKind.VAULT_PROJECT.value,
        "change_set_id": str(change_set.id),
        "document_version_ids": [str(version.id)],
        "parser_signature": index.parser_signature,
        "ocr_signature": index.ocr_signature,
        "chunk_max_chars": ChunkingConfig().max_chars,
        "chunk_overlap_chars": ChunkingConfig().overlap_chars,
    }
    session.flush()
    return kb, parent, change_set, vault_files


class _ActiveSemanticPlanner:
    provider = "semantic-chain-test"
    model = "semantic-chain-test"

    def generate(self, *, prompt: str, source_text: str, source_hash: str) -> object:
        raise AssertionError("semantic worker is stubbed in semantic-chain tests")


def _active_semantic_result(**kwargs: object) -> worker_module.SemanticIndexJobResult:
    request = kwargs["request"]
    vault_file_id = kwargs["vault_file_id"]
    return worker_module.SemanticIndexJobResult(
        state=worker_module.SemanticJobState.ACTIVE,
        index_version_id=request.knowledge_base_id,
        semantic_plan_id=vault_file_id,
        reused_plan=False,
    )


def _semantic_jobs_in_checkpoint_order(
    session: Session, parent: IngestionJob
) -> tuple[IngestionJob, ...]:
    jobs: list[IngestionJob] = []
    for raw_job_id in parent.checkpoint["semantic_job_ids"]:
        job = session.get(IngestionJob, UUID(raw_job_id))
        assert job is not None
        jobs.append(job)
    return tuple(jobs)


@pytest.mark.parametrize("corruption", ("duplicate", "missing"))
def test_semantic_finalizer_rejects_duplicate_or_missing_expected_vault_file(
    factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    now = datetime(2026, 8, 29, 15, 5, tzinfo=UTC)
    monkeypatch.setattr(
        worker_module,
        "run_semantic_index_job",
        lambda session, **kwargs: _active_semantic_result(**kwargs),
    )
    handler = make_semantic_plan_handler(
        HashEmbeddingAdapter(dimension=8),
        _ActiveSemanticPlanner(),
        vault_root=tmp_path,
        sidecar_root=tmp_path / "sidecars",
    )

    with factory.begin() as session:
        _, parent, change_set, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix=f"semantic-invalid-coverage-{corruption}",
            files=(
                ("alpha.md", VaultFileKind.MARKDOWN, False, True),
                ("beta.md", VaultFileKind.MARKDOWN, False, True),
            ),
        )
        make_vault_project_handler(tmp_path)(session, parent)
        current, sibling = _semantic_jobs_in_checkpoint_order(session, parent)
        sibling.state = IngestionJobState.COMPLETED
        sibling.started_at = now
        sibling.completed_at = now
        sibling.checkpoint = {
            **sibling.checkpoint,
            "vault_file_id": (
                current.checkpoint["vault_file_id"]
                if corruption == "duplicate"
                else str(uuid4())
            ),
        }

        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, current)

        assert captured.value.code == "semantic_job_checkpoint_invalid"
        assert change_set.state is VaultChangeSetState.INDEXING
        assert change_set.indexed_at is None


def test_semantic_finalizer_rejects_omitted_eligible_vault_file(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        worker_module,
        "run_semantic_index_job",
        lambda session, **kwargs: _active_semantic_result(**kwargs),
    )
    handler = make_semantic_plan_handler(
        HashEmbeddingAdapter(dimension=8),
        _ActiveSemanticPlanner(),
        vault_root=tmp_path,
        sidecar_root=tmp_path / "sidecars",
    )

    with factory.begin() as session:
        _, parent, change_set, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix="semantic-omitted-eligible-file",
            files=(
                ("alpha.md", VaultFileKind.MARKDOWN, False, True),
                ("beta.md", VaultFileKind.MARKDOWN, False, True),
            ),
        )
        make_vault_project_handler(tmp_path)(session, parent)
        current = _semantic_jobs_in_checkpoint_order(session, parent)[0]
        current.checkpoint = {
            **current.checkpoint,
            "semantic_job_ids": [str(current.id)],
            "semantic_vault_file_ids": [current.checkpoint["vault_file_id"]],
        }

        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, current)

        assert captured.value.code == "semantic_job_checkpoint_invalid"
        assert change_set.state is VaultChangeSetState.INDEXING
        assert change_set.indexed_at is None


def test_project_rerun_rejects_child_vault_file_sequence_mismatch(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with factory.begin() as session:
        _, parent, _, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix="semantic-child-vault-mismatch",
            files=(
                ("alpha.md", VaultFileKind.MARKDOWN, False, True),
                ("beta.md", VaultFileKind.MARKDOWN, False, True),
            ),
        )
        handler = make_vault_project_handler(tmp_path)
        handler(session, parent)
        child = _semantic_jobs_in_checkpoint_order(session, parent)[0]
        child.checkpoint = {
            **child.checkpoint,
            "semantic_vault_file_ids": list(
                reversed(child.checkpoint["semantic_vault_file_ids"])
            ),
        }

        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, parent)

        assert captured.value.code == "semantic_job_checkpoint_invalid"


def test_project_rerun_rejects_semantic_job_and_vault_file_count_mismatch(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with factory.begin() as session:
        _, parent, _, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix="semantic-checkpoint-count-mismatch",
            files=(
                ("alpha.md", VaultFileKind.MARKDOWN, False, True),
                ("beta.md", VaultFileKind.MARKDOWN, False, True),
            ),
        )
        handler = make_vault_project_handler(tmp_path)
        handler(session, parent)
        parent.checkpoint = {
            **parent.checkpoint,
            "semantic_vault_file_ids": parent.checkpoint["semantic_vault_file_ids"][:1],
        }

        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, parent)

        assert captured.value.code == "semantic_job_checkpoint_invalid"


def test_project_rerun_rejects_missing_semantic_expectation_after_enqueue(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with factory.begin() as session:
        kb, parent, _, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix="semantic-missing-parent-expectation",
            files=(("alpha.md", VaultFileKind.MARKDOWN, False, True),),
        )
        handler = make_vault_project_handler(tmp_path)
        handler(session, parent)
        child = _semantic_jobs_in_checkpoint_order(session, parent)[0]
        original_child_id = child.id
        parent.checkpoint = {
            key: value
            for key, value in parent.checkpoint.items()
            if key
            not in (
                "semantic_job_ids",
                "semantic_vault_file_ids",
                "semantic_expectation_initialized",
            )
        }
        child.checkpoint = {
            key: value
            for key, value in child.checkpoint.items()
            if key not in ("semantic_job_ids", "semantic_vault_file_ids")
        }

        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, parent)

        assert captured.value.code == "semantic_job_checkpoint_invalid"
        semantic_job_ids = tuple(
            session.scalars(
                select(IngestionJob.id).where(
                    IngestionJob.knowledge_base_id == kb.id,
                    IngestionJob.checkpoint["worker_job_kind"].as_string()
                    == DurableJobKind.SEMANTIC_PLAN.value,
                )
            )
        )
        assert semantic_job_ids == (original_child_id,)


def test_project_rerun_rejects_missing_parent_expectation_when_child_kind_is_missing(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with factory.begin() as session:
        _, parent, _, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix="semantic-missing-parent-and-child-kind",
            files=(("alpha.md", VaultFileKind.MARKDOWN, False, True),),
        )
        handler = make_vault_project_handler(tmp_path)
        handler(session, parent)
        child = _semantic_jobs_in_checkpoint_order(session, parent)[0]
        parent.checkpoint = {
            key: value
            for key, value in parent.checkpoint.items()
            if key
            not in (
                "semantic_job_ids",
                "semantic_vault_file_ids",
                "semantic_expectation_initialized",
            )
        }
        child.checkpoint = {
            key: value for key, value in child.checkpoint.items() if key != "worker_job_kind"
        }

        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, parent)

        assert captured.value.code == "semantic_job_checkpoint_invalid"


def test_project_rerun_rejects_missing_parent_expectation_when_child_source_changes(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with factory.begin() as session:
        _, parent, _, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix="semantic-missing-parent-and-child-source",
            files=(("alpha.md", VaultFileKind.MARKDOWN, False, True),),
        )
        handler = make_vault_project_handler(tmp_path)
        handler(session, parent)
        child = _semantic_jobs_in_checkpoint_order(session, parent)[0]
        parent.checkpoint = {
            key: value
            for key, value in parent.checkpoint.items()
            if key
            not in (
                "semantic_job_ids",
                "semantic_vault_file_ids",
                "semantic_expectation_initialized",
            )
        }
        child.checkpoint = {
            **child.checkpoint,
            "source_change_set_id": str(uuid4()),
        }

        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, parent)

        assert captured.value.code == "semantic_job_checkpoint_invalid"


@pytest.mark.parametrize(
    "corruption",
    (
        "scope",
        "transport_kind",
        "logical_kind",
        "source_change_set",
        "vault_file",
        "checkpoint_contract",
    ),
)
def test_enqueue_durable_job_rejects_existing_semantic_contract_corruption(
    factory: sessionmaker[Session], tmp_path: Path, corruption: str
) -> None:
    with factory() as session:
        _, parent, _, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix=f"semantic-existing-contract-{corruption}",
            files=(("alpha.md", VaultFileKind.MARKDOWN, False, True),),
        )
        make_vault_project_handler(tmp_path)(session, parent)
        child = _semantic_jobs_in_checkpoint_order(session, parent)[0]
        expected_checkpoint = {
            key: child.checkpoint[key]
            for key in (
                "document_version_ids",
                "parser_signature",
                "ocr_signature",
                "chunk_max_chars",
                "chunk_overlap_chars",
                "vault_file_id",
                "source_change_set_id",
                "source_snapshot_hash",
            )
        }
        if corruption == "scope":
            child.space_id = uuid4()
        elif corruption == "transport_kind":
            child.kind = IngestionJobKind.PARSE_DOCUMENT
        elif corruption == "logical_kind":
            child.checkpoint = {
                **child.checkpoint,
                "worker_job_kind": DurableJobKind.VAULT_PROJECT.value,
            }
        elif corruption == "source_change_set":
            child.checkpoint = {
                **child.checkpoint,
                "source_change_set_id": str(uuid4()),
            }
        elif corruption == "vault_file":
            child.checkpoint = {
                **child.checkpoint,
                "vault_file_id": str(uuid4()),
            }
        else:
            child.checkpoint = {
                **child.checkpoint,
                "parser_signature": "damaged-parser-contract",
            }

        with (
            session.no_autoflush,
            pytest.raises(worker_module.WorkerPublicError) as captured,
        ):
            worker_module._enqueue_durable_job(
                session,
                parent=parent,
                logical_kind=DurableJobKind.SEMANTIC_PLAN,
                idempotency_key=child.idempotency_key,
                checkpoint=expected_checkpoint,
            )

        assert captured.value.code == "semantic_job_checkpoint_invalid"


def test_zero_semantic_job_project_rerun_rejects_missing_expectation_without_drift(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with factory.begin() as session:
        _, parent, change_set, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix="semantic-zero-missing-parent-expectation",
            files=(("deleted.md", VaultFileKind.MARKDOWN, True, False),),
        )
        handler = make_vault_project_handler(tmp_path)
        handler(session, parent)
        first_indexed_at = change_set.indexed_at
        assert first_indexed_at is not None
        parent.checkpoint = {
            key: value
            for key, value in parent.checkpoint.items()
            if key not in ("semantic_job_ids", "semantic_vault_file_ids")
        }

        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, parent)

        assert captured.value.code == "semantic_job_checkpoint_invalid"
        assert change_set.state is VaultChangeSetState.INDEXED
        assert change_set.indexed_at == first_indexed_at


@pytest.mark.parametrize(
    "damaged_vault_ids",
    (
        lambda values: [values[0], values[0]],
        lambda values: [values[0], "not-a-uuid"],
    ),
    ids=("duplicate", "malformed"),
)
def test_project_rerun_rejects_damaged_semantic_vault_file_collection(
    factory: sessionmaker[Session], tmp_path: Path, damaged_vault_ids
) -> None:
    with factory.begin() as session:
        _, parent, _, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix=f"semantic-damaged-vault-collection-{uuid4()}",
            files=(
                ("alpha.md", VaultFileKind.MARKDOWN, False, True),
                ("beta.md", VaultFileKind.MARKDOWN, False, True),
            ),
        )
        handler = make_vault_project_handler(tmp_path)
        handler(session, parent)
        parent.checkpoint = {
            **parent.checkpoint,
            "semantic_vault_file_ids": damaged_vault_ids(
                parent.checkpoint["semantic_vault_file_ids"]
            ),
        }

        with pytest.raises(worker_module.WorkerPublicError) as captured:
            handler(session, parent)

        assert captured.value.code == "semantic_job_checkpoint_invalid"


def test_multi_file_change_set_waits_for_every_semantic_job(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 29, 15, 10, tzinfo=UTC)
    with factory.begin() as session:
        kb, parent, change_set, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix="semantic-multi",
            files=(
                ("alpha.md", VaultFileKind.MARKDOWN, False, True),
                ("beta.md", VaultFileKind.MARKDOWN, False, True),
            ),
        )
        make_vault_project_handler(tmp_path)(session, parent)
        semantic_jobs = tuple(
            session.scalars(
                select(IngestionJob).where(
                    IngestionJob.knowledge_base_id == kb.id,
                    IngestionJob.checkpoint["worker_job_kind"].as_string()
                    == DurableJobKind.SEMANTIC_PLAN.value,
                )
            )
        )
        expected_job_ids = parent.checkpoint["semantic_job_ids"]
        assert len(expected_job_ids) == 2
        assert {str(semantic_job.id) for semantic_job in semantic_jobs} == set(
            expected_job_ids
        )
        assert all(
            semantic_job.checkpoint["semantic_job_ids"] == expected_job_ids
            for semantic_job in semantic_jobs
        )
        expected_vault_file_ids = parent.checkpoint["semantic_vault_file_ids"]
        assert all(
            semantic_job.checkpoint["semantic_vault_file_ids"]
            == expected_vault_file_ids
            for semantic_job in semantic_jobs
        )
        change_set_id = change_set.id
        kb_id = kb.id
    monkeypatch.setattr(
        worker_module,
        "run_semantic_index_job",
        lambda session, **kwargs: _active_semantic_result(**kwargs),
    )
    handler = make_semantic_plan_handler(
        HashEmbeddingAdapter(dimension=8),
        _ActiveSemanticPlanner(),
        vault_root=tmp_path,
        sidecar_root=tmp_path / "sidecars",
    )
    config = WorkerConfig(worker_id="semantic-multi-worker")

    assert run_worker_once(
        factory,
        {DurableJobKind.SEMANTIC_PLAN: handler},
        config=config,
        now=now,
    )
    with factory() as session:
        states = list(
            session.scalars(
                select(IngestionJob.state)
                .where(
                    IngestionJob.knowledge_base_id == kb_id,
                    IngestionJob.checkpoint["worker_job_kind"].as_string()
                    == DurableJobKind.SEMANTIC_PLAN.value,
                )
                .order_by(IngestionJob.id)
            )
        )
        persisted = session.get(VaultChangeSet, change_set_id)
        assert sorted(states) == [IngestionJobState.COMPLETED, IngestionJobState.QUEUED]
        assert persisted is not None and persisted.state is VaultChangeSetState.INDEXING
        assert persisted.indexed_at is None

    assert run_worker_once(
        factory,
        {DurableJobKind.SEMANTIC_PLAN: handler},
        config=config,
        now=now + timedelta(seconds=1),
    )
    with factory() as session:
        persisted = session.get(VaultChangeSet, change_set_id)
        assert persisted is not None and persisted.state is VaultChangeSetState.INDEXED
        assert persisted.indexed_at is not None


@pytest.mark.parametrize(
    ("case_name", "files"),
    (
        (
            "deletion-only",
            (("deleted.md", VaultFileKind.MARKDOWN, True, False),),
        ),
        (
            "tombstone-only",
            (
                ("first.md", VaultFileKind.MARKDOWN, True, False),
                ("second.md", VaultFileKind.MARKDOWN, True, False),
            ),
        ),
        (
            "non-markdown-only",
            (("attachment.bin", VaultFileKind.ATTACHMENT, False, True),),
        ),
        (
            "no-eligible-entry",
            (("stale.md", VaultFileKind.MARKDOWN, False, False),),
        ),
    ),
)
def test_zero_semantic_job_change_sets_finish_indexed_idempotently(
    factory: sessionmaker[Session],
    tmp_path: Path,
    case_name: str,
    files: tuple[tuple[str, VaultFileKind, bool, bool], ...],
) -> None:
    with factory.begin() as session:
        kb, parent, change_set, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix=f"semantic-zero-{case_name}",
            files=files,
        )
        handler = make_vault_project_handler(tmp_path)
        handler(session, parent)
        first_indexed_at = change_set.indexed_at
        handler(session, parent)
        assert change_set.indexed_at == first_indexed_at
        semantic_job_count = session.scalar(
            select(func.count())
            .select_from(IngestionJob)
            .where(
                IngestionJob.knowledge_base_id == kb.id,
                IngestionJob.checkpoint["worker_job_kind"].as_string()
                == DurableJobKind.SEMANTIC_PLAN.value,
            )
        )
        assert semantic_job_count == 0
        assert change_set.state is VaultChangeSetState.INDEXED
        assert change_set.indexed_at is not None
        assert parent.checkpoint["semantic_job_ids"] == []


def test_successful_semantic_sibling_does_not_overwrite_failed_change_set(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 29, 15, 20, tzinfo=UTC)
    with factory.begin() as session:
        _, parent, change_set, _ = _seed_semantic_chain(
            session,
            tmp_path,
            suffix="semantic-failed-sibling",
            files=(
                ("alpha.md", VaultFileKind.MARKDOWN, False, True),
                ("beta.md", VaultFileKind.MARKDOWN, False, True),
            ),
        )
        make_vault_project_handler(tmp_path)(session, parent)
        jobs = list(
            session.scalars(
                select(IngestionJob)
                .where(
                    IngestionJob.checkpoint["worker_job_kind"].as_string()
                    == DurableJobKind.SEMANTIC_PLAN.value
                )
                .order_by(IngestionJob.id)
            )
        )
        change_set_id = change_set.id
        sibling_id = jobs[1].id

    def finish_after_sibling_failure(session: Session, **kwargs: object):
        sibling = session.get(IngestionJob, sibling_id)
        persisted = session.get(VaultChangeSet, change_set_id)
        assert sibling is not None and persisted is not None
        sibling.state = IngestionJobState.FAILED
        sibling.started_at = sibling.started_at or now
        sibling.completed_at = now
        sibling.last_error_code = "semantic_sibling_failed"
        persisted.state = VaultChangeSetState.FAILED
        persisted.failure_code = "semantic_sibling_failed"
        return _active_semantic_result(**kwargs)

    monkeypatch.setattr(worker_module, "run_semantic_index_job", finish_after_sibling_failure)
    handler = make_semantic_plan_handler(
        HashEmbeddingAdapter(dimension=8),
        _ActiveSemanticPlanner(),
        vault_root=tmp_path,
        sidecar_root=tmp_path / "sidecars",
    )
    assert run_worker_once(
        factory,
        {DurableJobKind.SEMANTIC_PLAN: handler},
        config=WorkerConfig(worker_id="semantic-failed-sibling-worker"),
        now=now,
    )
    with factory() as session:
        persisted = session.get(VaultChangeSet, change_set_id)
        assert persisted is not None and persisted.state is VaultChangeSetState.FAILED
        assert persisted.failure_code == "semantic_sibling_failed"
        assert persisted.indexed_at is None


def test_concurrent_semantic_completion_keeps_indexing_until_last_worker_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "semantic-concurrency.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 20},
        poolclass=NullPool,
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    slow_started = Event()
    release_slow = Event()
    errors: Queue[BaseException] = Queue()
    now = datetime(2026, 8, 29, 15, 30, tzinfo=UTC)
    try:
        with factory.begin() as session:
            _, parent, change_set, vault_files = _seed_semantic_chain(
                session,
                tmp_path,
                suffix="semantic-concurrent",
                files=(
                    ("fast.md", VaultFileKind.MARKDOWN, False, True),
                    ("slow.md", VaultFileKind.MARKDOWN, False, True),
                ),
            )
            make_vault_project_handler(tmp_path)(session, parent)
            semantic_jobs = list(
                session.scalars(
                    select(IngestionJob).where(
                        IngestionJob.checkpoint["worker_job_kind"].as_string()
                        == DurableJobKind.SEMANTIC_PLAN.value
                    )
                )
            )
            jobs_by_file = {
                UUID(job.checkpoint["vault_file_id"]): job for job in semantic_jobs
            }
            fast_job = jobs_by_file[vault_files["fast.md"].id]
            slow_job = jobs_by_file[vault_files["slow.md"].id]
            for owner, job in (("fast-owner", fast_job), ("slow-owner", slow_job)):
                job.state = IngestionJobState.RUNNING
                job.attempt_count = 1
                job.started_at = now
                job.lease_owner = owner
                job.lease_expires_at = now + timedelta(minutes=5)
            fast_job_id = fast_job.id
            slow_job_id = slow_job.id
            change_set_id = change_set.id

        def concurrent_result(**kwargs: object):
            if kwargs["vault_file_id"] == vault_files["slow.md"].id:
                slow_started.set()
                assert release_slow.wait(timeout=10)
            else:
                assert slow_started.wait(timeout=10)
            return _active_semantic_result(**kwargs)

        monkeypatch.setattr(
            worker_module,
            "run_semantic_index_job",
            lambda session, **kwargs: concurrent_result(**kwargs),
        )
        handler = make_semantic_plan_handler(
            HashEmbeddingAdapter(dimension=8),
            _ActiveSemanticPlanner(),
            vault_root=tmp_path,
            sidecar_root=tmp_path / "sidecars",
        )

        def execute(job_id: UUID, owner: str) -> None:
            try:
                with factory.begin() as session:
                    job = session.get(IngestionJob, job_id)
                    assert job is not None
                    handler(session, job)
                    complete_job(session, job_id=job.id, worker_id=owner, now=now)
            except BaseException as error:  # noqa: BLE001 - thread boundary capture
                errors.put(error)

        slow_thread = Thread(target=execute, args=(slow_job_id, "slow-owner"), daemon=True)
        fast_thread = Thread(target=execute, args=(fast_job_id, "fast-owner"), daemon=True)
        slow_thread.start()
        assert slow_started.wait(timeout=10)
        fast_thread.start()
        fast_thread.join(timeout=10)
        assert not fast_thread.is_alive()
        assert errors.empty(), list(errors.queue)
        with factory() as session:
            persisted = session.get(VaultChangeSet, change_set_id)
            assert persisted is not None and persisted.state is VaultChangeSetState.INDEXING
            assert persisted.indexed_at is None

        release_slow.set()
        slow_thread.join(timeout=10)
        assert not slow_thread.is_alive()
        assert errors.empty(), list(errors.queue)
        with factory() as session:
            persisted = session.get(VaultChangeSet, change_set_id)
            states = list(
                session.scalars(
                    select(IngestionJob.state).where(
                        IngestionJob.id.in_((fast_job_id, slow_job_id))
                    )
                )
            )
            assert persisted is not None and persisted.state is VaultChangeSetState.INDEXED
            assert persisted.indexed_at is not None
            assert states == [IngestionJobState.COMPLETED, IngestionJobState.COMPLETED]
    finally:
        release_slow.set()
        Base.metadata.drop_all(engine)
        engine.dispose()
