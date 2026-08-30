"""Read-only projections of confirmed, accepted knowledge candidates."""

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
)


@dataclass(frozen=True, slots=True)
class KnowledgeGraphNode:
    id: UUID
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
    nodes = tuple(
        KnowledgeGraphNode(
            id=note.id,
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
