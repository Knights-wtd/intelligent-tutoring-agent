import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.main import create_app


def make_test_app(settings: Settings) -> tuple[FastAPI, Engine]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    return create_app(settings, sessionmaker(bind=engine)), engine


def preflight_headers(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
    }


def test_health_returns_public_status_only() -> None:
    app, engine = make_test_app(Settings(_env_file=None, app_env="test", database_url="sqlite://"))
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "textbook-tutor-api"}
        assert "database_url" not in response.text
    finally:
        engine.dispose()


def test_create_app_rejects_invalid_production_settings() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="sqlite://",
        redis_url="redis://localhost:6379/0",
        object_storage_endpoint="http://localhost:9000",
        object_storage_access_key="textbook-local",
        object_storage_secret_key="replace-for-non-local-use",
        web_origin="http://localhost:3000",
    )

    with pytest.raises(RuntimeError) as exc_info:
        create_app(settings)

    message = str(exc_info.value)
    assert "OBJECT_STORAGE_SECRET_KEY must be replaced" in message
    assert "WEB_ORIGIN must use HTTPS" in message


def test_cors_preflight_allows_exact_configured_origin() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite://",
        web_origin="https://tutor.example.com",
    )

    app, engine = make_test_app(settings)
    try:
        with TestClient(app) as client:
            response = client.options(
                "/api/v1/health",
                headers=preflight_headers(settings.web_origin),
            )

        assert response.headers["access-control-allow-origin"] == settings.web_origin
    finally:
        engine.dispose()


def test_cors_preflight_allows_canonicalized_configured_origin() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite://",
        web_origin="HTTPS://EXAMPLE.COM:443",
    )
    browser_origin = "https://example.com"

    app, engine = make_test_app(settings)
    try:
        with TestClient(app) as client:
            response = client.options(
                "/api/v1/health",
                headers=preflight_headers(browser_origin),
            )

        assert response.headers.get("access-control-allow-origin") == browser_origin
    finally:
        engine.dispose()


def test_cors_preflight_does_not_allow_attacker_origin() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite://",
        web_origin="https://tutor.example.com",
    )

    app, engine = make_test_app(settings)
    try:
        with TestClient(app) as client:
            response = client.options(
                "/api/v1/health",
                headers=preflight_headers("https://attacker.example.com"),
            )

        assert "access-control-allow-origin" not in response.headers
    finally:
        engine.dispose()
