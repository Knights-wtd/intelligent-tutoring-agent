from fastapi.testclient import TestClient

from tutor_api.main import create_app


def test_health_returns_public_status_only() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "textbook-tutor-api"}
    assert "database_url" not in response.text
