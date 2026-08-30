from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from tutor_api.agent.event_store import (
    EventStoreError,
    acknowledge_runtime_event,
    persist_runtime_event,
)
from tutor_api.agent.models import (
    AgentSession,
    AgentSessionEvent,
    AgentSessionState,
    AgentTurn,
    AgentTurnState,
)
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault import models as vault_models  # noqa: F401


def setup_db():
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def graph(db):
    user = User(email="events@example.com", username="events", password_hash="h")
    db.add(user)
    db.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Events")
    db.add(space)
    db.flush()
    kb = KnowledgeBase(
        space_id=space.id, owner_user_id=user.id, created_by_user_id=user.id, name="Events"
    )
    db.add(kb)
    db.flush()
    agent = AgentSession(
        user_id=user.id,
        space_id=space.id,
        knowledge_base_id=kb.id,
        provider="claude",
        model="claude",
        state=AgentSessionState.RUNNING,
    )
    db.add(agent)
    db.flush()
    return agent


def create_turn(db, agent: AgentSession) -> AgentTurn:
    turn = AgentTurn(session_id=agent.id, user_message="test")
    db.add(turn)
    db.flush()
    return turn


def payload(agent, sequence=1, key="one"):
    return {
        "session_id": agent.id,
        "sequence": sequence,
        "event_id": uuid4(),
        "event_type": "model_text_delta",
        "timestamp": "2026-08-29T00:00:00Z",
        "payload": {"text": "hello", "token": "secret"},
        "idempotency_key": key,
    }


def test_duplicate_event_is_acknowledged_once_and_redacted() -> None:
    engine, factory = setup_db()
    with factory() as db:
        agent = graph(db)
        value = payload(agent)
        first = persist_runtime_event(db, value)
        second = persist_runtime_event(db, value)
        assert first.id == second.id
        assert db.scalar(select(func.count(AgentSessionEvent.id))) == 1
        assert first.payload["token"] == "[REDACTED]"
        assert first.timestamp == datetime(2026, 8, 29, tzinfo=UTC)
        ack = acknowledge_runtime_event(db, value)
        assert ack.model_dump() == {
            "persisted": True,
            "accepted_sequence": 1,
            "duplicate": True,
        }
    Base.metadata.drop_all(engine)


def test_gap_does_not_advance_session_cursor() -> None:
    engine, factory = setup_db()
    with factory() as db:
        agent = graph(db)
        with pytest.raises(EventStoreError, match="event_sequence_gap") as error:
            persist_runtime_event(db, payload(agent, sequence=2))
        assert error.value.expected_sequence == 1
        assert agent.last_event_sequence == 0
    Base.metadata.drop_all(engine)


@pytest.mark.parametrize(
    ("runtime_state", "expected_turn_state", "expected_session_state"),
    [
        ("completed", AgentTurnState.COMPLETED, AgentSessionState.WAITING_INPUT),
        ("failed", AgentTurnState.FAILED, AgentSessionState.FAILED),
        ("waiting_input", AgentTurnState.WAITING_INPUT, AgentSessionState.WAITING_INPUT),
    ],
)
def test_session_state_event_updates_turn_and_session(
    runtime_state: str,
    expected_turn_state: AgentTurnState,
    expected_session_state: AgentSessionState,
) -> None:
    engine, factory = setup_db()
    with factory() as db:
        agent = graph(db)
        turn = create_turn(db, agent)
        value = payload(agent)
        value.update(
            {
                "turn_id": turn.id,
                "event_type": "session_state",
                "payload": {"state": runtime_state},
            }
        )

        persist_runtime_event(db, value)

        assert turn.state == expected_turn_state
        assert agent.state == expected_session_state
    Base.metadata.drop_all(engine)
