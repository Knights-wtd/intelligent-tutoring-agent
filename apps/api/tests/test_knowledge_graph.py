from collections.abc import Generator
from dataclasses import fields
from datetime import UTC, datetime
from uuid import UUID
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.candidates import CandidateLinkKind, CandidateNoteKind
from tutor_api.knowledge.graph import KnowledgeGraph, load_knowledge_graph
from tutor_api.knowledge.models import (
    CandidateBatchState,
    CandidateReviewState,
    Document,
    DocumentVersion,
    KnowledgeBase,
    KnowledgeCandidateBatch,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
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


def create_user(session: Session, email: str) -> User:
    username = email.split("@", maxsplit=1)[0]
    user = User(email=email, username=username, password_hash="hash")
    session.add(user)
    session.flush()
    return user


def seed_graph_batch(
    session: Session,
    user: User,
    space: Space,
    knowledge_base: KnowledgeBase,
    document: Document,
    version: DocumentVersion,
) -> tuple[KnowledgeCandidateBatch, KnowledgeCandidateNote, KnowledgeCandidateNote, KnowledgeCandidateLink]:
    batch = KnowledgeCandidateBatch(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        document_version_id=version.id,
        generation_number=1,
        state=CandidateBatchState.CONFIRMED,
        created_by_user_id=user.id,
    )
    session.add(batch)
    session.flush()
    chapter = KnowledgeCandidateNote(
        space_id=space.id, knowledge_base_id=knowledge_base.id, batch_id=batch.id, ordinal=0,
        candidate_key="chapter", title="移动无线传播", normalized_title="移动无线传播",
        kind=CandidateNoteKind.CHAPTER, markdown="# 移动无线传播",
        source_pointers=["wireless.docx#block=120"], review_state=CandidateReviewState.ACCEPTED,
    )
    concept = KnowledgeCandidateNote(
        space_id=space.id, knowledge_base_id=knowledge_base.id, batch_id=batch.id, ordinal=1,
        candidate_key="path-loss", title="路径损耗", normalized_title="路径损耗",
        kind=CandidateNoteKind.CONCEPT, parent_key="chapter", markdown="# 路径损耗",
        source_pointers=["wireless.docx#block=150"], review_state=CandidateReviewState.ACCEPTED,
    )
    rejected_note = KnowledgeCandidateNote(
        space_id=space.id, knowledge_base_id=knowledge_base.id, batch_id=batch.id, ordinal=2,
        candidate_key="rejected", title="忽略", normalized_title="忽略", kind=CandidateNoteKind.CONCEPT,
        markdown="# 忽略", source_pointers=[], review_state=CandidateReviewState.REJECTED,
    )
    session.add_all([chapter, concept, rejected_note])
    session.flush()
    link = KnowledgeCandidateLink(
        space_id=space.id, knowledge_base_id=knowledge_base.id, batch_id=batch.id, ordinal=0,
        kind=CandidateLinkKind.TERM, relation="mentions", source_key="chapter", target_key="path-loss",
        source_pointer="wireless.docx#block=150", occurrence="路径损耗", context="提及路径损耗",
        review_state=CandidateReviewState.ACCEPTED,
    )
    rejected_link = KnowledgeCandidateLink(
        space_id=space.id, knowledge_base_id=knowledge_base.id, batch_id=batch.id, ordinal=1,
        kind=CandidateLinkKind.TERM, relation="mentions", source_key="chapter", target_key="rejected",
        source_pointer="wireless.docx#block=160", occurrence="忽略", context="拒绝链接",
        review_state=CandidateReviewState.REJECTED,
    )
    session.add_all([link, rejected_link])
    review_batch = KnowledgeCandidateBatch(
        space_id=space.id, knowledge_base_id=knowledge_base.id, document_id=document.id,
        document_version_id=version.id, generation_number=2, state=CandidateBatchState.NEEDS_REVIEW,
        created_by_user_id=user.id,
    )
    session.add(review_batch)
    session.flush()
    session.add(
        KnowledgeCandidateNote(
            space_id=space.id, knowledge_base_id=knowledge_base.id, batch_id=review_batch.id, ordinal=0,
            candidate_key="draft", title="草稿", normalized_title="草稿", kind=CandidateNoteKind.CONCEPT,
            markdown="# 草稿", source_pointers=[], review_state=CandidateReviewState.ACCEPTED,
        )
    )
    session.commit()
    return batch, chapter, concept, link


def test_graph_returns_accepted_candidates_from_the_requested_confirmed_batch(session: Session) -> None:
    owner, space, knowledge_base, document, version = create_source(session)
    batch, chapter, concept, link = seed_graph_batch(
        session, owner, space, knowledge_base, document, version
    )

    graph = load_knowledge_graph(session, owner, knowledge_base.id)

    assert [(node.id, node.title, node.kind, node.source_pointers) for node in graph.nodes] == [
        (chapter.id, "移动无线传播", "chapter", ("wireless.docx#block=120",)),
        (concept.id, "路径损耗", "concept", ("wireless.docx#block=150",)),
    ]
    assert [(edge.id, edge.source_id, edge.target_id, edge.kind, edge.relation, edge.source_pointer) for edge in graph.edges] == [
        (link.id, chapter.id, concept.id, "term", "mentions", "wireless.docx#block=150")
    ]
    assert graph.knowledge_base_id == knowledge_base.id
    assert tuple(field.name for field in fields(KnowledgeGraph)) == (
        "knowledge_base_id", "nodes", "edges"
    )
    assert batch.state is CandidateBatchState.CONFIRMED


def test_graph_is_not_readable_by_an_outsider(session: Session) -> None:
    owner, space, knowledge_base, document, version = create_source(session)
    seed_graph_batch(session, owner, space, knowledge_base, document, version)
    outsider = create_user(session, "outsider@example.com")

    with pytest.raises(HTTPException) as error:
        load_knowledge_graph(session, outsider, knowledge_base.id)

    assert error.value.status_code == 404


def test_graph_orders_identical_timestamps_and_batch_ordinals_deterministically(
    session: Session,
) -> None:
    owner, space, knowledge_base, document, version = create_source(session)
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    first_batch = KnowledgeCandidateBatch(
        id=UUID(int=2),
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        document_version_id=version.id,
        generation_number=1,
        state=CandidateBatchState.CONFIRMED,
        created_by_user_id=owner.id,
        created_at=created_at,
    )
    second_batch = KnowledgeCandidateBatch(
        id=UUID(int=1),
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        document_version_id=version.id,
        generation_number=2,
        state=CandidateBatchState.CONFIRMED,
        created_by_user_id=owner.id,
        created_at=created_at,
    )
    session.add_all([first_batch, second_batch])
    session.flush()
    first_note = KnowledgeCandidateNote(
        id=UUID(int=2),
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=first_batch.id,
        ordinal=0,
        candidate_key="first",
        title="first",
        normalized_title="first",
        kind=CandidateNoteKind.CONCEPT,
        markdown="# first",
        source_pointers=[],
        review_state=CandidateReviewState.ACCEPTED,
        created_at=created_at,
    )
    second_note = KnowledgeCandidateNote(
        id=UUID(int=1),
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=second_batch.id,
        ordinal=0,
        candidate_key="second",
        title="second",
        normalized_title="second",
        kind=CandidateNoteKind.CONCEPT,
        markdown="# second",
        source_pointers=[],
        review_state=CandidateReviewState.ACCEPTED,
        created_at=created_at,
    )
    session.add_all([first_note, second_note])
    session.flush()
    first_link = KnowledgeCandidateLink(
        id=UUID(int=4),
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=first_batch.id,
        ordinal=0,
        kind=CandidateLinkKind.TERM,
        relation="mentions",
        source_key="first",
        target_key="first",
        source_pointer="wireless.docx#first",
        occurrence="first",
        context="first",
        review_state=CandidateReviewState.ACCEPTED,
        created_at=created_at,
    )
    second_link = KnowledgeCandidateLink(
        id=UUID(int=3),
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        batch_id=second_batch.id,
        ordinal=0,
        kind=CandidateLinkKind.TERM,
        relation="mentions",
        source_key="second",
        target_key="second",
        source_pointer="wireless.docx#second",
        occurrence="second",
        context="second",
        review_state=CandidateReviewState.ACCEPTED,
        created_at=created_at,
    )
    session.add_all([first_link, second_link])
    session.commit()

    graph = load_knowledge_graph(session, owner, knowledge_base.id)

    assert [node.id for node in graph.nodes] == [second_note.id, first_note.id]
    assert [edge.id for edge in graph.edges] == [second_link.id, first_link.id]