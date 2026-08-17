import binascii
import hashlib
import struct
import zlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.embeddings import HashEmbeddingAdapter
from tutor_api.knowledge.indexing import ChunkingConfig
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
from tutor_api.knowledge.parsers import parse_markdown
from tutor_api.knowledge.service import (
    PreparedUpload,
    persist_parsed_document_and_enqueue_build,
    upload_prepared_knowledge_document,
)
from tutor_api.knowledge.storage import MemoryObjectStorage
from tutor_api.knowledge.worker import (
    WorkerConfig,
    claim_job_statement,
    claim_next_job,
    complete_job,
    fail_job,
    make_build_index_handler,
    make_parse_document_handler,
    run_worker_once,
)
from tutor_api.spaces.models import Space, SpaceKind


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
def test_worker_main_registers_parse_and_build_handlers() -> None:
    from tutor_api.core.config import Settings
    from tutor_api.worker_main import create_handlers

    handlers = create_handlers(Settings(app_env="test", embedding_dimension=8))
    assert set(handlers) == {
        IngestionJobKind.PARSE_DOCUMENT,
        IngestionJobKind.BUILD_INDEX,
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
        assert session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.index_version_id == target_id)
        ) == 0


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
        assert completed_old_job.index_version_id == old_target_id
        assert completed_old_job.idempotency_key == old_job_key
        assert failed_old_target and failed_old_target.state is IndexVersionState.FAILED
        assert preserved_active and preserved_active.state is IndexVersionState.ACTIVE
        assert session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.index_version_id == old_target_id)
        ) == 0
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
        assert session.scalar(
            select(func.count()).select_from(IngestionJob).where(
                IngestionJob.kind == IngestionJobKind.BUILD_INDEX
            )
        ) == 2

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
        assert claim_next_job(
            session,
            worker_id="replacement",
            now=now,
            kinds=(IngestionJobKind.BUILD_INDEX, IngestionJobKind.PARSE_DOCUMENT),
        ) is None

    with factory() as session:
        failed_target = session.get(IndexVersion, target_id)
        untouched = session.get(IndexVersion, unrelated_id)
        stale_parse = session.get(IngestionJob, parse_job_id)
        stale_version = session.get(DocumentVersion, version.id)
        assert failed_target and failed_target.state is IndexVersionState.FAILED
        assert untouched and untouched.state is IndexVersionState.BUILDING
        assert stale_parse and stale_parse.state is IngestionJobState.FAILED
        assert stale_version and stale_version.state is DocumentVersionState.FAILED
        assert session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.index_version_id == target_id)
        ) == 0


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
