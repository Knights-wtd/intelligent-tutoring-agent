from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
from tutor_api.classrooms.models import ClassroomMembership, ClassroomRole
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import KnowledgeBase, KnowledgeBaseState
from tutor_api.knowledge.service import create_knowledge_base
from tutor_api.main import create_app
from tutor_api.spaces.models import Space

SAFE_RESPONSE_FIELDS = {
    "id",
    "space_id",
    "name",
    "state",
    "created_at",
    "updated_at",
}


def make_client() -> tuple[TestClient, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    app = create_app(Settings(app_env="test"), sessionmaker(bind=engine))
    return TestClient(app), engine


def register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "password": "Correct horse battery staple 9",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_classroom(client: TestClient, name: str = "七年级数学") -> dict:
    response = client.post("/api/v1/classrooms", json={"name": name})
    assert response.status_code == 201
    return response.json()


def add_classroom_member(
    owner: TestClient,
    classroom: dict,
    username: str,
    role: ClassroomRole,
) -> tuple[TestClient, dict]:
    member = TestClient(owner.app)
    registration = register(member, username)
    invite = owner.post(
        f"/api/v1/classrooms/{classroom['id']}/invites",
        json={"expires_in_hours": 24, "max_uses": 1},
    )
    assert invite.status_code == 201
    joined = member.post("/api/v1/classrooms/join", json={"code": invite.json()["code"]})
    assert joined.status_code == 200
    if role == ClassroomRole.TEACHER:
        promoted = owner.patch(
            f"/api/v1/classrooms/{classroom['id']}/members/{registration['user']['id']}",
            json={"role": "teacher"},
        )
        assert promoted.status_code == 200
    return member, registration


def post_knowledge_base(client: TestClient, space_id: str, name: str) -> dict:
    response = client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases",
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_knowledge_base_routes_require_authentication() -> None:
    client, engine = make_client()
    space_id = uuid4()
    knowledge_base_id = uuid4()

    assert client.get(f"/api/v1/spaces/{space_id}/knowledge-bases").status_code == 401
    assert client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": "数学"}
    ).status_code == 401
    assert client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}").status_code == 401
    engine.dispose()


def test_personal_owner_can_create_list_and_read_trimmed_knowledge_base() -> None:
    client, engine = make_client()
    registration = register(client, "personal-owner")
    user_id = registration["user"]["id"]
    space_id = registration["personal_space"]["id"]

    created_response = client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases",
        json={"name": "  高等数学  "},
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["name"] == "高等数学"
    assert created["space_id"] == space_id
    assert created["state"] == "active"
    assert set(created) == SAFE_RESPONSE_FIELDS
    listed = client.get(f"/api/v1/spaces/{space_id}/knowledge-bases")
    detail = client.get(f"/api/v1/knowledge-bases/{created['id']}")
    assert listed.status_code == detail.status_code == 200
    assert listed.json() == [created]
    assert detail.json() == created

    with sessionmaker(bind=engine)() as session:
        stored = session.get(KnowledgeBase, UUID(created["id"]))
        assert stored is not None
        assert str(stored.owner_user_id) == user_id
        assert str(stored.created_by_user_id) == user_id
        assert stored.space_id == UUID(space_id)
        assert stored.state == KnowledgeBaseState.ACTIVE
    engine.dispose()


def test_personal_space_is_hidden_from_non_owner_for_read_and_write() -> None:
    owner, engine = make_client()
    owner_registration = register(owner, "personal-resource-owner")
    space_id = owner_registration["personal_space"]["id"]
    knowledge_base = post_knowledge_base(owner, space_id, "私有教材")
    outsider = TestClient(owner.app)
    register(outsider, "personal-outsider")

    assert outsider.get(f"/api/v1/spaces/{space_id}/knowledge-bases").status_code == 404
    assert outsider.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}").status_code == 404
    assert outsider.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": "越权"}
    ).status_code == 404
    engine.dispose()


def test_classroom_owner_and_teacher_can_create_knowledge_bases() -> None:
    owner, engine = make_client()
    register(owner, "classroom-owner")
    classroom = create_classroom(owner)
    space_id = classroom["space"]["id"]
    teacher, _ = add_classroom_member(
        owner, classroom, "classroom-teacher", ClassroomRole.TEACHER
    )

    owner_created = post_knowledge_base(owner, space_id, "教师资料")
    teacher_created = post_knowledge_base(teacher, space_id, "课堂习题")

    listed = teacher.get(f"/api/v1/spaces/{space_id}/knowledge-bases")
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()} == {
        owner_created["id"],
        teacher_created["id"],
    }
    engine.dispose()


def test_classroom_student_can_read_but_cannot_create() -> None:
    owner, engine = make_client()
    register(owner, "student-classroom-owner")
    classroom = create_classroom(owner)
    space_id = classroom["space"]["id"]
    knowledge_base = post_knowledge_base(owner, space_id, "课堂教材")
    student, _ = add_classroom_member(
        owner, classroom, "classroom-student", ClassroomRole.STUDENT
    )

    listed = student.get(f"/api/v1/spaces/{space_id}/knowledge-bases")
    detail = student.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}")
    forbidden = student.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": "学生上传"}
    )

    assert listed.status_code == detail.status_code == 200
    assert listed.json() == [knowledge_base]
    assert detail.json() == knowledge_base
    assert forbidden.status_code == 403
    engine.dispose()


def test_classroom_nonmember_cannot_discover_or_mutate_knowledge_bases() -> None:
    owner, engine = make_client()
    register(owner, "hidden-classroom-owner")
    classroom = create_classroom(owner)
    space_id = classroom["space"]["id"]
    knowledge_base = post_knowledge_base(owner, space_id, "隐藏教材")
    outsider = TestClient(owner.app)
    register(outsider, "classroom-nonmember")

    assert outsider.get(f"/api/v1/spaces/{space_id}/knowledge-bases").status_code == 404
    assert outsider.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}").status_code == 404
    assert outsider.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": "越权教材"}
    ).status_code == 404
    engine.dispose()


def test_unknown_spaces_and_knowledge_bases_are_hidden() -> None:
    client, engine = make_client()
    register(client, "unknown-resource-reader")

    assert client.get(f"/api/v1/spaces/{uuid4()}/knowledge-bases").status_code == 404
    assert client.post(
        f"/api/v1/spaces/{uuid4()}/knowledge-bases", json={"name": "未知空间"}
    ).status_code == 404
    assert client.get(f"/api/v1/knowledge-bases/{uuid4()}").status_code == 404
    engine.dispose()


def test_space_lists_are_isolated() -> None:
    owner, engine = make_client()
    registration = register(owner, "list-isolation-owner")
    personal_space_id = registration["personal_space"]["id"]
    classroom = create_classroom(owner, "隔离课堂")
    classroom_space_id = classroom["space"]["id"]
    personal = post_knowledge_base(owner, personal_space_id, "个人教材")
    classroom_kb = post_knowledge_base(owner, classroom_space_id, "课堂教材")

    personal_list = owner.get(f"/api/v1/spaces/{personal_space_id}/knowledge-bases")
    classroom_list = owner.get(f"/api/v1/spaces/{classroom_space_id}/knowledge-bases")

    assert personal_list.json() == [personal]
    assert classroom_list.json() == [classroom_kb]
    engine.dispose()


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
def test_knowledge_base_name_validation_rejects_blank_and_overlong_names(name: str) -> None:
    client, engine = make_client()
    registration = register(client, f"validation-{len(name)}-{name == '   '}")
    space_id = registration["personal_space"]["id"]

    response = client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases",
        json={"name": name},
    )

    assert response.status_code == 422
    engine.dispose()


def test_duplicate_name_conflict_is_stable_and_other_spaces_allow_the_same_name() -> None:
    first, engine = make_client()
    first_registration = register(first, "duplicate-first")
    first_space_id = first_registration["personal_space"]["id"]
    second = TestClient(first.app)
    second_registration = register(second, "duplicate-second")
    second_space_id = second_registration["personal_space"]["id"]
    post_knowledge_base(first, first_space_id, "同名教材")

    duplicate = first.post(
        f"/api/v1/spaces/{first_space_id}/knowledge-bases",
        json={"name": "同名教材"},
    )
    recovered = first.post(
        f"/api/v1/spaces/{first_space_id}/knowledge-bases",
        json={"name": "冲突后可继续"},
    )
    other_space = second.post(
        f"/api/v1/spaces/{second_space_id}/knowledge-bases",
        json={"name": "同名教材"},
    )

    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "知识库名称已存在"}
    assert recovered.status_code == 201
    assert other_space.status_code == 201
    assert first.get(f"/api/v1/spaces/{first_space_id}/knowledge-bases").status_code == 200
    engine.dispose()


def test_known_knowledge_base_uuid_cannot_cross_permission_boundary() -> None:
    owner, engine = make_client()
    registration = register(owner, "known-uuid-owner")
    knowledge_base = post_knowledge_base(
        owner, registration["personal_space"]["id"], "UUID 私有教材"
    )
    outsider = TestClient(owner.app)
    register(outsider, "known-uuid-outsider")

    response = outsider.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}")

    assert response.status_code == 404
    assert response.json() == {"detail": "资源不存在"}
    engine.dispose()


def test_owner_space_and_creator_fields_cannot_be_forged() -> None:
    client, engine = make_client()
    registration = register(client, "anti-forgery-owner")
    space_id = registration["personal_space"]["id"]
    forged_id = str(uuid4())

    response = client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases",
        json={
            "name": "伪造测试",
            "space_id": forged_id,
            "owner_user_id": forged_id,
            "created_by_user_id": forged_id,
            "state": "archived",
        },
    )

    assert response.status_code == 422
    with sessionmaker(bind=engine)() as session:
        assert session.scalar(select(KnowledgeBase).where(KnowledgeBase.name == "伪造测试")) is None
    engine.dispose()


def test_list_order_is_stable_and_responses_only_contain_safe_fields() -> None:
    client, engine = make_client()
    registration = register(client, "stable-list-owner")
    space_id = registration["personal_space"]["id"]
    for name in ("第三", "第一", "第二"):
        post_knowledge_base(client, space_id, name)

    first = client.get(f"/api/v1/spaces/{space_id}/knowledge-bases")
    second = client.get(f"/api/v1/spaces/{space_id}/knowledge-bases")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json() == sorted(
        first.json(), key=lambda item: (item["created_at"], item["id"])
    )
    assert all(set(item) == SAFE_RESPONSE_FIELDS for item in first.json())
    detail = client.get(f"/api/v1/knowledge-bases/{first.json()[0]['id']}")
    assert set(detail.json()) == SAFE_RESPONSE_FIELDS
    engine.dispose()


def test_service_conflict_rolls_back_and_same_session_remains_usable() -> None:
    client, engine = make_client()
    registration = register(client, "same-session-owner")
    user_id = UUID(registration["user"]["id"])
    space_id = UUID(registration["personal_space"]["id"])

    with Session(engine) as session:
        user = session.get(User, user_id)
        space = session.get(Space, space_id)
        assert user is not None and space is not None
        create_knowledge_base(session, user, space.id, "重复名称")
        session.commit()

        with pytest.raises(HTTPException) as conflict:
            create_knowledge_base(session, user, space.id, "重复名称")
        assert conflict.value.status_code == 409

        recovered = create_knowledge_base(session, user, space.id, "恢复成功")
        session.commit()
        assert recovered.id is not None
        assert session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.space_id == space.id,
                KnowledgeBase.name == "恢复成功",
            )
        ) is not None
    engine.dispose()


def test_classroom_permissions_come_from_server_side_membership() -> None:
    owner, engine = make_client()
    register(owner, "membership-owner")
    classroom = create_classroom(owner)
    space_id = classroom["space"]["id"]
    student, registration = add_classroom_member(
        owner, classroom, "membership-student", ClassroomRole.STUDENT
    )

    forged = student.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases",
        json={"name": "角色伪造", "role": "teacher"},
    )

    assert forged.status_code == 422
    with sessionmaker(bind=engine)() as session:
        membership = session.scalar(
            select(ClassroomMembership).where(
                ClassroomMembership.user_id == UUID(registration["user"]["id"])
            )
        )
        assert membership is not None
        assert membership.role == ClassroomRole.STUDENT
        assert session.scalar(select(KnowledgeBase).where(KnowledgeBase.name == "角色伪造")) is None
    engine.dispose()
