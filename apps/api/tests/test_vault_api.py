from collections.abc import Callable, Generator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

import tutor_api.agent.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.classrooms.models import (
    Classroom,
    ClassroomMembership,
    ClassroomRole,
)
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.identity.router import get_current_user
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault.router import router as vault_router
from tutor_api.vault.service import VaultService


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

    with factory.begin() as session:
        owner = User(email="vault-owner@example.com", username="vault-owner", password_hash="hash")
        student = User(
            email="vault-student@example.com", username="vault-student", password_hash="hash"
        )
        outsider = User(
            email="vault-outsider@example.com", username="vault-outsider", password_hash="hash"
        )
        session.add_all([owner, student, outsider])
        session.flush()
        space = Space(owner_id=owner.id, kind=SpaceKind.CLASSROOM, name="Vault Classroom")
        session.add(space)
        session.flush()
        classroom = Classroom(space_id=space.id, owner_id=owner.id, name="Vault Classroom")
        session.add(classroom)
        session.flush()
        session.add_all(
            [
                ClassroomMembership(
                    classroom_id=classroom.id, user_id=owner.id, role=ClassroomRole.OWNER
                ),
                ClassroomMembership(
                    classroom_id=classroom.id, user_id=student.id, role=ClassroomRole.STUDENT
                ),
            ]
        )
        knowledge_base = KnowledgeBase(
            space_id=space.id,
            owner_user_id=owner.id,
            created_by_user_id=owner.id,
            name="Vault API",
        )
        session.add(knowledge_base)
        session.flush()
        ids = {
            "owner_id": owner.id,
            "student_id": student.id,
            "outsider_id": outsider.id,
            "space_id": space.id,
            "knowledge_base_id": knowledge_base.id,
        }

    app = FastAPI()
    app.state.session_factory = factory
    app.state.vault_root = tmp_path
    app.include_router(vault_router)

    def select_user(user_id: UUID) -> Callable[[], User]:
        def dependency() -> User:
            with factory() as session:
                user = session.get(User, user_id)
                assert user is not None
                session.expunge(user)
                return user

        return dependency

    app.dependency_overrides[get_current_user] = select_user(ids["owner_id"])
    client = TestClient(app)
    ids["app"] = app
    ids["factory"] = factory
    ids["select_user"] = select_user
    try:
        yield client, ids
    finally:
        client.close()
        engine.dispose()


def as_user(context: dict[str, object], user_id: UUID) -> TestClient:
    app = context["app"]
    select_user = context["select_user"]
    assert isinstance(app, FastAPI)
    assert callable(select_user)
    app.dependency_overrides[get_current_user] = select_user(user_id)
    return TestClient(app)


def test_vault_crud_and_change_set_status(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    knowledge_base_id = context["knowledge_base_id"]

    created_response = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files",
        json={"relative_path": "课程/第一章.md", "markdown": "# 第一章"},
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["relative_path"] == "课程/第一章.md"
    assert created["revision"] == 1
    assert created["sync_state"] == "synced"
    assert created["index_state"] == "pending"

    listed = client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files")
    assert listed.status_code == 200
    assert [item["vault_file_id"] for item in listed.json()] == [created["vault_file_id"]]

    read_response = client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files/{created['vault_file_id']}"
    )
    assert read_response.status_code == 200
    assert read_response.json()["markdown"] == "# 第一章"

    updated_response = client.put(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files/{created['vault_file_id']}",
        json={"markdown": "# 第一章\n\n完整正文", "expected_hash": created["content_hash"]},
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["vault_file_id"] == created["vault_file_id"]
    assert updated["revision"] == 2

    moved_response = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files/{created['vault_file_id']}/move",
        json={"relative_path": "课程/基础/第一章.md", "expected_hash": updated["content_hash"]},
    )
    assert moved_response.status_code == 200
    moved = moved_response.json()
    assert moved["vault_file_id"] == created["vault_file_id"]
    assert moved["relative_path"] == "课程/基础/第一章.md"

    status_response = client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/change-sets/{moved['change_set_id']}"
    )
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "committed"
    assert status_response.json()["entries"][0]["operation"] == "move"

    deleted_response = client.request(
        "DELETE",
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files/{created['vault_file_id']}",
        json={"expected_hash": moved["content_hash"]},
    )
    assert deleted_response.status_code == 200
    assert deleted_response.json()["is_tombstoned"] is True


def test_conflict_returns_409_and_preserves_current_content(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    client, context = api_context
    knowledge_base_id = context["knowledge_base_id"]
    created = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files",
        json={"relative_path": "conflict.md", "markdown": "current"},
    ).json()

    response = client.put(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files/{created['vault_file_id']}",
        json={"markdown": "stale overwrite", "expected_hash": "0" * 64},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["actual_hash"] == created["content_hash"]
    read_response = client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files/{created['vault_file_id']}"
    )
    assert read_response.json()["markdown"] == "current"


def test_acl_allows_student_read_but_rejects_student_write_and_outsider_read(
    api_context: tuple[TestClient, dict[str, object]],
) -> None:
    owner_client, context = api_context
    knowledge_base_id = context["knowledge_base_id"]
    owner_id = context["owner_id"]
    space_id = context["space_id"]
    factory = context["factory"]
    assert isinstance(owner_id, UUID)
    assert isinstance(space_id, UUID)
    assert isinstance(knowledge_base_id, UUID)
    assert isinstance(factory, sessionmaker)

    with factory.begin() as session:
        service = VaultService(
            session,
            vault_root=owner_client.app.state.vault_root,
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            actor_user_id=owner_id,
        )
        created = service.create("shared.md", "shared content")

    student_id = context["student_id"]
    outsider_id = context["outsider_id"]
    assert isinstance(student_id, UUID)
    assert isinstance(outsider_id, UUID)
    student = as_user(context, student_id)

    student_list = student.get(f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files")
    assert student_list.status_code == 200
    assert student_list.json()[0]["vault_file_id"] == str(created.vault_file_id)
    student_write = student.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files",
        json={"relative_path": "student.md", "markdown": "not allowed"},
    )
    assert student_write.status_code == 403

    outsider = as_user(context, outsider_id)
    outsider_read = outsider.get(f"/api/v1/knowledge-bases/{knowledge_base_id}/vault/files")
    assert outsider_read.status_code == 404
