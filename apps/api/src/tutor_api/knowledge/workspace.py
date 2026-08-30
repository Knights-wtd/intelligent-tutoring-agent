"""Route-aware projections for the knowledge workspace."""

import hashlib
import re
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_readable_knowledge_base
from tutor_api.knowledge.models import (
    CandidateBatchState,
    Document,
    DocumentState,
    DocumentVersion,
    KnowledgeCandidateBatch,
    MarkdownNote,
    MarkdownNoteState,
    MarkdownRevision,
    MarkdownRevisionState,
)
from tutor_api.knowledge.service import get_document_processing_state
from tutor_api.vault.migration import (
    MigrationPhase,
    MigrationRoute,
    knowledge_base_vault_root,
    migration_route_for_knowledge_base,
    resolve_vault_path,
)
from tutor_api.vault.models import VaultFile

_PARENT_PATTERN = re.compile(r"所属结构\s*→\s*\[\[([^\]]+)\]\]")


@dataclass(frozen=True, slots=True)
class WorkspaceDocument:
    document_id: UUID
    document_version_id: UUID
    source_name: str
    content_type: str
    processing_state: str
    created_at: object
    updated_at: object


@dataclass(frozen=True, slots=True)
class NoteSummary:
    id: UUID
    title: str
    kind: str
    parent_id: UUID | None
    source_document_id: UUID | None
    updated_at: object


@dataclass(frozen=True, slots=True)
class KnowledgeWorkspace:
    knowledge_base_id: UUID
    documents: tuple[WorkspaceDocument, ...]
    candidate_batch: KnowledgeCandidateBatch | None
    notes: tuple[NoteSummary, ...]


@dataclass(frozen=True, slots=True)
class NoteReference:
    id: UUID
    title: str


@dataclass(frozen=True, slots=True)
class PublishedNoteDetail:
    id: UUID
    title: str
    kind: str
    markdown: str
    source_markers: tuple[str, ...]
    source_document_id: UUID | None
    source_name: str | None
    parent: NoteReference | None
    children: tuple[NoteReference, ...]
    updated_at: object


def _published_note_rows(session: Session, knowledge_base_id: UUID, space_id: UUID):
    return list(
        session.execute(
            select(MarkdownNote, MarkdownRevision, Document)
            .join(
                MarkdownRevision,
                (MarkdownRevision.note_id == MarkdownNote.id)
                & (MarkdownRevision.knowledge_base_id == MarkdownNote.knowledge_base_id)
                & (MarkdownRevision.space_id == MarkdownNote.space_id),
            )
            .outerjoin(
                Document,
                (Document.id == MarkdownRevision.source_document_id)
                & (Document.knowledge_base_id == MarkdownRevision.knowledge_base_id)
                & (Document.space_id == MarkdownRevision.space_id),
            )
            .where(
                MarkdownNote.knowledge_base_id == knowledge_base_id,
                MarkdownNote.space_id == space_id,
                MarkdownNote.state == MarkdownNoteState.PUBLISHED,
                MarkdownRevision.state == MarkdownRevisionState.PUBLISHED,
            )
            .order_by(MarkdownNote.title, MarkdownNote.id)
        )
    )


def _parent_title(markdown: str | None) -> str | None:
    if not markdown:
        return None
    match = _PARENT_PATTERN.search(markdown)
    return match.group(1).strip() if match else None


def _vault_read_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="知识库内容暂不可用",
    )


def _effective_markdown(
    session: Session,
    note: MarkdownNote,
    revision: MarkdownRevision,
    route: MigrationRoute | None,
) -> str:
    if route is None or route.phase is not MigrationPhase.VAULT_AUTHORITATIVE:
        return revision.markdown or ""
    if note.vault_file_id is None or note.vault_relative_path is None:
        raise _vault_read_unavailable()
    vault_file = session.get(VaultFile, note.vault_file_id)
    if (
        vault_file is None
        or vault_file.knowledge_base_id != note.knowledge_base_id
        or vault_file.space_id != note.space_id
        or vault_file.relative_path != note.vault_relative_path
        or vault_file.is_tombstoned
    ):
        raise _vault_read_unavailable()
    try:
        raw = resolve_vault_path(
            knowledge_base_vault_root(
                route.vault_root, note.space_id, note.knowledge_base_id
            ),
            vault_file.relative_path,
        ).read_bytes()
    except (OSError, RuntimeError):
        raise _vault_read_unavailable() from None
    if (
        len(raw) != vault_file.size_bytes
        or hashlib.sha256(raw).hexdigest() != vault_file.content_hash
    ):
        raise _vault_read_unavailable()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _vault_read_unavailable() from None


def _effective_markdown_by_note(session: Session, knowledge_base_id: UUID, rows) -> dict[UUID, str]:
    route = migration_route_for_knowledge_base(session, knowledge_base_id)
    return {
        note.id: _effective_markdown(session, note, revision, route) for note, revision, _ in rows
    }


def _note_hierarchy(
    rows, markdown_by_note: dict[UUID, str]
) -> tuple[dict[UUID, UUID | None], dict[UUID, list[UUID]]]:
    note_by_title = {note.title: note for note, _, _ in rows}
    parent_by_id: dict[UUID, UUID | None] = {}
    children_by_id: dict[UUID, list[UUID]] = {note.id: [] for note, _, _ in rows}
    for note, _, _ in rows:
        title = _parent_title(markdown_by_note[note.id])
        parent = note_by_title.get(title) if title is not None else None
        parent_id = parent.id if parent is not None and parent.id != note.id else None
        parent_by_id[note.id] = parent_id
        if parent_id is not None:
            children_by_id.setdefault(parent_id, []).append(note.id)
    return parent_by_id, children_by_id


def _ordered_note_ids(rows, parent_by_id: dict[UUID, UUID | None]) -> tuple[UUID, ...]:
    notes = {note.id: note for note, _, _ in rows}
    children: dict[UUID | None, list[UUID]] = {}
    for note_id, parent_id in parent_by_id.items():
        children.setdefault(parent_id if parent_id in notes else None, []).append(note_id)
    for values in children.values():
        values.sort(key=lambda note_id: (notes[note_id].title, str(note_id)))
    ordered: list[UUID] = []
    visited: set[UUID] = set()

    def visit(note_id: UUID) -> None:
        if note_id in visited:
            return
        visited.add(note_id)
        ordered.append(note_id)
        for child_id in children.get(note_id, []):
            visit(child_id)

    for root_id in children.get(None, []):
        visit(root_id)
    for note_id in sorted(notes, key=lambda value: (notes[value].title, str(value))):
        visit(note_id)
    return tuple(ordered)


def load_knowledge_workspace(
    session: Session, user: User, knowledge_base_id: UUID
) -> KnowledgeWorkspace:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    version_rows = list(
        session.execute(
            select(Document, DocumentVersion)
            .join(
                DocumentVersion,
                (DocumentVersion.document_id == Document.id)
                & (DocumentVersion.knowledge_base_id == Document.knowledge_base_id)
                & (DocumentVersion.space_id == Document.space_id),
            )
            .where(
                Document.knowledge_base_id == knowledge_base.id,
                Document.space_id == knowledge_base.space_id,
                Document.state == DocumentState.ACTIVE,
            )
            .order_by(Document.title, Document.id, DocumentVersion.version_number.desc())
        )
    )
    latest_rows = []
    seen_documents: set[UUID] = set()
    for document, version in version_rows:
        if document.id in seen_documents:
            continue
        seen_documents.add(document.id)
        latest_rows.append((document, version))
    documents = tuple(
        WorkspaceDocument(
            document_id=document.id,
            document_version_id=version.id,
            source_name=document.source_key,
            content_type=version.content_type,
            processing_state=get_document_processing_state(
                session, user, knowledge_base.id, document.id, version.id
            ),
            created_at=version.created_at,
            updated_at=version.updated_at,
        )
        for document, version in latest_rows
    )
    state_priority = case(
        (KnowledgeCandidateBatch.state == CandidateBatchState.PROCESSING, 0),
        (KnowledgeCandidateBatch.state == CandidateBatchState.NEEDS_REVIEW, 1),
        (KnowledgeCandidateBatch.state == CandidateBatchState.FAILED, 2),
        (KnowledgeCandidateBatch.state == CandidateBatchState.CONFIRMED, 3),
        else_=4,
    )
    candidate_batch = session.scalar(
        select(KnowledgeCandidateBatch)
        .where(
            KnowledgeCandidateBatch.knowledge_base_id == knowledge_base.id,
            KnowledgeCandidateBatch.space_id == knowledge_base.space_id,
        )
        .order_by(
            state_priority, KnowledgeCandidateBatch.created_at.desc(), KnowledgeCandidateBatch.id
        )
        .limit(1)
    )
    rows = _published_note_rows(session, knowledge_base.id, knowledge_base.space_id)
    markdown_by_note = _effective_markdown_by_note(session, knowledge_base.id, rows)
    parent_by_id, _ = _note_hierarchy(rows, markdown_by_note)
    row_by_note_id = {note.id: (note, revision) for note, revision, _ in rows}
    notes = tuple(
        NoteSummary(
            id=note_id,
            title=row_by_note_id[note_id][0].title,
            kind="note",
            parent_id=parent_by_id.get(note_id),
            source_document_id=row_by_note_id[note_id][0].source_document_id,
            updated_at=row_by_note_id[note_id][1].updated_at,
        )
        for note_id in _ordered_note_ids(rows, parent_by_id)
    )
    return KnowledgeWorkspace(knowledge_base.id, documents, candidate_batch, notes)


def load_published_note(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    note_id: UUID,
) -> PublishedNoteDetail:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    rows = _published_note_rows(session, knowledge_base.id, knowledge_base.space_id)
    selected = next((row for row in rows if row[0].id == note_id), None)
    if selected is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")
    markdown_by_note = _effective_markdown_by_note(session, knowledge_base.id, rows)
    parent_by_id, children_by_id = _note_hierarchy(rows, markdown_by_note)
    note_by_id = {note.id: note for note, _, _ in rows}
    note, revision, document = selected
    parent_id = parent_by_id.get(note.id)
    parent_note = note_by_id.get(parent_id) if parent_id is not None else None
    child_ids = children_by_id.get(note.id, [])
    child_ids.sort(key=lambda child_id: (note_by_id[child_id].title, str(child_id)))
    return PublishedNoteDetail(
        id=note.id,
        title=note.title,
        kind="note",
        markdown=markdown_by_note[note.id],
        source_markers=tuple(revision.source_markers),
        source_document_id=revision.source_document_id,
        source_name=document.source_key if document is not None else None,
        parent=(
            NoteReference(parent_note.id, parent_note.title) if parent_note is not None else None
        ),
        children=tuple(
            NoteReference(note_by_id[child_id].id, note_by_id[child_id].title)
            for child_id in child_ids
        ),
        updated_at=revision.updated_at,
    )
