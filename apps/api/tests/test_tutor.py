from __future__ import annotations

import inspect
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

import tutor_api.agent.models  # noqa: F401
import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.identity.router import get_current_user
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.main import create_app
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.tutor.models import TutorConversation, TutorMessage, TutorMessageRole
from tutor_api.tutor.schemas import TutorCitationResponse

_RETIRED = {
    "code": "legacy_tutor_retired",
    "replacement": "/api/v1/agent",
}


@pytest.fixture
def legacy_context(
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
    created_at = datetime(2026, 8, 28, 8, 30, tzinfo=UTC)

    with factory.begin() as db:
        owner = User(
            email="legacy-owner@example.com",
            username="legacy-owner",
            password_hash="hash",
        )
        outsider = User(
            email="legacy-outsider@example.com",
            username="legacy-outsider",
            password_hash="hash",
        )
        db.add_all([owner, outsider])
        db.flush()
        space = Space(owner_id=owner.id, kind=SpaceKind.PERSONAL, name="Legacy Tutor")
        outsider_space = Space(
            owner_id=outsider.id,
            kind=SpaceKind.PERSONAL,
            name="Legacy outsider",
        )
        db.add_all([space, outsider_space])
        db.flush()
        knowledge_base = KnowledgeBase(
            space_id=space.id,
            owner_user_id=owner.id,
            created_by_user_id=owner.id,
            name="Legacy KB",
        )
        other_knowledge_base = KnowledgeBase(
            space_id=space.id,
            owner_user_id=owner.id,
            created_by_user_id=owner.id,
            name="Other KB",
        )
        db.add_all([knowledge_base, other_knowledge_base])
        db.flush()
        conversation = TutorConversation(
            user_id=owner.id,
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            title="Legacy path loss conversation",
            created_at=created_at,
            updated_at=created_at + timedelta(minutes=1),
        )
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                TutorMessage(
                    conversation_id=conversation.id,
                    user_id=owner.id,
                    space_id=space.id,
                    knowledge_base_id=knowledge_base.id,
                    role=TutorMessageRole.USER,
                    content="What is path loss?",
                    citations=[],
                    created_at=created_at,
                ),
                TutorMessage(
                    conversation_id=conversation.id,
                    user_id=owner.id,
                    space_id=space.id,
                    knowledge_base_id=knowledge_base.id,
                    role=TutorMessageRole.ASSISTANT,
                    content="A legacy grounded answer.",
                    citations=[
                        {
                            "id": "legacy-citation",
                            "source_name": "wireless.pdf",
                            "page_number": 9,
                        }
                    ],
                    created_at=created_at + timedelta(seconds=1),
                ),
            ]
        )
        ids = {
            "owner_id": owner.id,
            "outsider_id": outsider.id,
            "knowledge_base_id": knowledge_base.id,
            "other_knowledge_base_id": other_knowledge_base.id,
            "conversation_id": conversation.id,
        }

    app = create_app(
        Settings(
            app_env="test",
            agent_runtime_url="http://127.0.0.1:8765",
            agent_runtime_token="runtime-token",
            agent_capability_secret="capability-secret-capability-secret",
            agent_vault_root=str(tmp_path / "vault"),
            agent_sidecar_root=str(tmp_path / "sidecars"),
        ),
        factory,
    )

    def current_user() -> User:
        with factory() as db:
            user = db.get(User, ids["owner_id"])
            assert user is not None
            db.expunge(user)
            return user

    app.dependency_overrides[get_current_user] = current_user
    with TestClient(app) as client:
        ids.update({"app": app, "factory": factory})
        yield client, ids
    engine.dispose()


def test_legacy_history_list_and_get_remain_read_only(
    legacy_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = legacy_context
    knowledge_base_id = context["knowledge_base_id"]
    conversation_id = context["conversation_id"]

    nested_list = client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations")
    global_list = client.get("/api/v1/tutor/conversations")
    nested_get = client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations/{conversation_id}"
    )
    global_get = client.get(f"/api/v1/tutor/conversations/{conversation_id}")

    assert nested_list.status_code == 200
    assert global_list.status_code == 200
    assert nested_list.json() == global_list.json()
    assert [item["id"] for item in nested_list.json()] == [str(conversation_id)]
    assert nested_get.status_code == 200
    assert global_get.status_code == 200
    assert nested_get.json() == global_get.json()
    body = global_get.json()
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert body["messages"][1]["citations"] == [
        {
            "id": "legacy-citation",
            "kind": "knowledge",
            "source_name": "wireless.pdf",
            "page_number": 9,
            "knowledge_base_id": None,
            "knowledge_base_name": None,
            "space_id": None,
            "url": None,
        }
    ]


@pytest.mark.parametrize(
    ("url", "payload"),
    [
        ("/api/v1/tutor/conversations", {"prompt": "new"}),
        ("/api/v1/tutor/messages", {"content": "new"}),
    ],
)
def test_global_legacy_mutations_return_gone(
    legacy_context: tuple[TestClient, dict[str, object]],
    url: str,
    payload: dict[str, str],
) -> None:
    client, _ = legacy_context
    response = client.post(url, json=payload)
    assert response.status_code == 410
    assert response.json() == _RETIRED


def test_nested_legacy_mutations_return_gone(
    legacy_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = legacy_context
    knowledge_base_id = context["knowledge_base_id"]
    conversation_id = context["conversation_id"]

    created = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations",
        json={"prompt": "new"},
    )
    sent = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations/{conversation_id}/messages",
        json={"prompt": "new"},
    )

    assert created.status_code == 410
    assert created.json() == _RETIRED
    assert sent.status_code == 410
    assert sent.json() == _RETIRED


def test_legacy_conversation_acl_remains_stable_not_found(
    legacy_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = legacy_context
    app = context["app"]
    factory = context["factory"]
    conversation_id = context["conversation_id"]

    cross_base = client.get(
        f"/api/v1/knowledge-bases/{context['other_knowledge_base_id']}/tutor/conversations/{conversation_id}"
    )
    assert cross_base.status_code == 404
    assert cross_base.json() == {"detail": "tutor_conversation_not_found"}

    def outsider() -> User:
        with factory() as db:
            user = db.get(User, context["outsider_id"])
            assert user is not None
            db.expunge(user)
            return user

    app.dependency_overrides[get_current_user] = outsider
    hidden = client.get(f"/api/v1/tutor/conversations/{conversation_id}")
    assert hidden.status_code == 404
    assert hidden.json() == {"detail": "tutor_conversation_not_found"}


def test_tutor_status_and_legacy_execution_wiring_are_removed(
    legacy_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = legacy_context
    app = context["app"]
    signature = inspect.signature(create_app)
    web_search_path = Path(__file__).parents[1] / "src" / "tutor_api" / "tutor" / "web_search.py"

    assert client.get("/api/v1/tutor/status").status_code == 404
    assert "tutor_adapter" not in signature.parameters
    assert "tutor_web_search_adapter" not in signature.parameters
    assert not hasattr(app.state, "tutor_adapter")
    assert not hasattr(app.state, "tutor_semaphore")
    assert not hasattr(app.state, "tutor_web_search_adapter")
    assert not web_search_path.exists()


def test_tutor_citation_schema_accepts_legacy_knowledge_citation_json() -> None:
    citation = TutorCitationResponse.model_validate(
        {
            "id": "legacy-citation",
            "source_name": "legacy.pdf",
            "page_number": 9,
        }
    )

    assert citation.kind == "knowledge"
    assert citation.knowledge_base_id is None
    assert citation.knowledge_base_name is None
    assert citation.space_id is None
    assert citation.url is None
