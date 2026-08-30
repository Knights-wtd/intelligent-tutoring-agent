from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.agent.models import AgentSession, AgentSessionEvent, AgentSessionState
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.spaces.models import Space, SpaceKind


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    active_session = factory()
    try:
        yield active_session
    finally:
        active_session.close()
        engine.dispose()


@pytest.fixture
def agent_session(session: Session) -> AgentSession:
    user = User(email="agent@example.com", username="agent-user", password_hash="hash")
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Agent Space")
    session.add(space)
    session.flush()
    knowledge_base = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name="Agent KB",
    )
    session.add(knowledge_base)
    session.flush()
    model = AgentSession(
        user_id=user.id,
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        model="claude",
        state=AgentSessionState.RUNNING,
    )
    session.add(model)
    session.flush()
    return model


def test_agent_event_sequence_is_unique_per_session(
    session: Session, agent_session: AgentSession
) -> None:
    session.add_all(
        [
            AgentSessionEvent(
                session_id=agent_session.id,
                sequence=1,
                event_id=uuid4(),
                event_type="turn_started",
                payload={},
                idempotency_key="a",
            ),
            AgentSessionEvent(
                session_id=agent_session.id,
                sequence=1,
                event_id=uuid4(),
                event_type="model_text_delta",
                payload={},
                idempotency_key="b",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.flush()
