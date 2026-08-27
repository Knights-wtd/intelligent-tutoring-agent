import struct
from collections.abc import Generator
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.embeddings import HashEmbeddingAdapter, is_embedding_blank
from tutor_api.knowledge.indexing import (
    MAX_LEXICAL_TERMS,
    ChunkingConfig,
    IndexBuildRequest,
    IndexingError,
    _embedding_values_match_with_pgvector_precision,
    build_index,
    chunk_source_blocks,
    content_sha256,
    make_index_signature,
    make_pipeline_signature,
    normalize_lexical_terms,
    prepare_index_build,
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
from tutor_api.knowledge.storage import MemoryObjectStorage
from tutor_api.spaces.models import Space, SpaceKind


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


class CountingEmbedding:
    backend = "hash"
    model = "feature-hash-v1"
    dimension = 8
    signature = "hash:feature-hash-v1:8"

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_on = fail_on
        self.delegate = HashEmbeddingAdapter(dimension=8)

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("provider secret traceback")
        return self.delegate.embed(text)


def graph(session: Session, suffix: str = "one") -> tuple[User, Space, KnowledgeBase]:
    user = User(email=f"{suffix}@example.com", username=f"user-{suffix}", password_hash="h")
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name=f"Space {suffix}")
    session.add(space)
    session.flush()
    kb = KnowledgeBase(
        space_id=space.id, owner_user_id=user.id, created_by_user_id=user.id, name=f"KB {suffix}"
    )
    session.add(kb)
    session.flush()
    return user, space, kb


def add_version(
    session: Session,
    user: User,
    space: Space,
    kb: KnowledgeBase,
    suffix: str,
    blocks: tuple[tuple[BlockKind, str], ...],
) -> DocumentVersion:
    document = Document(
        space_id=space.id,
        knowledge_base_id=kb.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title=suffix,
        source_kind="upload",
        source_key=f"{suffix}.md",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=kb.id,
        document_id=document.id,
        version_number=1,
        content_sha256=content_sha256("\n".join(x[1] for x in blocks)),
        object_key=f"objects/{suffix}",
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
        source_pointer=f"{suffix}.md#page=1",
        content_sha256=version.content_sha256,
        source_metadata={},
    )
    session.add(page)
    session.flush()
    for ordinal, (kind, text) in enumerate(blocks):
        session.add(
            Block(
                space_id=space.id,
                page_id=page.id,
                ordinal=ordinal,
                kind=kind,
                source_pointer=f"{suffix}.md#block={ordinal}",
                content_sha256=content_sha256(text),
                text=text,
            )
        )
    session.flush()
    return version


def request(
    user: User, space: Space, kb: KnowledgeBase, versions: tuple[UUID, ...]
) -> IndexBuildRequest:
    return IndexBuildRequest(
        space_id=space.id,
        knowledge_base_id=kb.id,
        created_by_user_id=user.id,
        document_version_ids=versions,
        parser_signature=make_pipeline_signature("parser", "native", "1"),
        ocr_signature=make_pipeline_signature("ocr", "disabled", "1"),
        chunking=ChunkingConfig(max_chars=80, overlap_chars=16),
    )


def test_heading_aware_chunks_keep_context_and_bound_overlap() -> None:
    chunks = chunk_source_blocks(
        (
            (1, 0, "heading", "Algebra", "doc#h"),
            (1, 1, "paragraph", "".join(chr(0x4E00 + index) for index in range(240)), "doc#p"),
        ),
        ChunkingConfig(max_chars=90, overlap_chars=18),
    )
    assert len(chunks) > 1
    assert all(
        c.content and len(c.content) <= 90 and c.content.startswith("Algebra\n") for c in chunks
    )
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert len({c.source_pointer for c in chunks}) == len(chunks)
    for left, right in zip(chunks, chunks[1:], strict=False):
        a, b = left.content.removeprefix("Algebra\n"), right.content.removeprefix("Algebra\n")
        shared = max((n for n in range(min(len(a), len(b)) + 1) if a[-n:] == b[:n]), default=0)
        assert shared <= 18


@pytest.mark.parametrize(
    "maximum,overlap",
    [(True, 0), (0, 0), (20, False), (20, -1), (20, 20), (20, 21), (500000, 1)],
)
def test_chunking_bounds_fail_closed(maximum: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(max_chars=maximum, overlap_chars=overlap)


def test_signatures_are_stable_versioned_and_domain_separated() -> None:
    parser = make_pipeline_signature("parser", "native", "1")
    ocr = make_pipeline_signature("ocr", "native", "1")
    signature = make_index_signature(
        knowledge_base_id=UUID(int=1),
        document_sources=((UUID(int=2), "a" * 64), (UUID(int=3), "b" * 64)),
        parser_signature=parser,
        ocr_signature=ocr,
        chunking_signature="chunk:v1",
        embedding_signature="hash:feature-hash-v1:8",
    )
    moved_source = make_index_signature(
        knowledge_base_id=UUID(int=1),
        document_sources=((UUID(int=4), "a" * 64), (UUID(int=3), "b" * 64)),
        parser_signature=parser,
        ocr_signature=ocr,
        chunking_signature="chunk:v1",
        embedding_signature="hash:feature-hash-v1:8",
    )
    assert parser == make_pipeline_signature("parser", "native", "1")
    assert parser.startswith("tutor:parser:v1:") and parser != ocr
    assert signature.startswith("tutor:index:v1:") and len(signature.rsplit(":", 1)[1]) == 64
    assert moved_source != signature


def test_persisted_embedding_accepts_pgvector_float4_text_roundtrip() -> None:
    # PostgreSQL/pgvector can return float4 as text such as -0.15858996;
    # parsing that text yields a Python float64 distinct from the float4 canonical value.
    persisted = [float("-0.15858996")]
    expected = [-0.15858995914459229]

    assert _embedding_values_match_with_pgvector_precision(persisted, expected)


def test_persisted_embedding_rejects_signed_zero_float4_bit_pattern_mismatch() -> None:
    persisted = [struct.unpack("<f", struct.pack("<I", 0x80000000))[0]]
    expected = [struct.unpack("<f", struct.pack("<I", 0x00000000))[0]]

    assert persisted == expected
    assert struct.pack("<f", persisted[0]) != struct.pack("<f", expected[0])
    assert not _embedding_values_match_with_pgvector_precision(persisted, expected)


def test_persisted_embedding_accepts_values_in_the_same_float4_bin() -> None:
    assert _embedding_values_match_with_pgvector_precision([1.0], [1.0 + 2**-24])


def test_persisted_embedding_rejects_different_float4_values() -> None:
    assert not _embedding_values_match_with_pgvector_precision([1.0 + 2**-23], [1.0])


def test_persisted_embedding_rejects_two_ulp_cross_binade_error() -> None:
    expected = [1.9999998807907104]
    persisted = [2.000000238418579]

    assert not _embedding_values_match_with_pgvector_precision(persisted, expected)


@pytest.mark.parametrize(
    "persisted,expected",
    (
        ([], [0.0]),
        ([float("nan")], [float("nan")]),
        ([float("inf")], [float("inf")]),
        ([1e39], [1e39]),
    ),
)
def test_persisted_embedding_rejects_invalid_float4_inputs(
    persisted: list[float], expected: list[float]
) -> None:
    assert not _embedding_values_match_with_pgvector_precision(persisted, expected)


def test_build_persists_pointers_terms_hashes_and_embedding_contract(session: Session) -> None:
    user, space, kb = graph(session)
    version = add_version(
        session,
        user,
        space,
        kb,
        "math",
        (
            (BlockKind.TITLE, "Linear Algebra"),
            (BlockKind.PARAGRAPH, "Vectors, vectors; BASIS basis."),
        ),
    )
    embedding = CountingEmbedding()
    result = build_index(session, request(user, space, kb, (version.id,)), embedding)
    session.commit()
    index = session.get(IndexVersion, result.index_version_id)
    chunks = list(session.scalars(select(Chunk).order_by(Chunk.ordinal)))
    assert index and index.state is IndexVersionState.ACTIVE
    assert chunks and [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(
        c.page_id
        and c.block_id
        and c.source_pointer.startswith(f"document-version:{version.id}:")
        and "math.md#block=" in c.source_pointer
        for c in chunks
    )
    assert all(c.content_sha256 == content_sha256(c.content) for c in chunks)
    assert all(c.lexical_terms == sorted(set(c.lexical_terms)) for c in chunks)
    assert normalize_lexical_terms("Vectors, vectors; BASIS basis.") == ["basis", "vectors"]
    assert all(c.embedding_dimension == 8 and len(c.embedding) == 8 for c in chunks)


def test_hash_reuse_respects_embedding_contract(session: Session) -> None:
    user, space, kb = graph(session)
    first = add_version(
        session, user, space, kb, "first", ((BlockKind.PARAGRAPH, "same immutable content"),)
    )
    embedding = CountingEmbedding()
    build_index(session, request(user, space, kb, (first.id,)), embedding)
    session.commit()
    assert len(embedding.calls) == 1
    second = add_version(
        session, user, space, kb, "second", ((BlockKind.PARAGRAPH, "same immutable content"),)
    )
    embedding.calls.clear()
    build_index(session, request(user, space, kb, (first.id, second.id)), embedding)
    session.commit()
    assert embedding.calls == []
    rebuilt = build_index(
        session, request(user, space, kb, (first.id,)), HashEmbeddingAdapter(dimension=16)
    )
    session.commit()
    chunks = session.scalars(
        select(Chunk).where(Chunk.index_version_id == rebuilt.index_version_id)
    ).all()
    assert all(len(c.embedding) == 16 for c in chunks)


def test_signature_only_embedding_change_does_not_reuse_old_vectors(session: Session) -> None:
    class ContractEmbedding:
        backend = "hash"
        model = "feature-hash-v1"
        dimension = 8

        def __init__(self, signature: str, marker: float) -> None:
            self.signature = signature
            self.marker = marker
            self.calls: list[str] = []

        def embed(self, text: str) -> list[float]:
            self.calls.append(text)
            return [self.marker] + [0.0] * 7

    user, space, kb = graph(session, "signature-only")
    version = add_version(
        session,
        user,
        space,
        kb,
        "signature-only",
        ((BlockKind.PARAGRAPH, "signature contract body"),),
    )
    build_request = request(user, space, kb, (version.id,))
    first_adapter = ContractEmbedding("contract-v1", 1.0)
    first = build_index(session, build_request, first_adapter)
    session.commit()

    second_adapter = ContractEmbedding("contract-v2", 2.0)
    second = build_index(session, build_request, second_adapter)
    session.commit()

    first_index = session.get(IndexVersion, first.index_version_id)
    second_index = session.get(IndexVersion, second.index_version_id)
    second_chunk = session.scalar(
        select(Chunk).where(Chunk.index_version_id == second.index_version_id)
    )
    assert second.index_version_id != first.index_version_id
    assert second_adapter.calls == ["signature contract body"]
    assert first_index and second_index
    assert first_index.embedding_contract_signature != second_index.embedding_contract_signature
    assert second_chunk and second_chunk.embedding == [2.0] + [0.0] * 7


def test_index_signature_includes_full_embedding_contract(session: Session) -> None:
    class CollidingModelEmbedding(CountingEmbedding):
        model = "different-model"
        signature = CountingEmbedding.signature

    user, space, kb = graph(session, "embedding-contract")
    version = add_version(
        session, user, space, kb, "contract", ((BlockKind.PARAGRAPH, "contract body"),)
    )
    build_request = request(user, space, kb, (version.id,))
    first = build_index(session, build_request, CountingEmbedding())
    session.commit()

    colliding = CollidingModelEmbedding()
    second = build_index(session, build_request, colliding)
    session.commit()

    assert second.index_version_id != first.index_version_id
    assert colliding.calls == ["contract body"]
    assert session.get(IndexVersion, second.index_version_id).embedding_model == "different-model"


def test_failed_rebuild_preserves_active_and_has_no_partial_chunks(session: Session) -> None:
    user, space, kb = graph(session)
    first = add_version(
        session, user, space, kb, "stable", ((BlockKind.PARAGRAPH, "stable content"),)
    )
    active = build_index(session, request(user, space, kb, (first.id,)), CountingEmbedding())
    session.commit()
    failing = add_version(
        session, user, space, kb, "failing", ((BlockKind.PARAGRAPH, "explode embedding"),)
    )
    with pytest.raises(IndexingError):
        build_index(
            session, request(user, space, kb, (first.id, failing.id)), CountingEmbedding("explode")
        )
    session.commit()
    current = session.scalar(
        select(IndexVersion).where(IndexVersion.state == IndexVersionState.ACTIVE)
    )
    failed = session.scalar(
        select(IndexVersion).where(IndexVersion.state == IndexVersionState.FAILED)
    )
    assert current and current.id == active.index_version_id and failed and failed.id != current.id
    assert (
        session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.index_version_id == failed.id)
        )
        == 0
    )


def test_activation_rollback_is_atomic(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import tutor_api.knowledge.indexing as indexing

    user, space, kb = graph(session)
    first = add_version(session, user, space, kb, "active", ((BlockKind.PARAGRAPH, "active"),))
    active = build_index(session, request(user, space, kb, (first.id,)), CountingEmbedding())
    session.commit()
    second = add_version(session, user, space, kb, "new", ((BlockKind.PARAGRAPH, "new"),))
    original = indexing._activate_building_index

    def fail_after(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)
        raise RuntimeError("rollback")

    monkeypatch.setattr(indexing, "_activate_building_index", fail_after)
    with pytest.raises(IndexingError):
        build_index(session, request(user, space, kb, (first.id, second.id)), CountingEmbedding())
    session.commit()
    current = session.scalar(
        select(IndexVersion).where(IndexVersion.state == IndexVersionState.ACTIVE)
    )
    failed = session.scalar(
        select(IndexVersion).where(IndexVersion.state == IndexVersionState.FAILED)
    )
    assert current and current.id == active.index_version_id and failed
    assert (
        session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.index_version_id == failed.id)
        )
        == 0
    )


def test_idempotent_restart_reuses_version_without_duplicates(session: Session) -> None:
    user, space, kb = graph(session)
    version = add_version(
        session, user, space, kb, "restart", ((BlockKind.PARAGRAPH, "restart safe"),)
    )
    build_request = request(user, space, kb, (version.id,))
    embedding = CountingEmbedding()
    first = build_index(session, build_request, embedding)
    session.commit()
    counts = (
        session.scalar(select(func.count()).select_from(IndexVersion)),
        session.scalar(select(func.count()).select_from(Chunk)),
    )
    embedding.calls.clear()
    second = build_index(session, build_request, embedding)
    session.commit()
    assert (
        second.index_version_id == first.index_version_id
        and second.reused
        and embedding.calls == []
    )
    assert counts == (
        session.scalar(select(func.count()).select_from(IndexVersion)),
        session.scalar(select(func.count()).select_from(Chunk)),
    )


def test_late_older_target_completion_never_replaces_newer_active_index(session: Session) -> None:
    user, space, kb = graph(session, "late-target")
    first_version = add_version(
        session, user, space, kb, "first", ((BlockKind.PARAGRAPH, "first index"),)
    )
    first_request = request(user, space, kb, (first_version.id,))
    older = prepare_index_build(session, first_request, CountingEmbedding())
    session.commit()

    second_version = add_version(
        session, user, space, kb, "second", ((BlockKind.PARAGRAPH, "second index"),)
    )
    newer = build_index(
        session,
        request(user, space, kb, (first_version.id, second_version.id)),
        CountingEmbedding(),
    )
    session.commit()

    late = build_index(session, first_request, CountingEmbedding())
    session.commit()

    active = session.scalar(
        select(IndexVersion).where(IndexVersion.state == IndexVersionState.ACTIVE)
    )
    retired = session.get(IndexVersion, older.id)
    assert late.index_version_id == older.id
    assert active and active.id == newer.index_version_id
    assert retired and retired.state is IndexVersionState.RETIRED
    assert retired.activated_at is None
def test_retired_build_restart_does_not_replace_newer_active_index(session: Session) -> None:
    user, space, kb = graph(session, "retired-restart")
    first_version = add_version(
        session, user, space, kb, "first", ((BlockKind.PARAGRAPH, "first index"),)
    )
    first_request = request(user, space, kb, (first_version.id,))
    first = build_index(session, first_request, CountingEmbedding())
    session.commit()

    second_version = add_version(
        session, user, space, kb, "second", ((BlockKind.PARAGRAPH, "second index"),)
    )
    second = build_index(
        session,
        request(user, space, kb, (first_version.id, second_version.id)),
        CountingEmbedding(),
    )
    session.commit()
    counts = (
        session.scalar(select(func.count()).select_from(IndexVersion)),
        session.scalar(select(func.count()).select_from(Chunk)),
    )

    embedding = CountingEmbedding()
    restarted = build_index(session, first_request, embedding)
    session.commit()

    active = session.scalar(
        select(IndexVersion).where(IndexVersion.state == IndexVersionState.ACTIVE)
    )
    assert restarted.index_version_id == first.index_version_id and restarted.reused
    assert active and active.id == second.index_version_id
    assert embedding.calls == []
    assert counts == (
        session.scalar(select(func.count()).select_from(IndexVersion)),
        session.scalar(select(func.count()).select_from(Chunk)),
    )


def test_persisted_parse_freezes_ready_set_and_enqueues_job_under_kb_lock(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tutor_api.knowledge import indexing, service
    from tutor_api.knowledge.models import IngestionJob
    from tutor_api.knowledge.parsers import ParsedBlock, ParsedBlockKind, ParsedDocument

    user, space, kb = graph(session, "serialized-ready-snapshot")
    existing = add_version(
        session, user, space, kb, "already-ready", ((BlockKind.PARAGRAPH, "existing"),)
    )
    document = Document(
        space_id=space.id,
        knowledge_base_id=kb.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title="newly-ready",
        source_kind="upload",
        source_key="newly-ready.md",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=kb.id,
        document_id=document.id,
        version_number=1,
        content_sha256=content_sha256("newly ready"),
        object_key="objects/newly-ready",
        content_type="text/markdown",
        state=DocumentVersionState.PARSING,
        created_by_user_id=user.id,
    )
    session.add(version)
    session.flush()

    events: list[str] = []
    real_lock = indexing._lock_knowledge_base
    real_snapshot = service._latest_ready_version_ids
    real_prepare = service.prepare_index_build
    real_add = session.add

    def record_lock(*args: object, **kwargs: object) -> None:
        events.append("lock")
        real_lock(*args, **kwargs)

    def record_snapshot(*args: object, **kwargs: object) -> tuple[UUID, ...]:
        assert events == ["lock"]
        events.append("snapshot")
        return real_snapshot(*args, **kwargs)

    def record_prepare(*args: object, **kwargs: object) -> IndexVersion:
        assert events == ["lock", "snapshot"]
        assert kwargs["knowledge_base_locked"] is True
        events.append("target")
        return real_prepare(*args, **kwargs)

    def record_add(instance: object, *args: object, **kwargs: object) -> None:
        if isinstance(instance, IngestionJob):
            assert events == ["lock", "snapshot", "target"]
            events.append("job")
        real_add(instance, *args, **kwargs)

    monkeypatch.setattr(indexing, "_lock_knowledge_base", record_lock)
    monkeypatch.setattr(service, "_latest_ready_version_ids", record_snapshot)
    monkeypatch.setattr(service, "prepare_index_build", record_prepare)
    monkeypatch.setattr(session, "add", record_add)

    job = service.persist_parsed_document_and_enqueue_build(
        session,
        document_version_id=version.id,
        parsed_document=ParsedDocument(
            source_name="newly-ready.md",
            media_type="text/markdown",
            blocks=(ParsedBlock(ParsedBlockKind.PARAGRAPH, "newly ready", 0, "newly-ready.md#L1"),),
        ),
        parser_signature=make_pipeline_signature("parser", "native", "1"),
        ocr_signature=make_pipeline_signature("ocr", "disabled", "1"),
        chunking=ChunkingConfig(max_chars=80, overlap_chars=16),
        object_storage=MemoryObjectStorage(),
        embedding_adapter=CountingEmbedding(),
    )

    assert events == ["lock", "snapshot", "target", "job"]
    assert set(job.checkpoint["document_version_ids"]) == {str(existing.id), str(version.id)}

def test_parsed_document_persistence_enqueues_one_idempotent_build(session: Session) -> None:
    from tutor_api.knowledge.models import IngestionJob, IngestionJobKind
    from tutor_api.knowledge.parsers import ParsedBlock, ParsedBlockKind, ParsedDocument
    from tutor_api.knowledge.service import persist_parsed_document_and_enqueue_build

    user, space, kb = graph(session, "parse")
    document = Document(
        space_id=space.id,
        knowledge_base_id=kb.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title="parsed",
        source_kind="upload",
        source_key="parsed.md",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=kb.id,
        document_id=document.id,
        version_number=1,
        content_sha256="a" * 64,
        object_key="objects/parsed",
        content_type="text/markdown",
        state=DocumentVersionState.PARSING,
        created_by_user_id=user.id,
    )
    session.add(version)
    session.flush()
    parsed = ParsedDocument(
        source_name="parsed.md",
        media_type="text/markdown",
        blocks=(
            ParsedBlock(
                ParsedBlockKind.HEADING,
                "Heading",
                0,
                "parsed.md#L1",
                line_start=1,
                line_end=1,
                heading_level=1,
            ),
            ParsedBlock(
                ParsedBlockKind.PARAGRAPH, "Body text", 1, "parsed.md#L2", line_start=2, line_end=2
            ),
        ),
    )
    embedding = CountingEmbedding()
    first = persist_parsed_document_and_enqueue_build(
        session,
        document_version_id=version.id,
        parsed_document=parsed,
        parser_signature=make_pipeline_signature("parser", "native", "1"),
        ocr_signature=make_pipeline_signature("ocr", "disabled", "1"),
        chunking=ChunkingConfig(max_chars=80, overlap_chars=16),
        object_storage=MemoryObjectStorage(),
        embedding_adapter=embedding,
    )
    second = persist_parsed_document_and_enqueue_build(
        session,
        document_version_id=version.id,
        parsed_document=parsed,
        parser_signature=make_pipeline_signature("parser", "native", "1"),
        ocr_signature=make_pipeline_signature("ocr", "disabled", "1"),
        chunking=ChunkingConfig(max_chars=80, overlap_chars=16),
        object_storage=MemoryObjectStorage(),
        embedding_adapter=embedding,
    )
    conflicting = ParsedDocument(
        source_name="renamed.md",
        media_type=parsed.media_type,
        blocks=parsed.blocks,
    )
    with pytest.raises(RuntimeError, match="parsed_document_restart_conflict"):
        persist_parsed_document_and_enqueue_build(
            session,
            document_version_id=version.id,
            parsed_document=conflicting,
            parser_signature=make_pipeline_signature("parser", "native", "1"),
            ocr_signature=make_pipeline_signature("ocr", "disabled", "1"),
            chunking=ChunkingConfig(max_chars=80, overlap_chars=16),
            object_storage=MemoryObjectStorage(),
            embedding_adapter=embedding,
        )
    session.commit()
    assert first.id == second.id and first.kind is IngestionJobKind.BUILD_INDEX
    assert version.state is DocumentVersionState.READY
    assert session.scalar(select(func.count()).select_from(Page)) == 1
    assert session.scalar(select(func.count()).select_from(Block)) == 2
    assert session.scalar(select(func.count()).select_from(IndexVersion)) == 1
    assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1


def test_build_job_handler_activates_prepared_target(session: Session) -> None:
    from datetime import timedelta

    from sqlalchemy.orm import sessionmaker

    from tutor_api.knowledge.models import IngestionJob, IngestionJobKind, IngestionJobState
    from tutor_api.knowledge.parsers import ParsedBlock, ParsedBlockKind, ParsedDocument
    from tutor_api.knowledge.service import persist_parsed_document_and_enqueue_build
    from tutor_api.knowledge.worker import WorkerConfig, make_build_index_handler, run_worker_once

    user, space, kb = graph(session, "handler")
    document = Document(
        space_id=space.id,
        knowledge_base_id=kb.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title="handler",
        source_kind="upload",
        source_key="handler.md",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=kb.id,
        document_id=document.id,
        version_number=1,
        content_sha256="b" * 64,
        object_key="objects/handler",
        content_type="text/markdown",
        state=DocumentVersionState.PARSING,
        created_by_user_id=user.id,
    )
    session.add(version)
    session.flush()
    parsed = ParsedDocument(
        source_name="handler.md",
        media_type="text/markdown",
        blocks=(
            ParsedBlock(
                ParsedBlockKind.PARAGRAPH,
                "Handler content",
                0,
                "handler.md#L1",
                line_start=1,
                line_end=1,
            ),
        ),
    )
    embedding = CountingEmbedding()
    job = persist_parsed_document_and_enqueue_build(
        session,
        document_version_id=version.id,
        parsed_document=parsed,
        parser_signature=make_pipeline_signature("parser", "native", "1"),
        ocr_signature=make_pipeline_signature("ocr", "disabled", "1"),
        chunking=ChunkingConfig(max_chars=80, overlap_chars=16),
        object_storage=MemoryObjectStorage(),
        embedding_adapter=embedding,
    )
    session.commit()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    config = WorkerConfig(worker_id="builder", lease_duration=timedelta(seconds=30))
    assert run_worker_once(
        factory, {IngestionJobKind.BUILD_INDEX: make_build_index_handler(embedding)}, config=config
    )
    session.expire_all()
    assert session.get(IngestionJob, job.id).state is IngestionJobState.COMPLETED
    assert session.get(IndexVersion, job.index_version_id).state is IndexVersionState.ACTIVE


def test_multi_document_build_isolates_headings_and_namespaces_source_pointers(
    session: Session,
) -> None:
    user, space, kb = graph(session, "multi")
    first = add_version(
        session,
        user,
        space,
        kb,
        "first",
        (
            (BlockKind.TITLE, "First heading"),
            (BlockKind.PARAGRAPH, "First body"),
        ),
    )
    second = add_version(
        session,
        user,
        space,
        kb,
        "second",
        ((BlockKind.PARAGRAPH, "Second body"),),
    )
    first_pointer = session.scalar(
        select(Block.source_pointer)
        .join(Page, Block.page_id == Page.id)
        .where(Page.document_version_id == first.id, Block.ordinal == 1)
    )
    second_block = session.scalar(
        select(Block)
        .join(Page, Block.page_id == Page.id)
        .where(Page.document_version_id == second.id)
    )
    assert first_pointer and second_block
    second_block.source_pointer = first_pointer
    session.flush()

    result = build_index(
        session,
        request(user, space, kb, (first.id, second.id)),
        CountingEmbedding(),
    )
    session.commit()

    chunks = list(
        session.scalars(
            select(Chunk)
            .where(Chunk.index_version_id == result.index_version_id)
            .order_by(Chunk.ordinal)
        )
    )
    second_chunks = [chunk for chunk in chunks if chunk.document_version_id == second.id]
    assert second_chunks and all(
        not chunk.content.startswith("First heading\n") for chunk in second_chunks
    )
    assert len({chunk.source_pointer for chunk in chunks}) == len(chunks)
    assert all(str(chunk.document_version_id) in chunk.source_pointer for chunk in chunks)


@pytest.mark.parametrize("source_case", ("missing", "cross_kb", "not_ready"))
def test_prepare_index_build_rejects_invalid_immutable_source_contract(
    session: Session, source_case: str
) -> None:
    user, space, kb = graph(session, f"source-contract-{source_case}")
    version = add_version(
        session,
        user,
        space,
        kb,
        "valid",
        ((BlockKind.PARAGRAPH, "immutable source"),),
    )
    version_ids = (version.id,)
    if source_case == "missing":
        version_ids = (UUID(int=999),)
    elif source_case == "cross_kb":
        other_user, other_space, other_kb = graph(session, "other-source")
        foreign = add_version(
            session,
            other_user,
            other_space,
            other_kb,
            "foreign",
            ((BlockKind.PARAGRAPH, "foreign immutable source"),),
        )
        version_ids = (foreign.id,)
    else:
        version.state = DocumentVersionState.FAILED
        session.flush()

    with pytest.raises(IndexingError) as captured:
        prepare_index_build(session, request(user, space, kb, version_ids), CountingEmbedding())

    assert captured.value.code == "index_source_contract_invalid"
    assert session.scalar(select(func.count()).select_from(IndexVersion)) == 0


def test_build_rejects_empty_ready_source_and_cleans_failed_target(session: Session) -> None:
    user, space, kb = graph(session, "empty-source")
    version = add_version(session, user, space, kb, "empty", ())

    with pytest.raises(IndexingError) as captured:
        build_index(session, request(user, space, kb, (version.id,)), CountingEmbedding())

    session.commit()
    failed = session.scalar(
        select(IndexVersion).where(
            IndexVersion.knowledge_base_id == kb.id,
            IndexVersion.state == IndexVersionState.FAILED,
        )
    )
    assert captured.value.code == "index_source_empty"
    assert failed is not None
    assert (
        session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.index_version_id == failed.id)
        )
        == 0
    )


@pytest.mark.parametrize(
    "vector",
    (
        [0.0] * 7,
        [True] + [0.0] * 7,
        ["invalid"] + [0.0] * 7,
        [float("nan")] + [0.0] * 7,
        [float("inf")] + [0.0] * 7,
    ),
)
def test_build_rejects_malformed_embedding_without_replacing_active_index(
    session: Session, vector: object
) -> None:
    class MalformedEmbedding(CountingEmbedding):
        def embed(self, text: str):
            self.calls.append(text)
            return vector

    user, space, kb = graph(session, "malformed-embedding")
    stable = add_version(
        session,
        user,
        space,
        kb,
        "stable",
        ((BlockKind.PARAGRAPH, "stable immutable content"),),
    )
    active = build_index(session, request(user, space, kb, (stable.id,)), CountingEmbedding())
    session.commit()
    candidate = add_version(
        session,
        user,
        space,
        kb,
        "candidate",
        ((BlockKind.PARAGRAPH, "candidate immutable content"),),
    )

    with pytest.raises(IndexingError) as captured:
        build_index(
            session,
            request(user, space, kb, (stable.id, candidate.id)),
            MalformedEmbedding(),
        )

    session.commit()
    current = session.scalar(
        select(IndexVersion).where(
            IndexVersion.knowledge_base_id == kb.id,
            IndexVersion.state == IndexVersionState.ACTIVE,
        )
    )
    failed = session.scalar(
        select(IndexVersion).where(
            IndexVersion.knowledge_base_id == kb.id,
            IndexVersion.state == IndexVersionState.FAILED,
        )
    )
    assert captured.value.code == "embedding_contract_invalid"
    assert current is not None and current.id == active.index_version_id
    assert failed is not None
    assert (
        session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.index_version_id == failed.id)
        )
        == 0
    )


def test_build_bounds_long_source_pointer_without_losing_immutable_identity(
    session: Session,
) -> None:
    user, space, kb = graph(session, "long-pointer")
    version = add_version(
        session,
        user,
        space,
        kb,
        "pointer",
        ((BlockKind.PARAGRAPH, "bounded pointer body"),),
    )
    raw_pointer = "p" * 1_000
    block = session.scalar(
        select(Block)
        .join(Page, Block.page_id == Page.id)
        .where(Page.document_version_id == version.id)
    )
    assert block is not None
    block.source_pointer = raw_pointer
    session.flush()

    result = build_index(session, request(user, space, kb, (version.id,)), CountingEmbedding())
    chunk = session.scalar(select(Chunk).where(Chunk.index_version_id == result.index_version_id))

    assert chunk is not None
    expected_pointer = f"document-version:{version.id}:sha256:{content_sha256(raw_pointer)}"
    assert chunk.source_pointer == expected_pointer
    assert len(chunk.source_pointer) <= 980

def test_punctuation_only_blocks_do_not_break_index_build(session: Session) -> None:
    user, space, kb = graph(session, "punct")
    version = add_version(
        session,
        user,
        space,
        kb,
        "punct-doc",
        (
            (BlockKind.TITLE, "第一章 概述"),
            (BlockKind.PARAGRAPH, "} }]"),
            (BlockKind.PARAGRAPH, "真实正文介绍智能体的规划与记忆模块。"),
            (BlockKind.PARAGRAPH, "{"),
            (BlockKind.PARAGRAPH, "]},"),
            (BlockKind.TITLE, "]}"),
        ),
    )

    result = build_index(
        session,
        request(user, space, kb, (version.id,)),
        HashEmbeddingAdapter(dimension=8),
    )
    session.commit()

    index = session.get(IndexVersion, result.index_version_id)
    assert index is not None and index.state is IndexVersionState.ACTIVE
    chunks = list(
        session.scalars(select(Chunk).where(Chunk.index_version_id == index.id))
    )
    assert chunks
    assert all(not is_embedding_blank(chunk.content) for chunk in chunks)


def test_document_without_embeddable_text_fails_with_stable_code(session: Session) -> None:
    user, space, kb = graph(session, "blank-doc")
    version = add_version(
        session,
        user,
        space,
        kb,
        "blank-doc",
        (
            (BlockKind.PARAGRAPH, "} }]"),
            (BlockKind.PARAGRAPH, "***"),
        ),
    )

    with pytest.raises(IndexingError) as raised:
        build_index(
            session,
            request(user, space, kb, (version.id,)),
            HashEmbeddingAdapter(dimension=8),
        )
    assert raised.value.code == "index_source_empty"


def test_lexical_terms_include_cjk_bigrams_for_natural_language_recall() -> None:
    chunk_terms = set(
        normalize_lexical_terms("路径损耗用于描述接收功率随距离的衰减。Vectors are neat.")
    )

    assert {"路径", "径损", "损耗", "衰减"} <= chunk_terms
    assert {"vectors", "are", "neat"} <= chunk_terms
    query_terms = set(normalize_lexical_terms("什么是路径损耗？"))
    assert query_terms & chunk_terms, "中文查询词必须能与正文词法项相交"


def test_lexical_terms_cap_stays_bounded_for_long_chinese_text() -> None:
    long_text = "无线" * 5_000

    terms = normalize_lexical_terms(long_text)

    assert len(terms) <= MAX_LEXICAL_TERMS
    assert "无线" in terms

