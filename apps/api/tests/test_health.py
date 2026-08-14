import pytest
from fastapi.testclient import TestClient

from tutor_api.core.config import Settings
from tutor_api.main import create_app


def preflight_headers(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
    }


def test_health_returns_public_status_only() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "textbook-tutor-api"}
    assert "database_url" not in response.text


def test_create_app_rejects_invalid_production_settings() -> None:
    settings = Settings(app_env="production")

    with pytest.raises(RuntimeError) as exc_info:
        create_app(settings)

    message = str(exc_info.value)
    assert "OBJECT_STORAGE_SECRET_KEY must be replaced" in message
    assert "WEB_ORIGIN must use HTTPS" in message


def test_cors_preflight_allows_exact_configured_origin() -> None:
    settings = Settings(web_origin="https://tutor.example.com")

    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/api/v1/health",
            headers=preflight_headers(settings.web_origin),
        )

    assert response.headers["access-control-allow-origin"] == settings.web_origin


def test_cors_preflight_does_not_allow_attacker_origin() -> None:
    settings = Settings(web_origin="https://tutor.example.com")

    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/api/v1/health",
            headers=preflight_headers("https://attacker.example.com"),
        )

    assert "access-control-allow-origin" not in response.headers
