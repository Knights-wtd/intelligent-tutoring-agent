from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
from tutor_api.classrooms.models import ClassroomInvite, ClassroomMembership, ClassroomRole
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.main import create_app


def make_client() -> tuple[TestClient, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    return TestClient(create_app(Settings(app_env="test"), sessionmaker(bind=engine))), engine


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


def test_create_classroom_creates_space_owner_membership_and_one_use_student_invite() -> None:
    client, engine = make_client()
    owner = register(client, "owner")["user"]

    response = client.post("/api/v1/classrooms", json={"name": "七年级数学"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "七年级数学"
    assert body["space"] == {"id": body["space"]["id"], "kind": "classroom", "name": "七年级数学"}
    assert body["invite_code"]
    assert len(body["invite_code"]) >= 20
    with sessionmaker(bind=engine)() as session:
        membership = session.scalar(select(ClassroomMembership))
        invite = session.scalar(select(ClassroomInvite))
        assert membership is not None
        assert str(membership.user_id) == owner["id"]
        assert membership.role == ClassroomRole.OWNER
        assert invite is not None
        assert invite.role == ClassroomRole.STUDENT
        assert invite.max_uses == 1
        assert invite.use_count == 0
        assert invite.code_digest != body["invite_code"]
    engine.dispose()


def test_join_consumes_a_one_use_invite_and_rejects_duplicate_membership() -> None:
    owner, engine = make_client()
    register(owner, "owner")
    classroom = create_classroom(owner)
    student = TestClient(owner.app)
    register(student, "student")

    joined = student.post("/api/v1/classrooms/join", json={"code": classroom["invite_code"]})
    duplicate = student.post("/api/v1/classrooms/join", json={"code": classroom["invite_code"]})
    another = TestClient(owner.app)
    register(another, "another")
    exhausted = another.post("/api/v1/classrooms/join", json={"code": classroom["invite_code"]})

    assert joined.status_code == 200
    assert joined.json()["membership"]["role"] == "student"
    assert duplicate.status_code == 409
    assert exhausted.status_code == 403
    with sessionmaker(bind=engine)() as session:
        invite = session.scalar(select(ClassroomInvite))
        assert invite is not None and invite.use_count == 1
    engine.dispose()


def test_join_rejects_expired_and_revoked_invites() -> None:
    owner, engine = make_client()
    register(owner, "owner")
    classroom = create_classroom(owner)
    student = TestClient(owner.app)
    register(student, "student")
    with sessionmaker(bind=engine)() as session:
        invite = session.scalar(select(ClassroomInvite))
        assert invite is not None
        invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    response = student.post("/api/v1/classrooms/join", json={"code": classroom["invite_code"]})
    assert response.status_code == 403
    with sessionmaker(bind=engine)() as session:
        invite = session.scalar(select(ClassroomInvite))
        assert invite is not None
        invite.expires_at = datetime.now(UTC) + timedelta(days=1)
        invite.revoked_at = datetime.now(UTC)
        session.commit()

    response = student.post("/api/v1/classrooms/join", json={"code": classroom["invite_code"]})
    assert response.status_code == 403
    engine.dispose()


def test_classroom_is_hidden_from_non_members() -> None:
    owner, engine = make_client()
    register(owner, "owner")
    classroom = create_classroom(owner)
    outsider = TestClient(owner.app)
    register(outsider, "outsider")

    assert outsider.get(f"/api/v1/classrooms/{classroom['id']}").status_code == 404
    assert owner.get(f"/api/v1/classrooms/{classroom['id']}").status_code == 200
    engine.dispose()


def test_owner_can_manage_member_roles_but_cannot_change_owner() -> None:
    owner, engine = make_client()
    owner_info = register(owner, "owner")["user"]
    classroom = create_classroom(owner)
    student = TestClient(owner.app)
    student_info = register(student, "student")["user"]
    student.post("/api/v1/classrooms/join", json={"code": classroom["invite_code"]})

    promoted = owner.patch(
        f"/api/v1/classrooms/{classroom['id']}/members/{student_info['id']}",
        json={"role": "teacher"},
    )
    owner_change = owner.patch(
        f"/api/v1/classrooms/{classroom['id']}/members/{owner_info['id']}",
        json={"role": "teacher"},
    )
    removed = owner.patch(
        f"/api/v1/classrooms/{classroom['id']}/members/{student_info['id']}", json={"remove": True}
    )

    assert promoted.status_code == 200
    assert promoted.json()["role"] == "teacher"
    assert owner_change.status_code == 403
    assert removed.status_code == 204
    engine.dispose()


def test_teacher_cannot_change_roles_but_can_create_bounded_invites() -> None:
    owner, engine = make_client()
    register(owner, "owner")
    classroom = create_classroom(owner)
    teacher = TestClient(owner.app)
    teacher_info = register(teacher, "teacher")["user"]
    teacher.post("/api/v1/classrooms/join", json={"code": classroom["invite_code"]})
    promote = owner.patch(
        f"/api/v1/classrooms/{classroom['id']}/members/{teacher_info['id']}",
        json={"role": "teacher"},
    )
    assert promote.status_code == 200

    forbidden = teacher.patch(
        f"/api/v1/classrooms/{classroom['id']}/members/{teacher_info['id']}",
        json={"role": "student"},
    )
    invite = teacher.post(
        f"/api/v1/classrooms/{classroom['id']}/invites",
        json={"expires_in_hours": 24, "max_uses": 3},
    )
    invalid = teacher.post(
        f"/api/v1/classrooms/{classroom['id']}/invites",
        json={"expires_in_hours": 0, "max_uses": 0},
    )

    assert forbidden.status_code == 403
    assert invite.status_code == 201
    assert invite.json()["code"]
    assert invalid.status_code == 422
    engine.dispose()
