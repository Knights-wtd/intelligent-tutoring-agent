from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
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


def test_spaces_returns_personal_and_joined_classroom_spaces() -> None:
    owner, engine = make_client()
    owner_registration = register(owner, "owner")
    created = owner.post("/api/v1/classrooms", json={"name": "七年级数学"})
    assert created.status_code == 201

    student = TestClient(owner.app)
    student_registration = register(student, "student")
    joined = student.post("/api/v1/classrooms/join", json={"code": created.json()["invite_code"]})
    assert joined.status_code == 200

    owner_spaces = owner.get("/api/v1/spaces")
    student_spaces = student.get("/api/v1/spaces")

    assert owner_spaces.status_code == student_spaces.status_code == 200
    assert owner_spaces.json() == [
        owner_registration["personal_space"],
        {"id": created.json()["space"]["id"], "kind": "classroom", "name": "七年级数学"},
    ]
    assert student_spaces.json() == [
        student_registration["personal_space"],
        {"id": created.json()["space"]["id"], "kind": "classroom", "name": "七年级数学"},
    ]
    engine.dispose()


def test_spaces_requires_authentication() -> None:
    client, engine = make_client()

    assert client.get("/api/v1/spaces").status_code == 401
    engine.dispose()
