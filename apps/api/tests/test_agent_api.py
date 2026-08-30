from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

import tutor_api.agent.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.agent.models import AgentProviderSetting, AgentSession, AgentSessionState
from tutor_api.agent.runtime_client import RuntimeUnavailable
from tutor_api.agent.schemas import RuntimeStartResponse, SessionCreateRequest
from tutor_api.agent.service import create_session
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.identity.router import get_current_user
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.main import create_app
from tutor_api.spaces.models import Space, SpaceKind


@pytest.fixture
def api_context(tmp_path: Path) -> Generator[tuple[TestClient, dict[str, object]], None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        user = User(email="agent-api@example.com", username="agent-api", password_hash="hash")
        db.add(user)
        db.flush()
        space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Agent API")
        db.add(space)
        db.flush()
        knowledge_base = KnowledgeBase(
            space_id=space.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            name="Agent API KB",
        )
        db.add(knowledge_base)
        db.flush()
        ids = {
            "user_id": user.id,
            "space_id": space.id,
            "knowledge_base_id": knowledge_base.id,
        }

    settings = Settings(
        app_env="test",
        agent_runtime_url="http://127.0.0.1:8765",
        agent_runtime_callback_url="http://127.0.0.1:8000/api/v1/agent/runtime/events",
        agent_runtime_token="runtime-token",
        agent_capability_secret="capability-secret-capability-secret",
        agent_vault_root=str(tmp_path / "vault"),
        agent_sidecar_root=str(tmp_path / "sidecars"),
    )
    app = create_app(settings, factory)

    def current_user() -> User:
        with factory() as db:
            user = db.get(User, ids["user_id"])
            assert user is not None
            db.expunge(user)
            return user

    app.dependency_overrides[get_current_user] = current_user
    with TestClient(app) as client:
        ids.update({"app": app, "factory": factory})
        yield client, ids
    engine.dispose()


def test_agent_settings_root_matches_the_workspace_web_contract(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    initial = client.get("/api/v1/agent/settings")

    assert initial.status_code == 200
    assert initial.json() == {
        "provider": app.state.settings.agent_provider,
        "model": app.state.settings.agent_model,
        "context_window": app.state.settings.agent_context_window,
        "permission_mode": "bypassPermissions",
        "workspace_roots": [str(app.state.vault_root)],
        "mcp_enabled": False,
        "skills_enabled": False,
        "subagents_enabled": True,
        "web_enabled": True,
    }


def test_agent_settings_root_update_persists_faro_but_returns_effective_controls(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    app = context["app"]
    assert isinstance(app, FastAPI)
    payload = {
        "provider": "faro",
        "model": "gemini-3.7-flash-tiered",
        "context_window": 32_000,
        "permission_mode": "plan",
        "workspace_roots": ["C:/untrusted-client-root"],
        "mcp_enabled": True,
        "skills_enabled": True,
        "subagents_enabled": False,
        "web_enabled": False,
    }
    effective = {
        "provider": "faro",
        "model": "gemini-3.7-flash-tiered",
        "context_window": 32_000,
        "permission_mode": "bypassPermissions",
        "workspace_roots": [str(app.state.vault_root)],
        "mcp_enabled": False,
        "skills_enabled": False,
        "subagents_enabled": True,
        "web_enabled": True,
    }

    updated = client.put("/api/v1/agent/settings", json=payload)
    loaded = client.get("/api/v1/agent/settings")

    assert updated.status_code == 200
    assert updated.json() == effective
    assert loaded.status_code == 200
    assert loaded.json() == effective


def test_agent_settings_root_rejects_non_faro_provider(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    app = context["app"]
    assert isinstance(app, FastAPI)
    payload = {
        "provider": "claude",
        "model": "claude-sonnet",
        "context_window": 131_072,
        "permission_mode": "bypassPermissions",
        "workspace_roots": [str(app.state.vault_root)],
        "mcp_enabled": False,
        "skills_enabled": False,
        "subagents_enabled": True,
        "web_enabled": True,
    }

    response = client.put("/api/v1/agent/settings", json=payload)

    assert response.status_code == 422


def test_agent_settings_provider_route_rejects_non_faro_provider(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, _ = api_context

    response = client.put(
        "/api/v1/agent/settings/claude",
        json={"model": "claude-sonnet", "context_window": 131_072},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "agent_provider_must_be_faro"}


def test_agent_settings_ignore_stale_claude_rows_and_disabled_faro_rows(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    factory = context["factory"]
    with factory.begin() as db:
        db.add_all(
            [
                AgentProviderSetting(
                    user_id=None,
                    provider="claude",
                    model="claude-global",
                    context_window=1_000_000,
                    enabled=True,
                ),
                AgentProviderSetting(
                    user_id=context["user_id"],
                    provider="claude",
                    model="claude-user",
                    context_window=1_000_000,
                    enabled=True,
                ),
                AgentProviderSetting(
                    user_id=context["user_id"],
                    provider="faro",
                    model="disabled-gemini",
                    context_window=65_536,
                    enabled=False,
                ),
                AgentProviderSetting(
                    user_id=None,
                    provider="faro",
                    model="global-gemini",
                    context_window=96_000,
                    enabled=True,
                ),
            ]
        )

    response = client.get("/api/v1/agent/settings")

    assert response.status_code == 200
    assert response.json()["provider"] == "faro"
    assert response.json()["model"] == "gemini-3.7-flash-tiered"
    assert response.json()["context_window"] == 32_000


def test_agent_settings_prefer_enabled_user_faro_over_global_faro(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    factory = context["factory"]
    with factory.begin() as db:
        db.add_all(
            [
                AgentProviderSetting(
                    user_id=None,
                    provider="faro",
                    model="global-gemini",
                    context_window=96_000,
                    enabled=True,
                ),
                AgentProviderSetting(
                    user_id=context["user_id"],
                    provider="faro",
                    model="user-gemini",
                    context_window=128_000,
                    enabled=True,
                ),
            ]
        )

    response = client.get("/api/v1/agent/settings")

    assert response.status_code == 200
    assert response.json()["provider"] == "faro"
    assert response.json()["model"] == "gemini-3.7-flash-tiered"
    assert response.json()["context_window"] == 32_000


def test_agent_settings_reject_context_windows_that_cannot_create_a_session(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    app = context["app"]
    assert isinstance(app, FastAPI)
    payload = {
        "provider": app.state.settings.agent_provider,
        "model": app.state.settings.agent_model,
        "context_window": 31_999,
        "permission_mode": "bypassPermissions",
        "workspace_roots": [str(app.state.vault_root)],
        "mcp_enabled": False,
        "skills_enabled": False,
        "subagents_enabled": True,
        "web_enabled": True,
    }

    response = client.put("/api/v1/agent/settings", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("model", "context_window"),
    [
        pytest.param("another-model", 32_000, id="wrong-model"),
        pytest.param("gemini-3.7-flash-tiered", 131_072, id="wrong-context"),
    ],
)
def test_agent_settings_root_rejects_non_target_faro_configuration(
    api_context: tuple[TestClient, dict[str, object]],
    model: str,
    context_window: int,
) -> None:
    client, context = api_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    response = client.put(
        "/api/v1/agent/settings",
        json={
            "provider": "faro",
            "model": model,
            "context_window": context_window,
            "permission_mode": "bypassPermissions",
            "workspace_roots": [str(app.state.vault_root)],
            "mcp_enabled": False,
            "skills_enabled": False,
            "subagents_enabled": True,
            "web_enabled": True,
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        pytest.param(
            {"model": "another-model", "context_window": 32_000},
            "agent_model_must_be_gemini_3_7_flash",
            id="wrong-model",
        ),
        pytest.param(
            {"model": "gemini-3.7-flash-tiered", "context_window": 131_072},
            "agent_context_window_must_be_32000",
            id="wrong-context",
        ),
    ],
)
def test_agent_settings_provider_route_rejects_non_target_faro_configuration(
    api_context: tuple[TestClient, dict[str, object]],
    payload: dict[str, object],
    detail: str,
) -> None:
    client, _ = api_context

    response = client.put("/api/v1/agent/settings/faro", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    ("provider", "model", "context_window"),
    [
        pytest.param("claude", "fable", 1_000_000, id="legacy-claude-fable"),
        pytest.param("faro", "fable", 32_000, id="wrong-model"),
        pytest.param(
            "faro",
            "gemini-3.7-flash-tiered",
            1_000_000,
            id="wrong-context-window",
        ),
    ],
)
def test_create_agent_session_rejects_non_target_runtime_configuration(
    api_context: tuple[TestClient, dict[str, object]],
    provider: str,
    model: str,
    context_window: int,
) -> None:
    client, context = api_context

    response = client.post(
        "/api/v1/agent/sessions",
        json={
            "knowledge_base_id": str(context["knowledge_base_id"]),
            "provider": provider,
            "model": model,
            "context_window": context_window,
        },
    )

    assert response.status_code == 422


def test_create_session_service_forces_target_runtime_configuration(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    _, context = api_context
    factory = context["factory"]
    payload = SessionCreateRequest.model_construct(
        knowledge_base_id=context["knowledge_base_id"],
        provider="claude",
        model="fable",
        context_window=1_000_000,
    )

    with factory.begin() as db:
        user = db.get(User, context["user_id"])
        assert user is not None
        session = create_session(db, user, payload)

        assert session.provider == "faro"
        assert session.model == "gemini-3.7-flash-tiered"
        assert session.recovery["context_window"] == 32_000


def test_create_app_wires_agent_and_vault_routes_and_runtime_state(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    created = client.post(
        "/api/v1/agent/sessions",
        json={
            "knowledge_base_id": str(context["knowledge_base_id"]),
            "provider": "faro",
            "model": "gemini-3.7-flash-tiered",
            "context_window": 32_000,
        },
    )
    vault = client.get(f"/api/v1/knowledge-bases/{context['knowledge_base_id']}/vault/files")

    assert created.status_code == 201
    assert created.json()["permission_mode"] == "bypassPermissions"
    assert vault.status_code == 200
    assert vault.json() == []
    assert app.state.agent_runtime_client is not None
    assert app.state.agent_runtime_http_client is not None
    assert app.state.session_factory is context["factory"]
    assert app.state.vault_root == Path(app.state.settings.agent_vault_root).resolve()
    assert app.state.agent_sidecar_root == Path(app.state.settings.agent_sidecar_root).resolve()


def test_retired_claude_session_cannot_start_a_new_turn(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    app = context["app"]
    factory = context["factory"]
    assert isinstance(app, FastAPI)

    class RecordingRuntime:
        calls = 0

        async def start_turn(self, payload, request_id=None):
            del payload, request_id
            self.calls += 1
            raise AssertionError("retired session must not reach runtime")

    runtime = RecordingRuntime()
    app.state.agent_runtime_client = runtime
    with factory.begin() as db:
        session = AgentSession(
            user_id=context["user_id"],
            space_id=context["space_id"],
            knowledge_base_id=context["knowledge_base_id"],
            provider="claude",
            model="fable",
            permission_mode="bypassPermissions",
            state=AgentSessionState.WAITING_INPUT,
            recovery={"context_window": 1_000_000},
        )
        db.add(session)
        db.flush()
        session_id = session.id

    response = client.post(
        f"/api/v1/agent/sessions/{session_id}/turns",
        json={"prompt": "继续旧会话"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "agent_session_provider_retired"}
    assert runtime.calls == 0


def test_agent_send_never_calls_legacy_tutor_adapter(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    app = context["app"]
    legacy_tutor_adapter = Mock()

    class RecordingRuntime:
        calls = 0

        async def start_turn(self, payload, *, request_id=None):
            del payload, request_id
            self.calls += 1
            return RuntimeStartResponse(
                execution_id="execution-1",
                native_session_id="native-session-1",
                accepted_sequence=0,
            )

    runtime = RecordingRuntime()
    app.state.agent_runtime_client = runtime
    app.state.tutor_adapter = legacy_tutor_adapter
    created = client.post(
        "/api/v1/agent/sessions",
        json={
            "knowledge_base_id": str(context["knowledge_base_id"]),
            "provider": "faro",
            "model": "gemini-3.7-flash-tiered",
            "context_window": 32_000,
        },
    )
    response = client.post(
        f"/api/v1/agent/sessions/{created.json()['id']}/turns",
        json={"prompt": "联合知识库和网页回答"},
    )

    assert created.status_code == 201
    assert response.status_code == 202
    assert runtime.calls == 1
    legacy_tutor_adapter.assert_not_called()


def test_turn_callback_uses_trusted_runtime_url_instead_of_proxy_host(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    class RecordingRuntime:
        payload = None

        async def start_turn(self, payload, *, request_id=None):
            del request_id
            self.payload = payload
            return RuntimeStartResponse(
                execution_id="execution-callback",
                native_session_id="native-callback",
                accepted_sequence=0,
            )

    runtime = RecordingRuntime()
    app.state.agent_runtime_client = runtime
    created = client.post(
        "/api/v1/agent/sessions",
        json={
            "knowledge_base_id": str(context["knowledge_base_id"]),
            "provider": "faro",
            "model": "gemini-3.7-flash-tiered",
            "context_window": 32_000,
        },
    )

    response = client.post(
        f"/api/v1/agent/sessions/{created.json()['id']}/turns",
        json={"prompt": "验证代理回调地址"},
        headers={"Host": "web:3000"},
    )

    assert response.status_code == 202
    assert runtime.payload is not None
    assert str(runtime.payload.callback_url) == app.state.settings.agent_runtime_callback_url
    assert "web:3000" not in str(runtime.payload.callback_url)


def test_runtime_event_callback_accepts_protocol_envelope_and_returns_durable_ack(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    created = client.post(
        "/api/v1/agent/sessions",
        json={
            "knowledge_base_id": str(context["knowledge_base_id"]),
            "provider": "faro",
            "model": "gemini-3.7-flash-tiered",
            "context_window": 32_000,
        },
    )
    assert created.status_code == 201
    event = {
        "event_id": str(uuid4()),
        "session_id": created.json()["id"],
        "turn_id": None,
        "sequence": 1,
        "event_type": "turn_started",
        "timestamp": "2026-08-29T00:00:00Z",
        "payload": {},
        "idempotency_key": f"runtime-event-{uuid4()}",
    }

    first = client.post(
        "/api/v1/agent/runtime/events",
        json=event,
        headers={"Authorization": "Bearer runtime-token"},
    )
    duplicate = client.post(
        "/api/v1/agent/runtime/events",
        json=event,
        headers={"Authorization": "Bearer runtime-token"},
    )

    assert first.status_code == 200
    assert first.json() == {
        "persisted": True,
        "accepted_sequence": 1,
        "duplicate": False,
    }
    assert duplicate.status_code == 200
    assert duplicate.json() == {
        "persisted": True,
        "accepted_sequence": 1,
        "duplicate": True,
    }

    replay = client.get(f"/api/v1/agent/sessions/{created.json()['id']}/events")
    assert replay.status_code == 200
    assert replay.json()[0]["timestamp"] == "2026-08-29T00:00:00+00:00"


def test_runtime_failure_is_a_recoverable_agent_503_and_health_stays_independent(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    class DownRuntime:
        async def proxy(self, method: str, path: str, payload=None):
            del method, path, payload
            raise RuntimeUnavailable("runtime_unavailable")

    app.state.agent_runtime_client = DownRuntime()

    failed = client.get("/api/v1/agent/mcp")
    health = client.get("/api/v1/health")

    assert failed.status_code == 503
    assert failed.json() == {"detail": "runtime_unavailable"}
    assert failed.headers.get("retry-after") == "1"
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "textbook-tutor-api"}


def test_invalid_runtime_configuration_does_not_block_api_startup(tmp_path: Path) -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    app = create_app(
        Settings(
            app_env="test",
            agent_runtime_url="https://runtime.example.com",
            agent_vault_root=str(tmp_path / "vault"),
        ),
        factory,
    )

    with TestClient(app) as client:
        health = client.get("/api/v1/health")

    assert health.status_code == 200
    assert app.state.agent_runtime_client is None
    assert app.state.agent_runtime_status == SimpleNamespace(
        status="unavailable", code="runtime_configuration_invalid"
    )
    engine.dispose()
