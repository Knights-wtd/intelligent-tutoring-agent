from __future__ import annotations

import hashlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

import tutor_api.agent.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.agent.models import AgentSession, AgentSessionEvent, AgentSessionState
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User, UserSession
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.main import create_app
from tutor_api.spaces.models import Space, SpaceKind


@pytest.fixture
def websocket_context() -> Generator[tuple[TestClient, dict[str, object]], None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    token = "agent-websocket-token"
    with factory.begin() as db:
        owner = User(email="ws-owner@example.com", username="ws-owner", password_hash="hash")
        outsider = User(
            email="ws-outsider@example.com", username="ws-outsider", password_hash="hash"
        )
        db.add_all([owner, outsider])
        db.flush()
        space = Space(owner_id=owner.id, kind=SpaceKind.PERSONAL, name="WS")
        db.add(space)
        db.flush()
        knowledge_base = KnowledgeBase(
            space_id=space.id,
            owner_user_id=owner.id,
            created_by_user_id=owner.id,
            name="WS KB",
        )
        db.add(knowledge_base)
        db.flush()
        agent_session = AgentSession(
            user_id=owner.id,
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            provider="claude",
            model="claude",
            state=AgentSessionState.RUNNING,
            last_event_sequence=2,
        )
        db.add(agent_session)
        db.flush()
        db.add_all(
            [
                AgentSessionEvent(
                    session_id=agent_session.id,
                    sequence=1,
                    event_id=uuid4(),
                    event_type="turn_started",
                    timestamp=datetime(2026, 8, 29, 0, 0, tzinfo=UTC),
                    payload={"text": "first"},
                    idempotency_key="ws-1",
                ),
                AgentSessionEvent(
                    session_id=agent_session.id,
                    sequence=2,
                    event_id=uuid4(),
                    event_type="model_text_delta",
                    timestamp=datetime(2026, 8, 29, 0, 0, 1, tzinfo=UTC),
                    payload={"text": "second"},
                    idempotency_key="ws-2",
                ),
            ]
        )
        db.add(
            UserSession(
                user_id=owner.id,
                token_digest=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        context = {"session_id": agent_session.id, "token": token, "factory": factory}

    app = create_app(
        Settings(
            app_env="test",
            agent_runtime_url="http://127.0.0.1:8765",
            agent_runtime_token="runtime-token",
        ),
        factory,
    )
    with TestClient(app) as client:
        context["cookie_name"] = app.state.settings.session_cookie_name
        yield client, context
    engine.dispose()


def test_websocket_replays_only_events_after_cursor_and_accepts_cookie_auth(
    websocket_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = websocket_context
    client.cookies.set(str(context["cookie_name"]), str(context["token"]))

    with client.websocket_connect(
        f"/api/v1/agent/ws/{context['session_id']}?after=1"
    ) as websocket:
        event_payload = websocket.receive_json()

    assert event_payload["sequence"] == 2
    assert event_payload["payload"] == {"text": "second"}
    assert event_payload["timestamp"] == "2026-08-29T00:00:01+00:00"


def test_websocket_rejects_missing_cookie_auth(
    websocket_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = websocket_context

    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(f"/api/v1/agent/ws/{context['session_id']}"):
            pass

    assert error.value.code == 4401


def test_websocket_rejects_revoked_cookie_on_reconnect(
    websocket_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = websocket_context
    factory = context["factory"]
    assert isinstance(factory, sessionmaker)
    with factory.begin() as db:
        stored = db.query(UserSession).one()
        stored.revoked_at = datetime.now(UTC)
    client.cookies.set(str(context["cookie_name"]), str(context["token"]))

    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(f"/api/v1/agent/ws/{context['session_id']}"):
            pass

    assert error.value.code == 4401

