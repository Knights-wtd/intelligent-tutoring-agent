from collections.abc import Generator

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker
from test_knowledge_candidate_models import create_source

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.knowledge.candidate_service import (
    confirm_candidate_batch,
    create_candidate_generation,
)
from tutor_api.knowledge.candidates import CandidateLinkKind, CandidateNoteKind
from tutor_api.knowledge.models import (
    CandidateBatchState,
    DocumentVersionState,
    IngestionJob,
    IngestionJobKind,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
    MarkdownLink,
    MarkdownNote,
    MarkdownRevision,
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    active_session = sessionmaker(bind=engine)()
    try:
        yield active_session
    finally:
        active_session.close()
        engine.dispose()


def test_generation_request_creates_review_batch_and_queued_job(session) -> None:
    owner, _, knowledge_base, _, version = create_source(session)
    version.state = DocumentVersionState.READY

    batch, job = create_candidate_generation(
        session,
        owner,
        knowledge_base.id,
        version.id,
        idempotency_key="wireless-v1",
    )

    assert batch.state is CandidateBatchState.PROCESSING
    assert job.kind is IngestionJobKind.GENERATE_MARKDOWN
    assert job.checkpoint == {"candidate_batch_id": str(batch.id)}
    assert session.scalar(select(func.count()).select_from(MarkdownNote)) == 0


def test_confirmation_publishes_only_hierarchy_as_wikilinks(session) -> None:
    owner, space, knowledge_base, document, version = create_source(session)
    version.state = DocumentVersionState.READY
    batch, _ = create_candidate_generation(
        session,
        owner,
        knowledge_base.id,
        version.id,
        idempotency_key="wireless-confirm",
    )
    batch.state = CandidateBatchState.NEEDS_REVIEW
    chapter = KnowledgeCandidateNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=0,
        candidate_key="ch-3",
        title="移动无线传播",
        normalized_title="移动无线传播",
        kind=CandidateNoteKind.CHAPTER,
        markdown="# 移动无线传播",
        source_pointers=["wireless.docx#block=120"],
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
        source_pointers=["wireless.docx#block=150"],
    )
    session.add_all([chapter, concept])
    session.flush()
    link = KnowledgeCandidateLink(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=0,
        kind=CandidateLinkKind.TERM,
        relation="mentions",
        source_key="ch-3",
        target_key="term-path-loss",
        source_pointer="wireless.docx#block=150",
        occurrence="路径损耗",
        context="后文引用同一概念",
    )
    session.add(link)
    session.flush()

    result = confirm_candidate_batch(
        session,
        owner,
        knowledge_base.id,
        batch.id,
        accepted_note_ids={chapter.id, concept.id},
        accepted_link_ids={link.id},
    )

    assert result.state is CandidateBatchState.CONFIRMED
    assert session.scalar(select(func.count()).select_from(MarkdownNote)) == 2
    assert session.scalar(select(func.count()).select_from(MarkdownRevision)) == 2
    assert session.scalar(select(func.count()).select_from(MarkdownLink)) == 2
    chapter_revision = session.scalar(
        select(MarkdownRevision)
        .join(MarkdownNote, MarkdownNote.id == MarkdownRevision.note_id)
        .where(MarkdownNote.title == "移动无线传播")
    )
    assert chapter_revision is not None
    assert "## 层级导航" in (chapter_revision.markdown or "")
    assert "- contains → [[路径损耗]]" in (chapter_revision.markdown or "")
    assert "## 语义关系（不参与关系图）" in (chapter_revision.markdown or "")
    assert "- mentions → 路径损耗" in (chapter_revision.markdown or "")
    assert "- mentions → [[路径损耗]]" not in (chapter_revision.markdown or "")
    concept_revision = session.scalar(
        select(MarkdownRevision)
        .join(MarkdownNote, MarkdownNote.id == MarkdownRevision.note_id)
        .where(MarkdownNote.title == "路径损耗")
    )
    assert concept_revision is not None
    assert "- 所属结构 → [[移动无线传播]]" in (concept_revision.markdown or "")
    assert version.document_id == document.id


def test_confirmation_rejects_an_accepted_child_without_its_parent(session) -> None:
    owner, space, knowledge_base, _, version = create_source(session)
    version.state = DocumentVersionState.READY
    batch, _ = create_candidate_generation(
        session,
        owner,
        knowledge_base.id,
        version.id,
        idempotency_key="wireless-orphan",
    )
    batch.state = CandidateBatchState.NEEDS_REVIEW
    chapter = KnowledgeCandidateNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=0,
        candidate_key="ch-3",
        title="移动无线传播",
        normalized_title="移动无线传播",
        kind=CandidateNoteKind.CHAPTER,
        markdown="# 移动无线传播",
        source_pointers=["wireless.docx#block=120"],
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
        markdown="# 路径损耗",
        source_pointers=["wireless.docx#block=150"],
    )
    session.add_all([chapter, concept])
    session.flush()

    with pytest.raises(HTTPException) as error:
        confirm_candidate_batch(
            session,
            owner,
            knowledge_base.id,
            batch.id,
            accepted_note_ids={concept.id},
            accepted_link_ids=set(),
        )

    assert error.value.status_code == 409
    assert error.value.detail == "候选笔记必须连同直属父级一起接受"


def test_generation_request_is_idempotent(session) -> None:
    owner, _, knowledge_base, _, version = create_source(session)
    version.state = DocumentVersionState.READY

    first_batch, first_job = create_candidate_generation(
        session,
        owner,
        knowledge_base.id,
        version.id,
        idempotency_key="same-request",
    )
    second_batch, second_job = create_candidate_generation(
        session,
        owner,
        knowledge_base.id,
        version.id,
        idempotency_key="same-request",
    )

    assert second_batch.id == first_batch.id
    assert second_job.id == first_job.id
    assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1
