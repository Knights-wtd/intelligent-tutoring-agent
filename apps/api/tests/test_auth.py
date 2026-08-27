import hashlib
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import UserSession
from tutor_api.identity.rate_limit import LoginRateLimiter
from tutor_api.main import create_app

VALID_REGISTRATION = {
    "email": "learner@example.com",
    "username": "learner",
    "password": "Correct horse battery staple 9",
}


def make_client() -> tuple[TestClient, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    return TestClient(create_app(Settings(app_env="test"), sessionmaker(bind=engine))), engine


def test_register_creates_personal_space_and_session() -> None:
    client, engine = make_client()

    response = client.post("/api/v1/auth/register", json=VALID_REGISTRATION)

    assert response.status_code == 201
    assert response.json()["user"]["username"] == "learner"
    assert response.json()["personal_space"]["kind"] == "personal"
    assert "session=" in response.headers["set-cookie"]
    engine.dispose()


def test_app_factory_builds_session_factory_from_a_test_database_url() -> None:
    app = create_app(Settings(app_env="test", database_url="sqlite://"))

    assert app.state.session_factory is not None


def test_login_sets_a_new_session_cookie_for_registered_user() -> None:
    client, engine = make_client()
    client.post("/api/v1/auth/register", json=VALID_REGISTRATION)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "LEARNER@example.com", "password": VALID_REGISTRATION["password"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "id": response.json()["user"]["id"],
            "email": "learner@example.com",
            "username": "learner",
        }
    }
    assert "session=" in response.headers["set-cookie"]
    engine.dispose()


def test_me_returns_the_current_user_from_a_valid_session() -> None:
    client, engine = make_client()
    registered = client.post("/api/v1/auth/register", json=VALID_REGISTRATION)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "user": registered.json()["user"],
        "personal_space": registered.json()["personal_space"],
    }
    engine.dispose()


def test_logout_revokes_the_session_and_clears_the_cookie() -> None:
    client, engine = make_client()
    client.post("/api/v1/auth/register", json=VALID_REGISTRATION)

    logout = client.post("/api/v1/auth/logout")
    current_user = client.get("/api/v1/auth/me")

    assert logout.status_code == 204
    assert "session=\"\"" in logout.headers["set-cookie"]
    assert current_user.status_code == 401
    engine.dispose()


def test_registration_normalizes_email_and_rejects_duplicates_and_invalid_input() -> None:
    client, engine = make_client()
    first = client.post(
        "/api/v1/auth/register",
        json={**VALID_REGISTRATION, "email": " Learner@Example.COM "},
    )
    duplicate = client.post("/api/v1/auth/register", json=VALID_REGISTRATION)
    invalid = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "username": "no spaces", "password": "too-short"},
    )

    assert first.status_code == 201
    assert first.json()["user"]["email"] == "learner@example.com"
    assert duplicate.status_code == 409
    assert invalid.status_code == 422
    assert "too-short" not in invalid.text
    engine.dispose()


def test_validation_errors_never_echo_password_when_another_field_is_invalid() -> None:
    client, engine = make_client()
    password = "Correct horse battery staple 9"

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "learner@example.com", "password": password},
    )

    assert response.status_code == 422
    assert password not in response.text
    engine.dispose()


def test_login_does_not_disclose_whether_identity_or_password_failed() -> None:
    client, engine = make_client()
    client.post("/api/v1/auth/register", json=VALID_REGISTRATION)
    unknown_identity = client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "password": VALID_REGISTRATION["password"]},
    )
    incorrect_password = client.post(
        "/api/v1/auth/login",
        json={"email": VALID_REGISTRATION["email"], "password": "not the right password"},
    )

    assert unknown_identity.status_code == incorrect_password.status_code == 401
    assert unknown_identity.json() == incorrect_password.json()
    engine.dispose()


def test_me_rejects_expired_and_revoked_sessions() -> None:
    client, engine = make_client()
    client.post("/api/v1/auth/register", json=VALID_REGISTRATION)
    token = client.cookies.get("session")
    factory = sessionmaker(bind=engine)
    with factory() as session:
        user_session = session.scalar(
            select(UserSession).where(
                UserSession.token_digest == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        assert user_session is not None
        user_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    assert client.get("/api/v1/auth/me").status_code == 401

    client.post(
        "/api/v1/auth/login",
        json={
            "email": VALID_REGISTRATION["email"],
            "password": VALID_REGISTRATION["password"],
        },
    )
    token = client.cookies.get("session")
    with factory() as session:
        user_session = session.scalar(
            select(UserSession).where(
                UserSession.token_digest == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        assert user_session is not None
        user_session.revoked_at = datetime.now(UTC)
        session.commit()

    assert client.get("/api/v1/auth/me").status_code == 401
    engine.dispose()


def test_session_token_is_http_only_and_only_its_digest_is_persisted() -> None:
    client, engine = make_client()
    response = client.post("/api/v1/auth/register", json=VALID_REGISTRATION)
    token = client.cookies.get("session")
    with sessionmaker(bind=engine)() as session:
        user_session = session.scalar(select(UserSession))

        assert user_session is not None
        assert user_session.token_digest == hashlib.sha256(token.encode()).hexdigest()
        assert user_session.token_digest != token
    assert "HttpOnly" in response.headers["set-cookie"]
    assert token not in response.text
    engine.dispose()


def test_session_cookie_is_secure_only_in_production() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    production_settings = Settings(
        app_env="production",
        web_origin="https://app.example.com",
        database_url="postgresql+psycopg://user:pass@db.example.com/tutor",
        redis_url="rediss://:password@cache.example.com/0",
        object_storage_endpoint="https://objects.example.com",
        object_storage_access_key="production-key",
        object_storage_secret_key="a-long-production-secret",
    )
    client = TestClient(create_app(production_settings, sessionmaker(bind=engine)))

    response = client.post("/api/v1/auth/register", json=VALID_REGISTRATION)

    assert response.status_code == 201
    assert "Secure" in response.headers["set-cookie"]
    engine.dispose()


def test_login_accepts_username_identifier_and_normalizes_case() -> None:
    client, engine = make_client()
    client.post("/api/v1/auth/register", json=VALID_REGISTRATION)

    by_username = client.post(
        "/api/v1/auth/login",
        json={"identifier": "learner", "password": VALID_REGISTRATION["password"]},
    )
    by_legacy_email = client.post(
        "/api/v1/auth/login",
        json={"email": VALID_REGISTRATION["email"], "password": VALID_REGISTRATION["password"]},
    )
    by_uppercase_username = client.post(
        "/api/v1/auth/login",
        json={"identifier": "LEARNER", "password": VALID_REGISTRATION["password"]},
    )

    assert by_username.status_code == 200
    assert by_legacy_email.status_code == 200
    assert by_uppercase_username.status_code == 200
    assert by_username.json()["user"]["username"] == "learner"
    engine.dispose()


def test_login_rejects_identifiers_that_are_neither_email_nor_username() -> None:
    client, engine = make_client()

    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "not valid!", "password": "some password 123"},
    )

    assert response.status_code == 422
    engine.dispose()


def test_registration_casefolds_username_and_rejects_confusing_duplicates() -> None:
    client, engine = make_client()
    first = client.post(
        "/api/v1/auth/register",
        json={**VALID_REGISTRATION, "username": "Learner"},
    )
    duplicate = client.post(
        "/api/v1/auth/register",
        json={
            "email": "other.person@example.com",
            "username": "LEARNER",
            "password": "Another correct horse staple 7",
        },
    )

    assert first.status_code == 201
    assert first.json()["user"]["username"] == "learner"
    assert duplicate.status_code == 409
    engine.dispose()


def test_login_locks_out_after_repeated_failures_and_unlocks_after_window() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    settings = Settings(app_env="test", login_max_attempts=3, login_lockout_seconds=60)
    app = create_app(settings, sessionmaker(bind=engine))
    clock = {"now": 0.0}
    app.state.login_rate_limiter = LoginRateLimiter(
        max_attempts=3, lockout_seconds=60, clock=lambda: clock["now"]
    )
    client = TestClient(app)
    client.post("/api/v1/auth/register", json=VALID_REGISTRATION)
    wrong = {"password": "not the right password"}

    for _ in range(3):
        assert (
            client.post("/api/v1/auth/login", json={"identifier": "learner", **wrong}).status_code
            == 401
        )

    locked = client.post(
        "/api/v1/auth/login",
        json={"identifier": "learner", "password": VALID_REGISTRATION["password"]},
    )
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1
    assert client.post(
        "/api/v1/auth/login",
        json={"identifier": "learner@example.com", "password": "x" * 16},
    ).status_code == 429

    clock["now"] = 61.0
    recovered = client.post(
        "/api/v1/auth/login",
        json={"identifier": "learner", "password": VALID_REGISTRATION["password"]},
    )
    assert recovered.status_code == 200
    engine.dispose()


def test_register_locks_out_bulk_creation_and_successes_do_not_reset_the_window() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    settings = Settings(app_env="test", register_max_attempts=2, register_lockout_seconds=600)
    app = create_app(settings, sessionmaker(bind=engine))
    clock = {"now": 0.0}
    app.state.register_rate_limiter = LoginRateLimiter(
        max_attempts=2, lockout_seconds=600, clock=lambda: clock["now"]
    )
    client = TestClient(app)

    def registration(index: int) -> dict[str, object]:
        return {
            "email": f"bulk-{index}@example.com",
            "username": f"bulk-{index}",
            "password": VALID_REGISTRATION["password"],
        }

    assert client.post("/api/v1/auth/register", json=registration(1)).status_code == 201
    assert client.post("/api/v1/auth/register", json=registration(2)).status_code == 201

    locked = client.post("/api/v1/auth/register", json=registration(3))
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1

    clock["now"] = 601.0
    assert client.post("/api/v1/auth/register", json=registration(3)).status_code == 201
    engine.dispose()


def test_successful_login_resets_the_failure_counter() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    app = create_app(
        Settings(app_env="test", login_max_attempts=3, login_lockout_seconds=60),
        sessionmaker(bind=engine),
    )
    client = TestClient(app)
    client.post("/api/v1/auth/register", json=VALID_REGISTRATION)

    for _ in range(2):
        client.post(
            "/api/v1/auth/login",
            json={"identifier": "learner", "password": "not the right password"},
        )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"identifier": "learner", "password": VALID_REGISTRATION["password"]},
        ).status_code
        == 200
    )
    for _ in range(2):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"identifier": "learner", "password": "not the right password"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"identifier": "learner", "password": VALID_REGISTRATION["password"]},
        ).status_code
        == 200
    )
    engine.dispose()


def test_login_purges_expired_and_revoked_sessions() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    app = create_app(
        Settings(app_env="test", session_purge_probability=1.0), sessionmaker(bind=engine)
    )
    client = TestClient(app)
    client.post("/api/v1/auth/register", json=VALID_REGISTRATION)
    stale_token = client.cookies.get("session")
    factory = sessionmaker(bind=engine)
    with factory() as session:
        stale = session.scalar(
            select(UserSession).where(
                UserSession.token_digest == hashlib.sha256(stale_token.encode()).hexdigest()
            )
        )
        assert stale is not None
        stale.expires_at = datetime.now(UTC) - timedelta(days=30)
        session.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "learner", "password": VALID_REGISTRATION["password"]},
    )

    assert response.status_code == 200
    fresh_token = client.cookies.get("session")
    with factory() as session:
        remaining = session.scalars(select(UserSession)).all()
        assert [row.token_digest for row in remaining] == [
            hashlib.sha256(fresh_token.encode()).hexdigest()
        ]
    engine.dispose()
