from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

import tutor_api.agent.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.agent.models import AgentSession, AgentSessionState, AgentUsageRecord
from tutor_api.agent.runtime_client import RuntimeUnavailable
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.identity.router import get_current_user
from tutor_api.knowledge.models import IndexVersion, IndexVersionState, KnowledgeBase
from tutor_api.main import create_app
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault.models import (
    SemanticIndexPlan,
    SemanticIndexPlanState,
    VaultChangeSet,
    VaultChangeSetState,
    VaultChangeSource,
    VaultFile,
    VaultFileKind,
    VaultSyncCursor,
    VaultSyncState,
)


@pytest.fixture
def diagnostics_context(
    tmp_path: Path,
) -> Generator[tuple[TestClient, dict[str, object]], None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        user = User(email="diag@example.com", username="diag", password_hash="hash")
        db.add(user)
        db.flush()
        space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Diagnostics")
        db.add(space)
        db.flush()
        knowledge_base = KnowledgeBase(
            space_id=space.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            name="Diagnostics KB",
        )
        db.add(knowledge_base)
        db.flush()
        agent_session = AgentSession(
            user_id=user.id,
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            provider="claude",
            model="claude",
            state=AgentSessionState.RUNNING,
            last_event_sequence=0,
        )
        pending = VaultChangeSet(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            source=VaultChangeSource.API,
            state=VaultChangeSetState.PENDING,
        )
        conflict = VaultChangeSet(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            source=VaultChangeSource.EXTERNAL_EDITOR,
            state=VaultChangeSetState.CONFLICTED,
        )
        db.add_all([agent_session, pending, conflict])
        db.flush()
        vault_file = VaultFile(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            relative_path="diagnostics.md",
            file_kind=VaultFileKind.MARKDOWN,
            content_hash="a" * 64,
            size_bytes=12,
            sync_state=VaultSyncState.PENDING,
        )
        db.add(vault_file)
        db.flush()
        index = IndexVersion(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            version_number=1,
            state=IndexVersionState.BUILDING,
            parser_signature="parser",
            ocr_signature="ocr",
            chunking_signature="chunk",
            embedding_backend="hash",
            embedding_model="hash",
            embedding_dimension=384,
            embedding_contract_signature="contract",
            index_signature="diagnostics-index",
            activation_status="semantic_ready",
            created_by_user_id=user.id,
        )
        plan = SemanticIndexPlan(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            vault_file_id=vault_file.id,
            input_hash="a" * 64,
            provider="claude",
            model="claude",
            schema_version="1",
            prompt_hash="b" * 64,
            state=SemanticIndexPlanState.PENDING,
        )
        cursor = VaultSyncCursor(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            pending_count=4,
            requires_full_scan=True,
            last_error="private filesystem path C:/secret",
        )
        usage = AgentUsageRecord(
            session_id=agent_session.id,
            provider="claude",
            model="claude",
            sidecar_bytes=123,
        )
        db.add_all([index, plan, cursor, usage])
        context = {"user_id": user.id, "factory": factory}

    sidecar_root = tmp_path / "sidecars"
    sidecar_root.mkdir()
    (sidecar_root / "payload.bin").write_bytes(b"12345")
    app = create_app(
        Settings(
            app_env="test",
            agent_runtime_url="http://127.0.0.1:8765",
            agent_runtime_token="runtime-token",
            agent_sidecar_root=str(sidecar_root),
            agent_vault_root=str(tmp_path / "vault"),
        ),
        factory,
    )

    def current_user() -> User:
        with factory() as db:
            user = db.get(User, context["user_id"])
            assert user is not None
            db.expunge(user)
            return user

    app.dependency_overrides[get_current_user] = current_user
    with TestClient(app) as client:
        context["app"] = app
        yield client, context
    engine.dispose()


def test_diagnostics_aggregates_runtime_and_control_plane_without_sensitive_details(
    diagnostics_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = diagnostics_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    class RuntimeDiagnostics:
        async def proxy(self, method: str, path: str, payload=None):
            del method, path, payload
            return {
                "status": "degraded",
                "protocol_version": "1",
                "upstream_commit": "do-not-expose-commit",
                "token": "runtime-secret-token",
                "providers": [
                    {
                        "id": "claude",
                        "status": "unavailable",
                        "enabled": True,
                        "detail": "sk-secret provider failure",
                    }
                ],
                "mcp": [
                    {
                        "name": "filesystem",
                        "status": "connected",
                        "error": "Authorization: Bearer secret",
                    }
                ],
            }

    app.state.agent_runtime_client = RuntimeDiagnostics()

    response = client.get("/api/v1/agent/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["runtime"] == {"status": "degraded", "protocol_version": "1"}
    assert payload["providers"] == [
        {"id": "claude", "enabled": True, "status": "unavailable"}
    ]
    assert payload["mcp"] == [{"name": "filesystem", "status": "connected"}]
    assert payload["events"]["sequence_lag"] == 0
    assert payload["sidecars"] == {"recorded_bytes": 123, "filesystem_bytes": 5}
    assert payload["vault"] == {
        "pending_change_sets": 1,
        "conflicts": 1,
        "pending_files": 1,
        "watcher_backlog": 4,
        "full_scans_required": 1,
    }
    assert payload["index"]["states"] == {"building": 1}
    assert payload["index"]["activation"] == {"semantic_ready": 1}
    assert payload["planner"] == {"pending": 1}
    serialized = response.text.casefold()
    for secret in (
        "runtime-secret-token",
        "sk-secret",
        "bearer secret",
        "do-not-expose-commit",
        "c:/secret",
    ):
        assert secret not in serialized


def test_diagnostics_is_degraded_but_available_when_runtime_is_down(
    diagnostics_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = diagnostics_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    class DownRuntime:
        async def proxy(self, method: str, path: str, payload=None):
            del method, path, payload
            raise RuntimeUnavailable("runtime_unavailable")

    app.state.agent_runtime_client = DownRuntime()

    diagnostics = client.get("/api/v1/agent/diagnostics")
    health = client.get("/api/v1/health")

    assert diagnostics.status_code == 200
    assert diagnostics.json()["status"] == "degraded"
    assert diagnostics.json()["runtime"] == {
        "status": "unavailable",
        "code": "runtime_unavailable",
    }
    assert health.status_code == 200
