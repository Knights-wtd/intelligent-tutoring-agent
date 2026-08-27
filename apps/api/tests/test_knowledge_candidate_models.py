from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.candidates import CandidateLinkKind, CandidateNoteKind
from tutor_api.knowledge.models import (
    CandidateBatchState,
    CandidateReviewState,
    Document,
    DocumentVersion,
    KnowledgeBase,
    KnowledgeCandidateBatch,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
    MarkdownLink,
    MarkdownNote,
)
from tutor_api.spaces.models import Space, SpaceKind


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    active_session = sessionmaker(bind=engine)()
    try:
        yield active_session
    finally:
        active_session.close()
        engine.dispose()


def create_source(session: Session) -> tuple[User, Space, KnowledgeBase, Document, DocumentVersion]:
    owner = User(email="candidate@example.com", username="candidate", password_hash="hash")
    session.add(owner)
    session.flush()
    space = Space(owner_id=owner.id, kind=SpaceKind.PERSONAL, name="Candidate space")
    session.add(space)
    session.flush()
    knowledge_base = KnowledgeBase(
        space_id=space.id,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        name="Candidate knowledge base",
    )
    session.add(knowledge_base)
    session.flush()
    document = Document(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        title="无线通信原理与应用",
        source_kind="upload",
        source_key="wireless.docx",
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        version_number=1,
        content_sha256="a" * 64,
        object_key="knowledge/wireless.docx",
        content_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        created_by_user_id=owner.id,
    )
    session.add(version)
    session.flush()
    return owner, space, knowledge_base, document, version


def test_candidates_remain_separate_from_formal_notes_and_links_until_confirmation(
    session: Session,
) -> None:
    owner, space, knowledge_base, document, version = create_source(session)
    batch = KnowledgeCandidateBatch(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        document_version_id=version.id,
        generation_number=1,
        state=CandidateBatchState.NEEDS_REVIEW,
        created_by_user_id=owner.id,
    )
    session.add(batch)
    session.flush()
    chapter = KnowledgeCandidateNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=0,
        candidate_key="ch-3",
        title="移动无线传播",
        normalized_title="移动无线传播",
        kind=CandidateNoteKind.CHAPTER,
        parent_key=None,
        markdown="# 移动无线传播",
        source_pointers=["wireless.docx#block=120"],
        review_state=CandidateReviewState.PENDING,
    )
    concept = KnowledgeCandidateNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=1,
        candidate_key="term-path-loss",
        title="路径损耗",
        normalized_title="路径损耗",
        kind=CandidateNoteKind.CONCEPT,
        parent_key="ch-3",
        markdown="# 路径损耗\n\n定义候选。",
        source_pointers=["wireless.docx#block=150", "wireless.docx#block=880"],
        review_state=CandidateReviewState.PENDING,
    )
    session.add_all([chapter, concept])
    session.flush()
    session.add(
        KnowledgeCandidateLink(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            batch_id=batch.id,
            ordinal=0,
            kind=CandidateLinkKind.TERM,
            relation="mentions",
            source_key="ch-3",
            target_key="term-path-loss",
            source_pointer="wireless.docx#block=880",
            occurrence="路径损耗",
            context="后文引用同一概念",
            review_state=CandidateReviewState.PENDING,
        )
    )
    session.commit()

    assert session.scalar(select(func.count()).select_from(KnowledgeCandidateNote)) == 2
    assert session.scalar(select(func.count()).select_from(KnowledgeCandidateLink)) == 1
    assert session.scalar(select(func.count()).select_from(MarkdownNote)) == 0
    assert session.scalar(select(func.count()).select_from(MarkdownLink)) == 0


def test_candidate_link_cannot_reference_a_note_from_another_batch(session: Session) -> None:
    owner, space, knowledge_base, document, version = create_source(session)
    batches = [
        KnowledgeCandidateBatch(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            document_version_id=version.id,
            generation_number=index,
            state=CandidateBatchState.NEEDS_REVIEW,
            created_by_user_id=owner.id,
        )
        for index in (1, 2)
    ]
    session.add_all(batches)
    session.flush()
    session.add_all(
        [
            KnowledgeCandidateNote(
                space_id=space.id,
                knowledge_base_id=knowledge_base.id,
                batch_id=batch.id,
                ordinal=0,
                candidate_key=key,
                title=key,
                normalized_title=key,
                kind=CandidateNoteKind.CONCEPT,
                markdown=f"# {key}",
                source_pointers=[f"wireless.docx#{key}"],
            )
            for batch, key in zip(batches, ("source", "target"), strict=True)
        ]
    )
    session.flush()
    session.add(
        KnowledgeCandidateLink(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            batch_id=batches[0].id,
            ordinal=0,
            kind=CandidateLinkKind.TERM,
            relation="mentions",
            source_key="source",
            target_key="target",
            source_pointer="wireless.docx#source",
            occurrence="target",
            context="cross-batch reference",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_candidate_tables_are_created_by_the_committed_graph_foundation() -> None:
    migration_path = (
        Path(__file__).parents[1] / "migrations" / "versions" / "0009_candidate_graph_foundation.py"
    )

    source = migration_path.read_text(encoding="utf-8")

    assert 'revision: str = "0009_candidate_graph_foundation"' in source
    assert 'down_revision: str | Sequence[str] | None = "0008_embedding_contract"' in source
    assert '"knowledge_candidate_batches"' in source
    assert '"knowledge_candidate_notes"' in source
    assert '"knowledge_candidate_links"' in source
    assert source.index('op.drop_table("knowledge_candidate_links")') < source.index(
        'op.drop_table("knowledge_candidate_batches")'
    )


def test_formula_evidence_has_an_additive_migration_after_candidates() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0014_candidate_formula_evidence.py"
    )

    source = migration_path.read_text(encoding="utf-8")

    assert 'revision: str = "0014_candidate_formula_evidence"' in source
    assert 'down_revision: str | Sequence[str] | None = "0013_markdown_job_kinds"' in source
    assert '"formula_verification"' in source
    assert '"external_sources"' in source
    assert KnowledgeCandidateNote.__table__.c.formula_verification.nullable is True
    assert KnowledgeCandidateNote.__table__.c.external_sources.nullable is False