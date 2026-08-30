from __future__ import annotations

import hashlib
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

import tutor_api.agent.models  # noqa: F401
import tutor_api.classrooms.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.agent.capability import (
    issue_workspace_capability,
    verify_workspace_capability,
)
from tutor_api.agent.runtime_client import RuntimeUnavailable
from tutor_api.agent.schemas import RuntimeStartResponse
from tutor_api.classrooms.models import Classroom, ClassroomMembership, ClassroomRole
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.identity.router import get_current_user
from tutor_api.knowledge.models import (
    KnowledgeBase,
    MarkdownNote,
    MarkdownNoteState,
    MarkdownRevision,
    MarkdownRevisionState,
)
from tutor_api.knowledge.storage import MemoryObjectStorage
from tutor_api.knowledge.workspace import load_published_note
from tutor_api.main import create_app
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.tutor.models import TutorConversation, TutorMessage, TutorMessageRole
from tutor_api.vault.migration import MigrationPhase, VaultMigrator

_RETIRED = {
    "code": "legacy_tutor_retired",
    "replacement": "/api/v1/agent",
}


@pytest.fixture
def acceptance_context(
    tmp_path: Path,
) -> Generator[tuple[TestClient, dict[str, Any]], None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory.begin() as db:
        owner = User(email="accept-owner@example.com", username="accept-owner", password_hash="h")
        student = User(
            email="accept-student@example.com",
            username="accept-student",
            password_hash="h",
        )
        outsider = User(
            email="accept-outsider@example.com",
            username="accept-outsider",
            password_hash="h",
        )
        db.add_all([owner, student, outsider])
        db.flush()

        classroom_space = Space(
            owner_id=owner.id,
            kind=SpaceKind.CLASSROOM,
            name="Acceptance classroom",
        )
        outsider_space = Space(
            owner_id=outsider.id,
            kind=SpaceKind.PERSONAL,
            name="Outsider personal",
        )
        db.add_all([classroom_space, outsider_space])
        db.flush()

        classroom = Classroom(
            space_id=classroom_space.id,
            owner_id=owner.id,
            name="Acceptance classroom",
        )
        db.add(classroom)
        db.flush()
        db.add_all(
            [
                ClassroomMembership(
                    classroom_id=classroom.id,
                    user_id=owner.id,
                    role=ClassroomRole.OWNER,
                ),
                ClassroomMembership(
                    classroom_id=classroom.id,
                    user_id=student.id,
                    role=ClassroomRole.STUDENT,
                ),
            ]
        )

        knowledge_base = KnowledgeBase(
            space_id=classroom_space.id,
            owner_user_id=owner.id,
            created_by_user_id=owner.id,
            name="Acceptance KB",
        )
        outsider_knowledge_base = KnowledgeBase(
            space_id=outsider_space.id,
            owner_user_id=outsider.id,
            created_by_user_id=outsider.id,
            name="Outsider KB",
        )
        db.add_all([knowledge_base, outsider_knowledge_base])
        db.flush()

        note = MarkdownNote(
            space_id=classroom_space.id,
            knowledge_base_id=knowledge_base.id,
            title="Migration route",
            normalized_title="migration route",
            state=MarkdownNoteState.PUBLISHED,
            created_by_user_id=owner.id,
        )
        db.add(note)
        db.flush()
        legacy_markdown = "legacy authoritative body"
        db.add(
            MarkdownRevision(
                space_id=classroom_space.id,
                knowledge_base_id=knowledge_base.id,
                note_id=note.id,
                revision_number=1,
                state=MarkdownRevisionState.PUBLISHED,
                markdown=legacy_markdown,
                content_sha256=hashlib.sha256(legacy_markdown.encode()).hexdigest(),
                source_markers=[],
                created_by_user_id=owner.id,
            )
        )

        legacy_created_at = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
        conversation = TutorConversation(
            user_id=owner.id,
            space_id=classroom_space.id,
            knowledge_base_id=knowledge_base.id,
            title="Legacy acceptance history",
            created_at=legacy_created_at,
            updated_at=legacy_created_at + timedelta(seconds=1),
        )
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                TutorMessage(
                    conversation_id=conversation.id,
                    user_id=owner.id,
                    space_id=classroom_space.id,
                    knowledge_base_id=knowledge_base.id,
                    role=TutorMessageRole.USER,
                    content="legacy question",
                    citations=[],
                    created_at=legacy_created_at,
                ),
                TutorMessage(
                    conversation_id=conversation.id,
                    user_id=owner.id,
                    space_id=classroom_space.id,
                    knowledge_base_id=knowledge_base.id,
                    role=TutorMessageRole.ASSISTANT,
                    content="legacy answer",
                    citations=[],
                    created_at=legacy_created_at + timedelta(seconds=1),
                ),
            ]
        )
        ids = {
            "owner_id": owner.id,
            "student_id": student.id,
            "outsider_id": outsider.id,
            "space_id": classroom_space.id,
            "knowledge_base_id": knowledge_base.id,
            "outsider_knowledge_base_id": outsider_knowledge_base.id,
            "note_id": note.id,
            "conversation_id": conversation.id,
        }

    settings = Settings(
        app_env="test",
        agent_runtime_url="http://127.0.0.1:8765",
        agent_runtime_token="runtime-token-for-acceptance",
        agent_capability_secret="acceptance-capability-secret-value",
        agent_vault_root=str(tmp_path / "vault"),
        agent_sidecar_root=str(tmp_path / "sidecars"),
    )
    app = create_app(settings, factory)

    def select_user(user_id: UUID) -> Callable[[], User]:
        def dependency() -> User:
            with factory() as db:
                user = db.get(User, user_id)
                assert user is not None
                db.expunge(user)
                return user

        return dependency

    def use_user(user_id: UUID) -> None:
        app.dependency_overrides[get_current_user] = select_user(user_id)

    use_user(ids["owner_id"])
    ids.update(
        {
            "app": app,
            "factory": factory,
            "settings": settings,
            "use_user": use_user,
            "tmp_path": tmp_path,
        }
    )
    with TestClient(app) as client:
        yield client, ids
    engine.dispose()


def _create_agent_session(client: TestClient, knowledge_base_id: UUID) -> dict[str, Any]:
    response = client.post(
        "/api/v1/agent/sessions",
        json={
            "knowledge_base_id": str(knowledge_base_id),
            "provider": "faro",
            "model": "gemini-3.7-flash-tiered",
            "context_window": 32_000,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_agent_is_the_only_mutating_ai_path_and_receives_scoped_capability(
    acceptance_context: tuple[TestClient, dict[str, Any]],
) -> None:
    client, context = acceptance_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    class RecordingRuntime:
        payload: Any = None

        async def start_turn(self, payload, *, request_id=None):
            del request_id
            self.payload = payload
            return RuntimeStartResponse(
                execution_id="acceptance-execution",
                native_session_id="acceptance-native-session",
                accepted_sequence=0,
            )

    runtime = RecordingRuntime()
    app.state.agent_runtime_client = runtime
    created = _create_agent_session(client, context["knowledge_base_id"])
    turn = client.post(
        f"/api/v1/agent/sessions/{created['id']}/turns",
        json={"prompt": "Inspect the whole authorized workspace"},
    )
    retired = client.post("/api/v1/tutor/conversations", json={"prompt": "old path"})

    assert turn.status_code == 202
    assert created["permission_mode"] == "bypassPermissions"
    assert runtime.payload is not None
    capability = verify_workspace_capability(
        runtime.payload.capability,
        settings=context["settings"],
        expected_user_id=context["owner_id"],
    )
    grants = {item["knowledge_base_id"]: item for item in capability["grants"]}
    assert grants[str(context["knowledge_base_id"])]["actions"] == ["read", "write", "delete"]
    assert runtime.payload.workspace_roots == capability["vault_roots"]
    assert all(Path(root).is_dir() for root in runtime.payload.workspace_roots)
    assert str(context["outsider_knowledge_base_id"]) not in grants
    assert retired.status_code == 410
    assert retired.json() == _RETIRED
    assert not hasattr(app.state, "tutor_adapter")
    assert not hasattr(app.state, "tutor_web_search_adapter")


def test_acl_keeps_student_read_only_and_hides_unjoined_or_foreign_workspaces(
    acceptance_context: tuple[TestClient, dict[str, Any]],
) -> None:
    client, context = acceptance_context
    knowledge_base_id = context["knowledge_base_id"]
    created = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files",
        json={"relative_path": "acceptance/shared.md", "markdown": "shared"},
    )
    assert created.status_code == 201

    context["use_user"](context["student_id"])
    student_read = client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files")
    student_write = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files",
        json={"relative_path": "acceptance/student.md", "markdown": "forbidden"},
    )
    with context["factory"]() as db:
        student = db.get(User, context["student_id"])
        assert student is not None
        token = issue_workspace_capability(
            db,
            student,
            session_id=knowledge_base_id,
            settings=context["settings"],
        )
        capability = verify_workspace_capability(
            token,
            settings=context["settings"],
            expected_user_id=context["student_id"],
        )

    grants = {item["knowledge_base_id"]: item for item in capability["grants"]}
    assert student_read.status_code == 200
    assert student_write.status_code == 403
    assert grants[str(knowledge_base_id)]["actions"] == ["read"]
    assert str(context["outsider_knowledge_base_id"]) not in grants

    context["use_user"](context["outsider_id"])
    hidden_vault = client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files")
    hidden_agent = client.post(
        "/api/v1/agent/sessions",
        json={"knowledge_base_id": str(knowledge_base_id)},
    )
    assert hidden_vault.status_code == 404
    assert hidden_agent.status_code == 404


def test_runtime_outage_is_recoverable_and_does_not_take_down_non_agent_paths(
    acceptance_context: tuple[TestClient, dict[str, Any]],
) -> None:
    client, context = acceptance_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    class DownRuntime:
        async def proxy(self, method: str, path: str, payload=None):
            del method, path, payload
            raise RuntimeUnavailable("runtime_unavailable")

    app.state.agent_runtime_client = DownRuntime()
    agent = client.get("/api/v1/agent/mcp")
    diagnostics = client.get("/api/v1/agent/diagnostics")
    health = client.get("/api/v1/health")
    vault = client.get(f"/api/v1/knowledge-bases/{context['knowledge_base_id']}/vault/files")
    legacy = client.get("/api/v1/tutor/conversations")

    assert agent.status_code == 503
    assert agent.json() == {"detail": "runtime_unavailable"}
    assert agent.headers["retry-after"] == "1"
    assert diagnostics.status_code == 200
    assert diagnostics.json()["status"] == "degraded"
    assert diagnostics.json()["runtime"] == {
        "status": "unavailable",
        "code": "runtime_unavailable",
    }
    assert health.status_code == vault.status_code == legacy.status_code == 200


def test_legacy_tutor_history_remains_read_only_and_acl_hidden(
    acceptance_context: tuple[TestClient, dict[str, Any]],
) -> None:
    client, context = acceptance_context
    conversation_id = context["conversation_id"]
    history = client.get(f"/api/v1/tutor/conversations/{conversation_id}")
    mutation = client.post("/api/v1/tutor/messages", json={"content": "new message"})

    assert history.status_code == 200
    assert [message["role"] for message in history.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assert mutation.status_code == 410
    assert mutation.json() == _RETIRED
    assert client.get("/api/v1/tutor/status").status_code == 404

    context["use_user"](context["outsider_id"])
    hidden = client.get(f"/api/v1/tutor/conversations/{conversation_id}")
    assert hidden.status_code == 404
    assert hidden.json() == {"detail": "tutor_conversation_not_found"}


def test_diagnostics_allowlist_drops_runtime_secrets_and_private_details(
    acceptance_context: tuple[TestClient, dict[str, Any]],
) -> None:
    client, context = acceptance_context
    app = context["app"]
    assert isinstance(app, FastAPI)

    class LeakyRuntime:
        async def proxy(self, method: str, path: str, payload=None):
            del method, path, payload
            return {
                "status": "ok",
                "protocol_version": "1",
                "token": "runtime-super-secret",
                "upstream_commit": "private-upstream-commit",
                "providers": [
                    {
                        "id": "claude",
                        "enabled": True,
                        "status": "ok",
                        "api_key": "sk-provider-secret",
                        "detail": "C:/private/provider/config.json",
                    }
                ],
                "mcp": [
                    {
                        "name": "filesystem",
                        "status": "connected",
                        "authorization": "Bearer mcp-secret",
                    }
                ],
            }

    app.state.agent_runtime_client = LeakyRuntime()
    response = client.get("/api/v1/agent/diagnostics")

    assert response.status_code == 200
    assert response.json()["runtime"] == {"status": "ok", "protocol_version": "1"}
    assert response.json()["providers"] == [{"id": "claude", "enabled": True, "status": "ok"}]
    assert response.json()["mcp"] == [{"name": "filesystem", "status": "connected"}]
    serialized = response.text.casefold()
    for forbidden in (
        "runtime-super-secret",
        "private-upstream-commit",
        "sk-provider-secret",
        "c:/private",
        "mcp-secret",
    ):
        assert forbidden not in serialized


def test_verified_shadow_cutover_and_rollback_switch_the_real_workspace_reader(
    acceptance_context: tuple[TestClient, dict[str, Any]],
) -> None:
    _, context = acceptance_context
    factory = context["factory"]
    assert isinstance(factory, sessionmaker)

    with factory() as db:
        owner = db.get(User, context["owner_id"])
        assert owner is not None
        migrator = VaultMigrator(
            session=db,
            object_storage=MemoryObjectStorage(),
            vault_root=context["tmp_path"] / "migration-vault",
            artifact_root=context["tmp_path"] / "migration-artifacts",
        )
        manifest = migrator.inventory(knowledge_base_id=context["knowledge_base_id"])
        copy_result = migrator.copy(manifest)
        verify_result = migrator.verify(manifest)
        shadow = migrator.activate_shadow(manifest)
        cutover = migrator.cutover(manifest)

        revision = db.scalar(
            select(MarkdownRevision).where(MarkdownRevision.note_id == context["note_id"])
        )
        assert revision is not None
        revision.markdown = "legacy changed after cutover"
        revision.content_sha256 = hashlib.sha256(revision.markdown.encode()).hexdigest()
        db.flush()

        vault_read = load_published_note(
            db,
            owner,
            context["knowledge_base_id"],
            context["note_id"],
        )
        rollback = migrator.rollback(manifest)
        legacy_read = load_published_note(
            db,
            owner,
            context["knowledge_base_id"],
            context["note_id"],
        )

        assert copy_result.conflicts == []
        assert verify_result.hash_mismatches == []
        assert shadow.phase is MigrationPhase.SHADOW
        assert cutover.phase is MigrationPhase.VAULT_AUTHORITATIVE
        assert vault_read.markdown == "legacy authoritative body"
        assert rollback.phase is MigrationPhase.LEGACY_AUTHORITATIVE
        assert legacy_read.markdown == "legacy changed after cutover"
        assert (migrator.scoped_vault_root(manifest) / manifest.entries[0].relative_path).exists()
