"""Read-only projections of confirmed, accepted knowledge candidates."""

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_readable_knowledge_base
from tutor_api.knowledge.models import (
    CandidateBatchState,
    CandidateReviewState,
    KnowledgeCandidateBatch,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
    MarkdownNote,
)


@dataclass(frozen=True, slots=True)
class KnowledgeGraphNode:
    id: UUID
    note_id: UUID | None
    title: str
    kind: str
    source_pointers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeGraphEdge:
    id: UUID
    source_id: UUID
    target_id: UUID
    kind: str
    relation: str
    source_pointer: str


@dataclass(frozen=True, slots=True)
class KnowledgeGraph:
    knowledge_base_id: UUID
    nodes: tuple[KnowledgeGraphNode, ...]
    edges: tuple[KnowledgeGraphEdge, ...]


def _normalize_title(title: str) -> str:
    return " ".join(title.casefold().split())


def _qualified_title(title: str, qualifier: str) -> str:
    suffix = f"（{qualifier}）"
    return f"{title[: 500 - len(suffix)]}{suffix}"


def _published_titles(notes: tuple[KnowledgeCandidateNote, ...]) -> dict[UUID, str]:
    notes_by_batch: dict[UUID, list[KnowledgeCandidateNote]] = {}
    for note in notes:
        notes_by_batch.setdefault(note.batch_id, []).append(note)
    result: dict[UUID, str] = {}
    for batch_notes in notes_by_batch.values():
        counts = Counter(note.normalized_title for note in batch_notes)
        by_key = {note.candidate_key: note for note in batch_notes}
        for note in batch_notes:
            if counts[note.normalized_title] == 1:
                result[note.id] = note.title
                continue
            parent = by_key.get(note.parent_key) if note.parent_key is not None else None
            qualifier = parent.title if parent is not None else str(note.ordinal + 1)
            result[note.id] = _qualified_title(note.title, qualifier)
    return result


def load_knowledge_graph(
    session: Session, user: User, knowledge_base_id: UUID
) -> KnowledgeGraph:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    notes = tuple(
        session.scalars(
            select(KnowledgeCandidateNote)
            .join(KnowledgeCandidateBatch)
            .where(
                KnowledgeCandidateNote.knowledge_base_id == knowledge_base.id,
                KnowledgeCandidateNote.space_id == knowledge_base.space_id,
                KnowledgeCandidateNote.review_state == CandidateReviewState.ACCEPTED,
                KnowledgeCandidateBatch.state == CandidateBatchState.CONFIRMED,
            )
            .order_by(
                KnowledgeCandidateNote.created_at,
                KnowledgeCandidateNote.ordinal,
                KnowledgeCandidateNote.id,
            )
        )
    )
    batches = {
        batch.id: batch
        for batch in session.scalars(
            select(KnowledgeCandidateBatch).where(
                KnowledgeCandidateBatch.id.in_({note.batch_id for note in notes})
            )
        )
    } if notes else {}
    published_notes = tuple(
        session.scalars(
            select(MarkdownNote).where(
                MarkdownNote.knowledge_base_id == knowledge_base.id,
                MarkdownNote.space_id == knowledge_base.space_id,
            )
        )
    )
    formal_by_source_and_title = {
        (note.source_document_id, note.normalized_title): note.id for note in published_notes
    }
    published_title_by_candidate_id = _published_titles(notes)
    nodes = tuple(
        KnowledgeGraphNode(
            id=note.id,
            note_id=formal_by_source_and_title.get(
                (
                    batches[note.batch_id].document_id,
                    _normalize_title(published_title_by_candidate_id[note.id]),
                )
            ),
            title=note.title,
            kind=note.kind.value,
            source_pointers=tuple(note.source_pointers),
        )
        for note in notes
    )
    node_ids = {(note.batch_id, note.candidate_key): note.id for note in notes}
    links = session.scalars(
        select(KnowledgeCandidateLink)
        .join(KnowledgeCandidateBatch)
        .where(
            KnowledgeCandidateLink.knowledge_base_id == knowledge_base.id,
            KnowledgeCandidateLink.space_id == knowledge_base.space_id,
            KnowledgeCandidateLink.review_state == CandidateReviewState.ACCEPTED,
            KnowledgeCandidateBatch.state == CandidateBatchState.CONFIRMED,
        )
        .order_by(
            KnowledgeCandidateLink.created_at,
            KnowledgeCandidateLink.ordinal,
            KnowledgeCandidateLink.id,
        )
    )
    edges = tuple(
        KnowledgeGraphEdge(
            id=link.id,
            source_id=node_ids[(link.batch_id, link.source_key)],
            target_id=node_ids[(link.batch_id, link.target_key)],
            kind=link.kind.value,
            relation=link.relation,
            source_pointer=link.source_pointer,
        )
        for link in links
        if (link.batch_id, link.source_key) in node_ids
        and (link.batch_id, link.target_key) in node_ids
    )
    return KnowledgeGraph(
        knowledge_base_id=knowledge_base.id,
        nodes=nodes,
        edges=edges,
    )
