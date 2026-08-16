from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import (
    Block,
    BlockKind,
    Chunk,
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    EmbeddingVector,
    IndexVersion,
    IndexVersionState,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeBase,
    KnowledgeBaseState,
    Page,
)
from tutor_api.spaces.models import Space, SpaceKind

VALID_HASH = "a" * 64
SECOND_HASH = "b" * 64


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    active_session = factory()
    try:
        yield active_session
    finally:
        active_session.close()
        engine.dispose()


def create_user_space(session: Session, suffix: str) -> tuple[User, Space]:
    user = User(email=f"{suffix}@example.com", username=suffix, password_hash="hash")
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name=f"{suffix} space")
    session.add(space)
    session.flush()
    return user, space


def create_knowledge_base(
    session: Session, user: User, space: Space, suffix: str = "math"
) -> KnowledgeBase:
    knowledge_base = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name=f"{suffix} knowledge",
        state=KnowledgeBaseState.ACTIVE,
    )
    session.add(knowledge_base)
    session.flush()
    return knowledge_base


def create_document_graph(
    session: Session,
    user: User,
    space: Space,
    knowledge_base: KnowledgeBase,
    suffix: str = "book",
) -> tuple[Document, DocumentVersion, Page, Block]:
    document = Document(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title=f"{suffix}.pdf",
        source_kind="upload",
        source_key=f"uploads/{suffix}.pdf",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        version_number=1,
        content_sha256=VALID_HASH,
        object_key=f"spaces/{space.id}/documents/{document.id}/versions/1/original.pdf",
        content_type="application/pdf",
        state=DocumentVersionState.READY,
        created_by_user_id=user.id,
    )
    session.add(version)
    session.flush()
    page = Page(
        space_id=space.id,
        document_version_id=version.id,
        page_number=1,
        source_pointer="page:1",
        content_sha256=SECOND_HASH,
        text_object_key=f"spaces/{space.id}/pages/1.txt",
    )
    session.add(page)
    session.flush()
    block = Block(
        space_id=space.id,
        page_id=page.id,
        ordinal=0,
        kind=BlockKind.PARAGRAPH,
        source_pointer="page:1/block:0",
        content_sha256="c" * 64,
        text="Pythagorean theorem",
    )
    session.add(block)
    session.flush()
    return document, version, page, block


def create_index(
    session: Session,
    user: User,
    space: Space,
    knowledge_base: KnowledgeBase,
    *,
    suffix: str = "v1",
    state: IndexVersionState = IndexVersionState.READY,
    dimension: int = 8,
) -> IndexVersion:
    index = IndexVersion(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        version_number=1 if suffix == "v1" else 2,
        state=state,
        parser_signature="parser:native-v1",
        ocr_signature="ocr:disabled",
        chunking_signature="chunk:structure-v1",
        embedding_backend="hash",
        embedding_model="feature-hash-v1",
        embedding_dimension=dimension,
        index_signature=f"index:{suffix}",
        created_by_user_id=user.id,
    )
    session.add(index)
    session.flush()
    return index


def create_chunk(
    session: Session,
    space: Space,
    index: IndexVersion,
    version: DocumentVersion,
    page: Page,
    block: Block,
    *,
    ordinal: int = 0,
    source_pointer: str = "page:1/block:0/chunk:0",
    dimension: int | None = None,
    signature: str | None = None,
    embedding: list[float] | None = None,
) -> Chunk:
    chunk_dimension = dimension if dimension is not None else index.embedding_dimension
    chunk = Chunk(
        space_id=space.id,
        knowledge_base_id=version.knowledge_base_id,
        index_version_id=index.id,
        document_version_id=version.id,
        page_id=page.id,
        block_id=block.id,
        ordinal=ordinal,
        source_pointer=source_pointer,
        content_sha256="d" * 64,
        content="The square of the hypotenuse equals the sum of the squares.",
        embedding_dimension=chunk_dimension,
        index_signature=signature if signature is not None else index.index_signature,
        embedding=embedding if embedding is not None else [0.1] * chunk_dimension,
    )
    session.add(chunk)
    session.flush()
    return chunk


def test_all_knowledge_resource_tables_have_indexed_non_null_space_id() -> None:
    table_names = {
        "knowledge_bases",
        "documents",
        "document_versions",
        "pages",
        "blocks",
        "index_versions",
        "chunks",
        "ingestion_jobs",
    }
    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        assert table.c.space_id.nullable is False
        assert any(
            tuple(column.name for column in index.columns) == ("space_id",)
            for index in table.indexes
        )


def test_all_parent_links_include_space_id_in_database_foreign_keys() -> None:
    expected_parents = {
        "documents": {"knowledge_bases"},
        "document_versions": {"documents"},
        "pages": {"document_versions"},
        "blocks": {"pages"},
        "index_versions": {"knowledge_bases"},
        "chunks": {"index_versions", "document_versions", "pages", "blocks"},
        "ingestion_jobs": {
            "knowledge_bases",
            "documents",
            "document_versions",
            "index_versions",
        },
    }
    for table_name, parent_names in expected_parents.items():
        table = Base.metadata.tables[table_name]
        for parent_name in parent_names:
            matching_constraints = [
                constraint
                for constraint in table.foreign_key_constraints
                if constraint.referred_table.name == parent_name
            ]
            assert matching_constraints
            assert all(
                "space_id" in {element.parent.name for element in constraint.elements}
                for constraint in matching_constraints
            )


def test_knowledge_ids_are_uuid_typed_and_audit_fields_are_present() -> None:
    for table_name in {
        "knowledge_bases",
        "documents",
        "document_versions",
        "pages",
        "blocks",
        "index_versions",
        "chunks",
        "ingestion_jobs",
    }:
        table = Base.metadata.tables[table_name]
        assert table.c.id.type.python_type is UUID
        assert "created_at" in table.c
        assert "updated_at" in table.c


def test_each_knowledge_base_has_at_most_one_active_index(session: Session) -> None:
    user, space = create_user_space(session, "active-index")
    knowledge_base = create_knowledge_base(session, user, space)
    create_index(session, user, space, knowledge_base, state=IndexVersionState.ACTIVE)
    session.add(
        IndexVersion(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            version_number=2,
            state=IndexVersionState.ACTIVE,
            parser_signature="parser:native-v1",
            ocr_signature="ocr:disabled",
            chunking_signature="chunk:structure-v1",
            embedding_backend="hash",
            embedding_model="feature-hash-v1",
            embedding_dimension=8,
            index_signature="index:v2",
            created_by_user_id=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_document_source_and_version_uniqueness_are_scoped_to_parent(session: Session) -> None:
    user, space = create_user_space(session, "source-unique")
    knowledge_base = create_knowledge_base(session, user, space)
    document, _, _, _ = create_document_graph(session, user, space, knowledge_base)
    session.commit()
    session.add(
        Document(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            title="duplicate.pdf",
            source_kind=document.source_kind,
            source_key=document.source_key,
            state=DocumentState.ACTIVE,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    document = session.get(Document, document.id)
    assert document is not None
    session.add(
        DocumentVersion(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            version_number=1,
            content_sha256="e" * 64,
            object_key="spaces/duplicate/version.pdf",
            content_type="application/pdf",
            state=DocumentVersionState.UPLOADED,
            created_by_user_id=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_document_rejects_duplicate_content_hash_versions(session: Session) -> None:
    user, space = create_user_space(session, "content-unique")
    knowledge_base = create_knowledge_base(session, user, space)
    document, version, _, _ = create_document_graph(session, user, space, knowledge_base)
    session.add(
        DocumentVersion(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            version_number=2,
            content_sha256=version.content_sha256,
            object_key="spaces/content-unique/version-2.pdf",
            content_type="application/pdf",
            state=DocumentVersionState.UPLOADED,
            created_by_user_id=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize("invalid_hash", ["a" * 63, "a" * 65, "G" * 64, "-" * 64])
def test_sha256_columns_reject_invalid_values(session: Session, invalid_hash: str) -> None:
    user, space = create_user_space(session, f"hash-{abs(hash(invalid_hash))}")
    knowledge_base = create_knowledge_base(session, user, space)
    document = Document(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title="invalid.pdf",
        source_kind="upload",
        source_key="uploads/invalid.pdf",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    session.add(
        DocumentVersion(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            version_number=1,
            content_sha256=invalid_hash,
            object_key="spaces/invalid/version.pdf",
            content_type="application/pdf",
            state=DocumentVersionState.UPLOADED,
            created_by_user_id=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_parent_child_space_mismatch_is_rejected(session: Session) -> None:
    user, first_space = create_user_space(session, "tenant-one")
    _, second_space = create_user_space(session, "tenant-two")
    knowledge_base = create_knowledge_base(session, user, first_space)
    session.add(
        Document(
            space_id=second_space.id,
            knowledge_base_id=knowledge_base.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            title="cross-space.pdf",
            source_kind="upload",
            source_key="uploads/cross-space.pdf",
            state=DocumentState.ACTIVE,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_chunk_dimension_signature_and_vector_length_match_index(session: Session) -> None:
    user, space = create_user_space(session, "chunk-contract")
    knowledge_base = create_knowledge_base(session, user, space)
    _, version, page, block = create_document_graph(session, user, space, knowledge_base)
    index = create_index(session, user, space, knowledge_base)
    create_chunk(session, space, index, version, page, block)
    session.commit()
    for number, overrides in enumerate(
        (
            {"dimension": 9, "embedding": [0.1] * 9},
            {"signature": "index:other"},
            {"embedding": [0.1, 0.2]},
        ),
        start=1,
    ):
        active = sessionmaker(bind=session.get_bind())()
        try:
            with pytest.raises(IntegrityError):
                create_chunk(
                    active,
                    space,
                    active.get(IndexVersion, index.id),
                    active.get(DocumentVersion, version.id),
                    active.get(Page, page.id),
                    active.get(Block, block.id),
                    ordinal=number,
                    source_pointer=f"bad:{number}",
                    **overrides,
                )
        finally:
            active.rollback()
            active.close()


def test_page_block_and_chunk_ordinals_are_unique(session: Session) -> None:
    user, space = create_user_space(session, "ordinals")
    knowledge_base = create_knowledge_base(session, user, space)
    _, version, page, block = create_document_graph(session, user, space, knowledge_base)
    index = create_index(session, user, space, knowledge_base)
    create_chunk(session, space, index, version, page, block)
    session.commit()
    duplicates = [
        Page(
            space_id=space.id,
            document_version_id=version.id,
            page_number=1,
            source_pointer="page:other",
            content_sha256="e" * 64,
        ),
        Page(
            space_id=space.id,
            document_version_id=version.id,
            page_number=2,
            source_pointer=page.source_pointer,
            content_sha256="e" * 64,
        ),
        Block(
            space_id=space.id,
            page_id=page.id,
            ordinal=0,
            kind=BlockKind.PARAGRAPH,
            source_pointer="page:1/block:other",
            content_sha256="e" * 64,
            text="duplicate ordinal",
        ),
        Block(
            space_id=space.id,
            page_id=page.id,
            ordinal=1,
            kind=BlockKind.PARAGRAPH,
            source_pointer=block.source_pointer,
            content_sha256="e" * 64,
            text="duplicate pointer",
        ),
        Chunk(
            space_id=space.id,
            index_version_id=index.id,
            document_version_id=version.id,
            page_id=page.id,
            block_id=block.id,
            ordinal=0,
            source_pointer="chunk:other",
            content_sha256="e" * 64,
            content="duplicate ordinal",
            embedding_dimension=8,
            index_signature=index.index_signature,
            embedding=[0.2] * 8,
        ),
        Chunk(
            space_id=space.id,
            index_version_id=index.id,
            document_version_id=version.id,
            page_id=page.id,
            block_id=block.id,
            ordinal=1,
            source_pointer="page:1/block:0/chunk:0",
            content_sha256="e" * 64,
            content="duplicate pointer",
            embedding_dimension=8,
            index_signature=index.index_signature,
            embedding=[0.2] * 8,
        ),
    ]
    for duplicate in duplicates:
        active = sessionmaker(bind=session.get_bind())()
        try:
            active.add(duplicate)
            with pytest.raises(IntegrityError):
                active.commit()
        finally:
            active.rollback()
            active.close()


def test_ingestion_job_persists_recovery_lease_retry_and_checkpoint(session: Session) -> None:
    user, space = create_user_space(session, "recovery-job")
    knowledge_base = create_knowledge_base(session, user, space)
    document, version, _, _ = create_document_graph(session, user, space, knowledge_base)
    index = create_index(session, user, space, knowledge_base)
    job = IngestionJob(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        index_version_id=index.id,
        kind=IngestionJobKind.BUILD_INDEX,
        state=IngestionJobState.RUNNING,
        idempotency_key="build-index:v1",
        attempt_count=2,
        max_attempts=5,
        available_at=datetime.now(UTC),
        lease_owner="worker-1",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        checkpoint={"page": 12, "chunk": 4},
        created_by_user_id=user.id,
        started_at=datetime.now(UTC),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    assert (job.attempt_count, job.max_attempts, job.lease_owner) == (2, 5, "worker-1")
    assert job.lease_expires_at is not None
    assert job.checkpoint == {"page": 12, "chunk": 4}


def test_ingestion_job_rejects_incomplete_lease_and_invalid_retry_counts(session: Session) -> None:
    user, space = create_user_space(session, "invalid-job")
    knowledge_base = create_knowledge_base(session, user, space)
    document, version, _, _ = create_document_graph(session, user, space, knowledge_base)
    session.add(
        IngestionJob(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            document_version_id=version.id,
            kind=IngestionJobKind.PARSE_DOCUMENT,
            state=IngestionJobState.RUNNING,
            idempotency_key="invalid-lease",
            attempt_count=4,
            max_attempts=3,
            lease_owner="worker-1",
            lease_expires_at=None,
            checkpoint={},
            created_by_user_id=user.id,
            started_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize("target", ["knowledge_base", "document", "version", "index"])
def test_knowledge_deletions_cascade_without_orphans(session: Session, target: str) -> None:
    user, space = create_user_space(session, f"cascade-{target}")
    knowledge_base = create_knowledge_base(session, user, space)
    document, version, page, block = create_document_graph(
        session, user, space, knowledge_base, suffix=target
    )
    index = create_index(session, user, space, knowledge_base)
    chunk = create_chunk(session, space, index, version, page, block)
    if target in {"document", "version"}:
        job = IngestionJob(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            document_version_id=version.id,
            kind=IngestionJobKind.PARSE_DOCUMENT,
            state=IngestionJobState.QUEUED,
            idempotency_key=f"cascade:{target}",
            attempt_count=0,
            max_attempts=3,
            available_at=datetime.now(UTC),
            checkpoint={},
            created_by_user_id=user.id,
        )
    else:
        job = IngestionJob(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            index_version_id=index.id,
            kind=IngestionJobKind.BUILD_INDEX,
            state=IngestionJobState.QUEUED,
            idempotency_key=f"cascade:{target}",
            attempt_count=0,
            max_attempts=3,
            available_at=datetime.now(UTC),
            checkpoint={},
            created_by_user_id=user.id,
        )
    session.add(job)
    session.commit()
    ids = {
        "knowledge_base": knowledge_base.id,
        "document": document.id,
        "version": version.id,
        "page": page.id,
        "block": block.id,
        "index": index.id,
        "chunk": chunk.id,
        "job": job.id,
    }
    session.delete(
        {
            "knowledge_base": knowledge_base,
            "document": document,
            "version": version,
            "index": index,
        }[target]
    )
    session.commit()
    if target == "knowledge_base":
        assert all(
            session.get(model, ids[key]) is None
            for model, key in (
                (KnowledgeBase, "knowledge_base"),
                (Document, "document"),
                (IndexVersion, "index"),
                (IngestionJob, "job"),
            )
        )
    elif target == "document":
        assert all(
            session.get(model, ids[key]) is None
            for model, key in (
                (DocumentVersion, "version"),
                (Page, "page"),
                (Block, "block"),
                (Chunk, "chunk"),
                (IngestionJob, "job"),
            )
        )
    elif target == "version":
        assert all(
            session.get(model, ids[key]) is None
            for model, key in (
                (Page, "page"),
                (Block, "block"),
                (Chunk, "chunk"),
                (IngestionJob, "job"),
            )
        )
    else:
        assert session.get(Chunk, ids["chunk"]) is None
        assert session.get(IngestionJob, ids["job"]) is None


def test_status_enums_reject_unknown_database_values(session: Session) -> None:
    user, space = create_user_space(session, "enum-state")
    session.add(
        KnowledgeBase(
            space_id=space.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            name="invalid state",
            state="unknown",  # type: ignore[arg-type]
        )
    )
    with pytest.raises((IntegrityError, StatementError)):
        session.commit()


def test_embedding_is_stored_as_json_in_sqlite(session: Session) -> None:
    user, space = create_user_space(session, "json-vector")
    knowledge_base = create_knowledge_base(session, user, space)
    _, version, page, block = create_document_graph(session, user, space, knowledge_base)
    index = create_index(session, user, space, knowledge_base)
    chunk = create_chunk(session, space, index, version, page, block)
    session.commit()
    assert chunk.embedding == [0.1] * 8
    columns = {
        column["name"]: column for column in inspect(session.get_bind()).get_columns("chunks")
    }
    assert "JSON" in str(columns["embedding"]["type"]).upper()
    assert session.scalar(select(Chunk).where(Chunk.id == chunk.id)) is not None



def test_chunk_embedding_is_required_by_orm_persistence(session: Session) -> None:
    user, space = create_user_space(session, "none-vector")
    knowledge_base = create_knowledge_base(session, user, space)
    _, version, page, block = create_document_graph(session, user, space, knowledge_base)
    index = create_index(session, user, space, knowledge_base)
    chunk = Chunk(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        index_version_id=index.id,
        document_version_id=version.id,
        page_id=page.id,
        block_id=block.id,
        ordinal=0,
        source_pointer="page:1/block:0/chunk:none-vector",
        content_sha256="d" * 64,
        content="Embedding is required for an immutable indexed chunk.",
        embedding_dimension=index.embedding_dimension,
        index_signature=index.index_signature,
        embedding=None,  # type: ignore[arg-type]
    )
    session.add(chunk)

    with pytest.raises((IntegrityError, StatementError, TypeError, ValueError)):
        session.commit()


def test_chunk_rejects_document_graph_from_another_knowledge_base(session: Session) -> None:
    user, space = create_user_space(session, "cross-kb-chunk")
    first_kb = create_knowledge_base(session, user, space, "first")
    second_kb = create_knowledge_base(session, user, space, "second")
    _, second_version, second_page, second_block = create_document_graph(
        session, user, space, second_kb, suffix="second-book"
    )
    first_index = create_index(session, user, space, first_kb)

    chunk = Chunk(
        space_id=space.id,
        knowledge_base_id=first_kb.id,
        index_version_id=first_index.id,
        document_version_id=second_version.id,
        page_id=second_page.id,
        block_id=second_block.id,
        ordinal=0,
        source_pointer="cross-kb:chunk:0",
        content_sha256="d" * 64,
        content="This chunk must not cross knowledge-base boundaries.",
        embedding_dimension=first_index.embedding_dimension,
        index_signature=first_index.index_signature,
        embedding=[0.1] * first_index.embedding_dimension,
    )
    session.add(chunk)

    with pytest.raises(IntegrityError):
        session.commit()


def test_document_version_rejects_a_different_knowledge_base_identity(session: Session) -> None:
    user, space = create_user_space(session, "cross-kb-version")
    first_kb = create_knowledge_base(session, user, space, "first")
    second_kb = create_knowledge_base(session, user, space, "second")
    second_document, _, _, _ = create_document_graph(
        session, user, space, second_kb, suffix="second-version"
    )
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=first_kb.id,
        document_id=second_document.id,
        version_number=2,
        content_sha256="e" * 64,
        object_key=f"spaces/{space.id}/cross-kb-version.pdf",
        content_type="application/pdf",
        state=DocumentVersionState.READY,
        created_by_user_id=user.id,
    )
    session.add(version)

    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    "invalid_embedding",
    [
        None,
        True,
        "[0.1]",
        {"value": 0.1},
        (0.1, 0.2),
        [True],
        [None],
        [[0.1]],
        [float("nan")],
        [float("inf")],
        [float("-inf")],
    ],
    ids=[
        "none",
        "bool-root",
        "string-root",
        "object-root",
        "tuple-root",
        "bool-element",
        "null-element",
        "nested-element",
        "nan",
        "positive-infinity",
        "negative-infinity",
    ],
)
def test_embedding_bind_rejects_invalid_python_values(invalid_embedding: object) -> None:
    embedding_type = EmbeddingVector()

    with pytest.raises((TypeError, ValueError)):
        embedding_type.process_bind_param(invalid_embedding, sqlite.dialect())  # type: ignore[arg-type]


def test_embedding_bind_normalizes_numeric_values_to_finite_floats() -> None:
    value = EmbeddingVector().process_bind_param([1, 2.5], sqlite.dialect())

    assert value == [1.0, 2.5]
    assert all(type(component) is float for component in value)


@pytest.mark.parametrize(
    ("database_value", "expected"),
    [
        ([1, 2.5], [1.0, 2.5]),
        ((1, 2.5), [1.0, 2.5]),
        ("[1,2.5]", [1.0, 2.5]),
        (b"[1,2.5]", [1.0, 2.5]),
        (memoryview(b"[1,2.5]"), [1.0, 2.5]),
    ],
)
def test_postgresql_embedding_result_processor_parses_common_dbapi_values(
    database_value: object, expected: list[float]
) -> None:
    result = EmbeddingVector().process_result_value(database_value, postgresql.dialect())

    assert result == expected
    assert all(type(component) is float for component in result)


@pytest.mark.parametrize(
    "database_value",
    [None, "null", "{}", "[true]", "[null]", "[NaN]", object()],
)
def test_postgresql_embedding_result_processor_rejects_invalid_values(
    database_value: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        EmbeddingVector().process_result_value(database_value, postgresql.dialect())


def _raw_chunk_insert(
    session: Session,
    *,
    knowledge_base: KnowledgeBase,
    index: IndexVersion,
    version: DocumentVersion,
    page: Page,
    block: Block,
    embedding_json: str,
) -> None:
    all_values = {
        "id": uuid4().hex,
        "space_id": knowledge_base.space_id.hex,
        "knowledge_base_id": knowledge_base.id.hex,
        "index_version_id": index.id.hex,
        "document_version_id": version.id.hex,
        "page_id": page.id.hex,
        "block_id": block.id.hex,
        "ordinal": 99,
        "source_pointer": f"raw:{uuid4()}",
        "content_sha256": "f" * 64,
        "content": "raw embedding contract",
        "embedding_dimension": index.embedding_dimension,
        "index_signature": index.index_signature,
        "embedding": embedding_json,
    }
    available_columns = {
        column["name"] for column in inspect(session.get_bind()).get_columns("chunks")
    }
    values = {name: value for name, value in all_values.items() if name in available_columns}
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    session.connection().exec_driver_sql(
        f"INSERT INTO chunks ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )


@pytest.mark.parametrize(
    "embedding_json",
    [
        "[true,0,0,0,0,0,0,0]",
        "[null,0,0,0,0,0,0,0]",
        '["0",0,0,0,0,0,0,0]',
        "[{},0,0,0,0,0,0,0]",
        "[[0],0,0,0,0,0,0,0]",
    ],
)
def test_sqlite_rejects_non_numeric_embedding_elements(
    session: Session, embedding_json: str
) -> None:
    user, space = create_user_space(session, f"raw-vector-{uuid4().hex}")
    knowledge_base = create_knowledge_base(session, user, space)
    _, version, page, block = create_document_graph(session, user, space, knowledge_base)
    index = create_index(session, user, space, knowledge_base)

    with pytest.raises(IntegrityError, match="invalid embedding element"):
        _raw_chunk_insert(
            session,
            knowledge_base=knowledge_base,
            index=index,
            version=version,
            page=page,
            block=block,
            embedding_json=embedding_json,
        )


@pytest.mark.parametrize("embedding_json", ["{}", '"text"', "null", "true", "1"])
def test_sqlite_rejects_non_array_embedding_roots(
    session: Session, embedding_json: str
) -> None:
    user, space = create_user_space(session, f"raw-vector-root-{uuid4().hex}")
    knowledge_base = create_knowledge_base(session, user, space)
    _, version, page, block = create_document_graph(session, user, space, knowledge_base)
    index = create_index(session, user, space, knowledge_base)

    with pytest.raises(IntegrityError):
        _raw_chunk_insert(
            session,
            knowledge_base=knowledge_base,
            index=index,
            version=version,
            page=page,
            block=block,
            embedding_json=embedding_json,
        )


def test_sqlite_embedding_constraint_requires_an_array_root() -> None:
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in Chunk.__table__.constraints
        if hasattr(constraint, "sqltext")
    }

    assert "json_type(embedding) = 'array'" in constraints[
        "ck_chunk_embedding_dimension_sqlite"
    ]


def _make_job(
    *,
    user: User,
    space: Space,
    knowledge_base: KnowledgeBase,
    kind: IngestionJobKind,
    state: IngestionJobState = IngestionJobState.QUEUED,
    document: Document | None = None,
    version: DocumentVersion | None = None,
    page: Page | None = None,
    index: IndexVersion | None = None,
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    checkpoint: dict[str, object] | None = None,
) -> IngestionJob:
    job = IngestionJob(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id if document else None,
        document_version_id=version.id if version else None,
        index_version_id=index.id if index else None,
        kind=kind,
        state=state,
        idempotency_key=f"job:{uuid4()}",
        attempt_count=0,
        max_attempts=3,
        available_at=datetime.now(UTC),
        lease_owner=lease_owner,
        lease_expires_at=lease_expires_at,
        checkpoint={} if checkpoint is None else checkpoint,
        created_by_user_id=user.id,
        started_at=started_at,
        completed_at=completed_at,
    )
    job.page_id = page.id if page else None
    return job


@pytest.mark.parametrize(
    "scenario",
    [
        "running_without_lease",
        "completed_without_completed_at",
        "queued_with_live_lease",
        "parse_without_document",
        "ocr_without_document",
        "build_index_without_index",
    ],
)
def test_ingestion_job_rejects_invalid_state_and_target_matrix(
    session: Session, scenario: str
) -> None:
    user, space = create_user_space(session, f"job-matrix-{scenario}")
    knowledge_base = create_knowledge_base(session, user, space)
    document, version, page, _ = create_document_graph(session, user, space, knowledge_base)
    now = datetime.now(UTC)
    kwargs: dict[str, object] = {
        "user": user,
        "space": space,
        "knowledge_base": knowledge_base,
        "kind": IngestionJobKind.PARSE_DOCUMENT,
        "document": document,
        "version": version,
    }
    if scenario == "running_without_lease":
        kwargs.update(state=IngestionJobState.RUNNING, started_at=now)
    elif scenario == "completed_without_completed_at":
        kwargs.update(state=IngestionJobState.COMPLETED, started_at=now)
    elif scenario == "queued_with_live_lease":
        kwargs.update(
            lease_owner="worker-1", lease_expires_at=now + timedelta(minutes=5)
        )
    elif scenario == "parse_without_document":
        kwargs.update(document=None, version=None)
    elif scenario == "ocr_without_document":
        kwargs.update(
            kind=IngestionJobKind.OCR_PAGE,
            document=None,
            version=None,
            page=None,
        )
    else:
        kwargs.update(
            kind=IngestionJobKind.BUILD_INDEX,
            document=None,
            version=None,
            index=None,
        )
    session.add(_make_job(**kwargs))  # type: ignore[arg-type]

    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize("kind", list(IngestionJobKind))
def test_ingestion_job_accepts_only_the_targets_for_its_kind(
    session: Session, kind: IngestionJobKind
) -> None:
    user, space = create_user_space(session, f"valid-target-{kind.value}")
    knowledge_base = create_knowledge_base(session, user, space)
    document, version, page, _ = create_document_graph(session, user, space, knowledge_base)
    index = create_index(session, user, space, knowledge_base)
    targets = {
        IngestionJobKind.PARSE_DOCUMENT: {"document": document, "version": version},
        IngestionJobKind.OCR_PAGE: {
            "document": document,
            "version": version,
            "page": page,
        },
        IngestionJobKind.BUILD_INDEX: {"index": index},
    }
    session.add(
        _make_job(
            user=user,
            space=space,
            knowledge_base=knowledge_base,
            kind=kind,
            **targets[kind],
        )
    )
    session.commit()


def test_checkpoint_in_place_mutation_is_persisted(session: Session) -> None:
    user, space = create_user_space(session, "mutable-checkpoint")
    knowledge_base = create_knowledge_base(session, user, space)
    document, version, _, _ = create_document_graph(session, user, space, knowledge_base)
    job = _make_job(
        user=user,
        space=space,
        knowledge_base=knowledge_base,
        kind=IngestionJobKind.PARSE_DOCUMENT,
        document=document,
        version=version,
        checkpoint={"page": 1},
    )
    session.add(job)
    session.commit()
    job.checkpoint["page"] = 2

    assert session.is_modified(job, include_collections=True)
    session.commit()
    job_id = job.id
    session.close()

    fresh_session = sessionmaker(bind=session.get_bind())()
    try:
        assert fresh_session.get(IngestionJob, job_id).checkpoint == {"page": 2}
    finally:
        fresh_session.close()


def _raw_job_insert(
    session: Session,
    *,
    user: User,
    space: Space,
    knowledge_base: KnowledgeBase,
    document: Document,
    version: DocumentVersion,
    checkpoint_json: str,
) -> None:
    all_values = {
        "id": uuid4().hex,
        "space_id": space.id.hex,
        "knowledge_base_id": knowledge_base.id.hex,
        "document_id": document.id.hex,
        "document_version_id": version.id.hex,
        "page_id": None,
        "index_version_id": None,
        "kind": IngestionJobKind.PARSE_DOCUMENT.value,
        "state": IngestionJobState.QUEUED.value,
        "idempotency_key": f"raw-job:{uuid4()}",
        "attempt_count": 0,
        "max_attempts": 3,
        "available_at": datetime.now(UTC).isoformat(),
        "lease_owner": None,
        "lease_expires_at": None,
        "checkpoint": checkpoint_json,
        "last_error_code": None,
        "last_error_detail": None,
        "created_by_user_id": user.id.hex,
        "started_at": None,
        "completed_at": None,
    }
    available_columns = {
        column["name"]
        for column in inspect(session.get_bind()).get_columns("ingestion_jobs")
    }
    values = {name: value for name, value in all_values.items() if name in available_columns}
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    session.connection().exec_driver_sql(
        f"INSERT INTO ingestion_jobs ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )


@pytest.mark.parametrize("checkpoint_json", ["null", "[]", '"text"', "true", "1"])
def test_checkpoint_database_contract_rejects_non_objects(
    session: Session, checkpoint_json: str
) -> None:
    user, space = create_user_space(session, f"raw-checkpoint-{uuid4().hex}")
    knowledge_base = create_knowledge_base(session, user, space)
    document, version, _, _ = create_document_graph(session, user, space, knowledge_base)

    with pytest.raises(
        IntegrityError, match="ck_ingestion_checkpoint_object_sqlite"
    ):
        _raw_job_insert(
            session,
            user=user,
            space=space,
            knowledge_base=knowledge_base,
            document=document,
            version=version,
            checkpoint_json=checkpoint_json,
        )


def test_checkpoint_rejects_python_none(session: Session) -> None:
    user, space = create_user_space(session, "none-checkpoint")
    knowledge_base = create_knowledge_base(session, user, space)
    document, version, _, _ = create_document_graph(session, user, space, knowledge_base)
    job = _make_job(
        user=user,
        space=space,
        knowledge_base=knowledge_base,
        kind=IngestionJobKind.PARSE_DOCUMENT,
        document=document,
        version=version,
    )
    job.checkpoint = None  # type: ignore[assignment]
    session.add(job)

    with pytest.raises((IntegrityError, StatementError, TypeError, ValueError)):
        session.commit()
