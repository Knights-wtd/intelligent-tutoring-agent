import pytest

from tutor_api.core.config import Settings


@pytest.mark.parametrize(
    "web_origin",
    [
        pytest.param("*", id="wildcard"),
        pytest.param("ftp://example.com", id="non-http-scheme"),
        pytest.param("https://user:password@example.com", id="userinfo"),
        pytest.param("https://example.com/path", id="path"),
        pytest.param("https://example.com?debug=true", id="query"),
        pytest.param("https://example.com#fragment", id="fragment"),
    ],
)
def test_settings_rejects_unsafe_web_origins(web_origin: str) -> None:
    with pytest.raises(
        ValueError,
        match=r"WEB_ORIGIN must be a single absolute HTTP\(S\) origin",
    ):
        Settings(web_origin=web_origin)


def test_settings_reject_non_local_default_object_secret() -> None:
    settings = Settings(
        app_env="production",
        object_storage_secret_key="replace-for-non-local-use",
    )
    errors = settings.production_errors()
    assert "OBJECT_STORAGE_SECRET_KEY must be replaced" in errors


def test_settings_accept_local_defaults_in_development() -> None:
    settings = Settings(app_env="development")
    assert settings.production_errors() == []


def test_settings_accepts_http_origin_in_test() -> None:
    settings = Settings(app_env="test", web_origin="http://test.example.com")
    assert settings.production_errors() == []


def test_settings_repr_masks_object_storage_secret() -> None:
    secret = "never-log-this-object-storage-secret"
    settings = Settings(object_storage_secret_key=secret)

    assert secret not in repr(settings)
