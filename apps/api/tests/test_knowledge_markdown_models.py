from collections.abc import Generator
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import (
    KnowledgeBase,
    MarkdownLink,
    MarkdownNote,
    MarkdownNoteState,
    MarkdownRevision,
    MarkdownRevisionState,
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


def create_owner_and_space(session: Session) -> tuple[User, Space, KnowledgeBase]:
    owner = User(email="markdown@example.com", username="markdown", password_hash="hash")
    session.add(owner)
    session.flush()
    space = Space(owner_id=owner.id, kind=SpaceKind.PERSONAL, name="Markdown space")
    session.add(space)
    session.flush()
    knowledge_base = KnowledgeBase(
        space_id=space.id,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        name="Markdown knowledge base",
    )
    session.add(knowledge_base)
    session.flush()
    return owner, space, knowledge_base


def create_note(
    session: Session, owner: User, space: Space, knowledge_base: KnowledgeBase, title: str
) -> MarkdownNote:
    note = MarkdownNote(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        title=title,
        normalized_title=title.casefold(),
        state=MarkdownNoteState.DRAFT,
        created_by_user_id=owner.id,
    )
    session.add(note)
    session.flush()
    return note


def test_markdown_note_and_revision_keep_draft_separate_from_published_content(
    session: Session,
) -> None:
    owner, space, knowledge_base = create_owner_and_space(session)
    note = create_note(session, owner, space, knowledge_base, "极限")
    draft = MarkdownRevision(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        note_id=note.id,
        revision_number=1,
        state=MarkdownRevisionState.NEEDS_REVIEW,
        markdown="# 极限\n\n原始内容整理稿",
        content_sha256="a" * 64,
        created_by_user_id=owner.id,
    )
    session.add(draft)
    session.commit()

    persisted = session.scalar(select(MarkdownRevision).where(MarkdownRevision.id == draft.id))
    assert persisted is not None
    assert persisted.state is MarkdownRevisionState.NEEDS_REVIEW
    assert note.state is MarkdownNoteState.DRAFT


def test_one_note_has_at_most_one_published_revision(session: Session) -> None:
    owner, space, knowledge_base = create_owner_and_space(session)
    note = create_note(session, owner, space, knowledge_base, "函数")
    for revision_number in (1, 2):
        session.add(
            MarkdownRevision(
                space_id=space.id,
                knowledge_base_id=knowledge_base.id,
                note_id=note.id,
                revision_number=revision_number,
                state=MarkdownRevisionState.PUBLISHED,
                markdown=f"# 函数 {revision_number}",
                content_sha256=("b" if revision_number == 1 else "c") * 64,
                created_by_user_id=owner.id,
            )
        )

    with pytest.raises(IntegrityError):
        session.commit()


def test_link_edge_keeps_unresolved_target_and_resolved_note_identity(session: Session) -> None:
    owner, space, knowledge_base = create_owner_and_space(session)
    source = create_note(session, owner, space, knowledge_base, "导数")
    target = create_note(session, owner, space, knowledge_base, "极限")
    revision = MarkdownRevision(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        note_id=source.id,
        revision_number=1,
        state=MarkdownRevisionState.PUBLISHED,
        markdown="# 导数\n\n[[极限]]\n\n[[尚未创建]]",
        content_sha256="d" * 64,
        created_by_user_id=owner.id,
    )
    session.add(revision)
    session.flush()
    session.add_all(
        [
            MarkdownLink(
                space_id=space.id,
                knowledge_base_id=knowledge_base.id,
                source_note_id=source.id,
                source_revision_id=revision.id,
                ordinal=0,
                target_note_id=target.id,
                target_title="极限",
            ),
            MarkdownLink(
                space_id=space.id,
                knowledge_base_id=knowledge_base.id,
                source_note_id=source.id,
                source_revision_id=revision.id,
                ordinal=1,
                target_title="尚未创建",
            ),
        ]
    )
    session.commit()

    links = session.scalars(select(MarkdownLink).order_by(MarkdownLink.ordinal)).all()
    assert [(link.target_note_id, link.target_title) for link in links] == [
        (target.id, "极限"),
        (None, "尚未创建"),
    ]
    assert all(isinstance(link.space_id, UUID) for link in links)
