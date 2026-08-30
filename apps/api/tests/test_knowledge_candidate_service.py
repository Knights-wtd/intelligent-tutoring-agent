from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker
from test_knowledge_candidate_models import create_source

from tutor_api.agent import models as agent_models  # noqa: F401
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
from tutor_api.knowledge.storage import MemoryObjectStorage
from tutor_api.vault.migration import MigrationPhase, VaultMigrator
from tutor_api.vault.models import VaultChangeSet, VaultChangeSource


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


def test_confirmation_qualifies_duplicate_titles_with_their_parent(session) -> None:
    owner, space, knowledge_base, _, version = create_source(session)
    version.state = DocumentVersionState.READY
    batch, _ = create_candidate_generation(
        session,
        owner,
        knowledge_base.id,
        version.id,
        idempotency_key="duplicate-section-titles",
    )
    batch.state = CandidateBatchState.NEEDS_REVIEW
    part_four = KnowledgeCandidateNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=0,
        candidate_key="part-4",
        title="第四部分：直接配置 Claude Code",
        normalized_title="第四部分：直接配置 claude code",
        kind=CandidateNoteKind.CHAPTER,
        markdown="# 第四部分：直接配置 Claude Code",
        source_pointers=["guide.md#part-4"],
    )
    part_five = KnowledgeCandidateNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=1,
        candidate_key="part-5",
        title="第五部分：直接配置 Codex",
        normalized_title="第五部分：直接配置 codex",
        kind=CandidateNoteKind.CHAPTER,
        markdown="# 第五部分：直接配置 Codex",
        source_pointers=["guide.md#part-5"],
    )
    claude_location = KnowledgeCandidateNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=2,
        candidate_key="claude-config-location",
        title="配置文件位置",
        normalized_title="配置文件位置",
        kind=CandidateNoteKind.SECTION,
        parent_key=part_four.candidate_key,
        markdown="# 配置文件位置\n\nClaude 配置路径。",
        source_pointers=["guide.md#claude-location"],
    )
    codex_location = KnowledgeCandidateNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=3,
        candidate_key="codex-config-location",
        title="配置文件位置",
        normalized_title="配置文件位置",
        kind=CandidateNoteKind.SECTION,
        parent_key=part_five.candidate_key,
        markdown="# 配置文件位置\n\nCodex 配置路径。",
        source_pointers=["guide.md#codex-location"],
    )
    notes = [part_four, part_five, claude_location, codex_location]
    session.add_all(notes)
    session.flush()

    result = confirm_candidate_batch(
        session,
        owner,
        knowledge_base.id,
        batch.id,
        accepted_note_ids={note.id for note in notes},
        accepted_link_ids=set(),
    )

    assert result.state is CandidateBatchState.CONFIRMED
    published_titles = set(session.scalars(select(MarkdownNote.title)))
    assert "配置文件位置（第四部分：直接配置 Claude Code）" in published_titles
    assert "配置文件位置（第五部分：直接配置 Codex）" in published_titles
    part_four_revision = session.scalar(
        select(MarkdownRevision)
        .join(MarkdownNote, MarkdownNote.id == MarkdownRevision.note_id)
        .where(MarkdownNote.title == "第四部分：直接配置 Claude Code")
    )
    assert part_four_revision is not None
    assert "[[配置文件位置（第四部分：直接配置 Claude Code）]]" in part_four_revision.markdown


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


def test_shadow_route_dual_writes_legacy_candidate_confirmation_and_allows_cutover(
    session: Session, tmp_path: Path
) -> None:
    owner, space, knowledge_base, _, version = create_source(session)
    version.state = DocumentVersionState.READY
    migration = VaultMigrator(
        session=session,
        object_storage=MemoryObjectStorage(),
        vault_root=tmp_path / "vault",
        artifact_root=tmp_path / "artifacts",
    )
    manifest = migration.inventory(knowledge_base_id=knowledge_base.id)
    migration.copy(manifest)
    migration.verify(manifest)
    assert migration.activate_shadow(manifest).phase is MigrationPhase.SHADOW

    batch, _ = create_candidate_generation(
        session,
        owner,
        knowledge_base.id,
        version.id,
        idempotency_key="shadow-dual-write",
    )
    batch.state = CandidateBatchState.NEEDS_REVIEW
    candidate = KnowledgeCandidateNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=batch.id,
        ordinal=0,
        candidate_key="shadow-note",
        title="Shadow note",
        normalized_title="shadow note",
        kind=CandidateNoteKind.CONCEPT,
        markdown="# Shadow\n\nMirrored body.",
        source_pointers=["source.md#shadow"],
    )
    session.add(candidate)
    session.flush()

    confirm_candidate_batch(
        session,
        owner,
        knowledge_base.id,
        batch.id,
        accepted_note_ids={candidate.id},
        accepted_link_ids=set(),
    )

    note = session.scalar(select(MarkdownNote).where(MarkdownNote.title == "Shadow note"))
    revision = session.scalar(
        select(MarkdownRevision).where(MarkdownRevision.note_id == note.id)
    )
    assert note is not None and revision is not None
    assert note.vault_file_id is not None
    assert revision.change_set_id is not None
    shadow_change = session.get(VaultChangeSet, revision.change_set_id)
    assert shadow_change is not None
    assert shadow_change.source is VaultChangeSource.API
    target = migration.scoped_vault_root(manifest) / note.vault_relative_path
    assert target.read_text(encoding="utf-8") == revision.markdown
    assert migration.cutover(manifest).phase is MigrationPhase.VAULT_AUTHORITATIVE
