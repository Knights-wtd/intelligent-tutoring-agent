"""Application services for review-only knowledge candidates."""

from __future__ import annotations

import hashlib
from collections import Counter
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_writable_knowledge_base
from tutor_api.knowledge.candidates import CandidateLinkKind
from tutor_api.knowledge.models import (
    CandidateBatchState,
    CandidateReviewState,
    DocumentVersion,
    DocumentVersionState,
    IngestionJob,
    IngestionJobKind,
    KnowledgeCandidateBatch,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
    MarkdownLink,
    MarkdownNote,
    MarkdownNoteState,
    MarkdownRevision,
    MarkdownRevisionState,
)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")


def _normalize_title(title: str) -> str:
    return " ".join(title.casefold().split())


def _qualified_title(title: str, qualifier: str) -> str:
    suffix = f"（{qualifier}）"
    return f"{title[: 500 - len(suffix)]}{suffix}"


def create_candidate_generation(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    document_version_id: UUID,
    *,
    idempotency_key: str,
) -> tuple[KnowledgeCandidateBatch, IngestionJob]:
    knowledge_base = get_writable_knowledge_base(session, user, knowledge_base_id)
    normalized_key = idempotency_key.strip()
    if not 1 <= len(normalized_key) <= 220:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="幂等键长度必须为 1 到 220 个字符",
        )
    job_key = f"candidate:{normalized_key}"
    existing_job = session.scalar(
        select(IngestionJob).where(
            IngestionJob.knowledge_base_id == knowledge_base.id,
            IngestionJob.idempotency_key == job_key,
        )
    )
    if existing_job is not None:
        raw_batch_id = existing_job.checkpoint.get("candidate_batch_id")
        try:
            batch_id = UUID(raw_batch_id)
        except (TypeError, ValueError, AttributeError):
            raise _conflict("已有生成任务状态无效") from None
        batch = session.get(KnowledgeCandidateBatch, batch_id)
        if batch is None:
            raise _conflict("已有生成任务状态无效")
        return batch, existing_job

    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == document_version_id,
            DocumentVersion.knowledge_base_id == knowledge_base.id,
            DocumentVersion.space_id == knowledge_base.space_id,
        )
    )
    if version is None:
        raise _not_found()
    if version.state is not DocumentVersionState.READY:
        raise _conflict("文档解析完成后才能生成知识候选")

    generation_number = (
        session.scalar(
            select(func.max(KnowledgeCandidateBatch.generation_number)).where(
                KnowledgeCandidateBatch.document_version_id == version.id
            )
        )
        or 0
    ) + 1
    batch = KnowledgeCandidateBatch(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        document_id=version.document_id,
        document_version_id=version.id,
        generation_number=generation_number,
        created_by_user_id=user.id,
    )
    session.add(batch)
    session.flush()
    job = IngestionJob(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        document_id=version.document_id,
        document_version_id=version.id,
        kind=IngestionJobKind.GENERATE_MARKDOWN,
        idempotency_key=job_key,
        checkpoint={"candidate_batch_id": str(batch.id)},
        # Provider reachability flaps for minutes at a time on some networks;
        # six attempts with the worker's minute-level backoff span those windows.
        max_attempts=6,
        created_by_user_id=user.id,
    )
    session.add(job)
    session.flush()
    return batch, job


def confirm_candidate_batch(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    batch_id: UUID,
    *,
    accepted_note_ids: set[UUID],
    accepted_link_ids: set[UUID],
) -> KnowledgeCandidateBatch:
    knowledge_base = get_writable_knowledge_base(session, user, knowledge_base_id)
    batch = session.scalar(
        select(KnowledgeCandidateBatch)
        .where(
            KnowledgeCandidateBatch.id == batch_id,
            KnowledgeCandidateBatch.knowledge_base_id == knowledge_base.id,
            KnowledgeCandidateBatch.space_id == knowledge_base.space_id,
        )
        .with_for_update()
    )
    if batch is None:
        raise _not_found()
    if batch.state is CandidateBatchState.CONFIRMED:
        return batch
    if batch.state is not CandidateBatchState.NEEDS_REVIEW:
        raise _conflict("候选尚未进入可确认状态")

    candidate_notes = list(
        session.scalars(
            select(KnowledgeCandidateNote)
            .where(KnowledgeCandidateNote.batch_id == batch.id)
            .order_by(KnowledgeCandidateNote.ordinal)
        )
    )
    candidate_links = list(
        session.scalars(
            select(KnowledgeCandidateLink)
            .where(KnowledgeCandidateLink.batch_id == batch.id)
            .order_by(KnowledgeCandidateLink.ordinal)
        )
    )
    note_by_id = {note.id: note for note in candidate_notes}
    link_by_id = {link.id: link for link in candidate_links}
    if not accepted_note_ids or not accepted_note_ids <= note_by_id.keys():
        raise _conflict("确认的候选笔记无效")
    if not accepted_link_ids <= link_by_id.keys():
        raise _conflict("确认的候选链接无效")

    accepted_notes = [note for note in candidate_notes if note.id in accepted_note_ids]
    accepted_keys = {note.candidate_key for note in accepted_notes}
    accepted_links = [link for link in candidate_links if link.id in accepted_link_ids]
    if any(
        link.source_key not in accepted_keys or link.target_key not in accepted_keys
        for link in accepted_links
    ):
        raise _conflict("候选链接的两端必须同时被接受")
    if any(
        note.parent_key is not None and note.parent_key not in accepted_keys
        for note in accepted_notes
    ):
        raise _conflict("候选笔记必须连同直属父级一起接受")

    for note in candidate_notes:
        note.review_state = (
            CandidateReviewState.ACCEPTED
            if note.id in accepted_note_ids
            else CandidateReviewState.REJECTED
        )
    for link in candidate_links:
        link.review_state = (
            CandidateReviewState.ACCEPTED
            if link.id in accepted_link_ids
            else CandidateReviewState.REJECTED
        )

    formal_by_key: dict[str, MarkdownNote] = {}
    revision_by_key: dict[str, MarkdownRevision] = {}
    candidate_by_key = {note.candidate_key: note for note in accepted_notes}
    normalized_title_counts = Counter(note.normalized_title for note in accepted_notes)
    published_title_by_key: dict[str, str] = {}
    published_normalized_title_by_key: dict[str, str] = {}
    for candidate in accepted_notes:
        if normalized_title_counts[candidate.normalized_title] == 1:
            published_title = candidate.title
        else:
            parent = (
                candidate_by_key.get(candidate.parent_key)
                if candidate.parent_key is not None
                else None
            )
            qualifier = parent.title if parent is not None else str(candidate.ordinal + 1)
            published_title = _qualified_title(candidate.title, qualifier)
        published_title_by_key[candidate.candidate_key] = published_title
        published_normalized_title_by_key[candidate.candidate_key] = _normalize_title(
            published_title
        )
    children_by_parent: dict[str, list[KnowledgeCandidateNote]] = {}
    for note in accepted_notes:
        if note.parent_key is not None:
            children_by_parent.setdefault(note.parent_key, []).append(note)
    semantic_links_by_source: dict[str, list[KnowledgeCandidateLink]] = {}
    for link in accepted_links:
        is_direct_child = (
            link.kind is CandidateLinkKind.STRUCTURE
            and link.relation == "contains"
            and candidate_by_key[link.target_key].parent_key == link.source_key
        )
        if not is_direct_child:
            semantic_links_by_source.setdefault(link.source_key, []).append(link)

    for candidate in accepted_notes:
        published_normalized_title = published_normalized_title_by_key[candidate.candidate_key]
        existing = session.scalar(
            select(MarkdownNote).where(
                MarkdownNote.knowledge_base_id == knowledge_base.id,
                MarkdownNote.normalized_title == published_normalized_title,
            )
        )
        if existing is not None:
            raise _conflict("知识库中已存在同名正式笔记")
        note = MarkdownNote(
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            source_document_id=batch.document_id,
            title=published_title_by_key[candidate.candidate_key],
            normalized_title=published_normalized_title,
            state=MarkdownNoteState.PUBLISHED,
            created_by_user_id=user.id,
        )
        session.add(note)
        formal_by_key[candidate.candidate_key] = note
    session.flush()

    for candidate in accepted_notes:
        hierarchy_lines: list[str] = []
        if candidate.parent_key is not None:
            hierarchy_lines.append(
                f"- 所属结构 → [[{published_title_by_key[candidate.parent_key]}]]"
            )
        hierarchy_lines.extend(
            f"- contains → [[{published_title_by_key[child.candidate_key]}]]"
            for child in children_by_parent.get(candidate.candidate_key, [])
        )
        semantic_lines = [
            f"- {link.relation} → {published_title_by_key[link.target_key]}"
            for link in semantic_links_by_source.get(candidate.candidate_key, [])
        ]
        markdown = candidate.markdown.rstrip()
        if hierarchy_lines:
            markdown += "\n\n## 层级导航\n\n" + "\n".join(hierarchy_lines)
        if semantic_lines:
            markdown += "\n\n## 语义关系（不参与关系图）\n\n" + "\n".join(semantic_lines)
        revision = MarkdownRevision(
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            note_id=formal_by_key[candidate.candidate_key].id,
            source_document_id=batch.document_id,
            source_document_version_id=batch.document_version_id,
            revision_number=1,
            state=MarkdownRevisionState.PUBLISHED,
            markdown=markdown,
            content_sha256=hashlib.sha256(markdown.encode()).hexdigest(),
            source_markers=list(candidate.source_pointers),
            generation_provider=batch.generation_provider,
            generation_model=batch.generation_model,
            generation_request_id=batch.generation_request_id,
            created_by_user_id=user.id,
        )
        session.add(revision)
        revision_by_key[candidate.candidate_key] = revision
    session.flush()

    link_ordinal_by_source: dict[str, int] = {}
    for child in accepted_notes:
        if child.parent_key is None:
            continue
        for source_key, target_key in (
            (child.candidate_key, child.parent_key),
            (child.parent_key, child.candidate_key),
        ):
            ordinal = link_ordinal_by_source.get(source_key, 0)
            session.add(
                MarkdownLink(
                    space_id=knowledge_base.space_id,
                    knowledge_base_id=knowledge_base.id,
                    source_note_id=formal_by_key[source_key].id,
                    source_revision_id=revision_by_key[source_key].id,
                    ordinal=ordinal,
                    target_note_id=formal_by_key[target_key].id,
                    target_title=published_title_by_key[target_key],
                )
            )
            link_ordinal_by_source[source_key] = ordinal + 1

    batch.state = CandidateBatchState.CONFIRMED
    batch.failure_code = None
    session.flush()
    return batch
