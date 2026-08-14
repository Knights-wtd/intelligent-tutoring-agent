import pytest

from tutor_api.core.config import Settings

SAFE_PRODUCTION_SETTINGS = {
    "app_env": "production",
    "web_origin": "https://app.example.com",
    "database_url": "postgresql+psycopg://app:strong-password@db.example.com:5432/textbook",
    "redis_url": "rediss://app:strong-password@cache.example.com:6379/0",
    "object_storage_endpoint": "https://objects.example.com",
    "object_storage_access_key": "textbook-production-app",
    "object_storage_secret_key": "long-random-production-object-secret",
}


def test_settings_parse_non_secret_provider_profiles() -> None:
    settings = Settings(
        provider_profiles_json=(
            '[{"id":"openai-gpt-4o-mini","provider":"openai","model":"gpt-4o-mini",'
            '"display_name":"OpenAI GPT-4o mini","supports_usage":true,'
            '"enabled_by_default":true}]'
        )
    )

    assert settings.provider_profiles[0].id == "openai-gpt-4o-mini"
    assert settings.provider_profiles[0].provider == "openai"
    assert settings.provider_profiles[0].model == "gpt-4o-mini"
    assert settings.provider_profiles[0].display_name == "OpenAI GPT-4o mini"
    assert settings.provider_profiles[0].supports_usage is True
    assert settings.provider_profiles[0].enabled_by_default is True


@pytest.mark.parametrize(
    "provider_profiles_json",
    [
        pytest.param("not-json", id="invalid-json"),
        pytest.param(
            '[{"id":"duplicate","provider":"openai","model":"gpt-4o-mini",'
            '"display_name":"First","supports_usage":true,"enabled_by_default":true},'
            '{"id":"duplicate","provider":"anthropic","model":"claude-haiku",'
            '"display_name":"Second","supports_usage":false,"enabled_by_default":false}]',
            id="duplicate-ids",
        ),
        pytest.param(
            '[{"id":" ","provider":"openai","model":"gpt-4o-mini",'
            '"display_name":"GPT-4o mini","supports_usage":true,'
            '"enabled_by_default":true}]',
            id="blank-id",
        ),
    ],
)
def test_settings_reject_invalid_provider_profiles(
    provider_profiles_json: str,
) -> None:
    with pytest.raises(ValueError, match="PROVIDER_PROFILES_JSON|provider profile fields"):
        Settings(provider_profiles_json=provider_profiles_json)


@pytest.mark.parametrize(
    "platform_admin_emails",
    [
        " Admin@Example.com, admin@example.com , owner@example.com ",
        (" Admin@Example.com ", "admin@example.com", " owner@example.com "),
        [" Admin@Example.com ", "admin@example.com", " owner@example.com "],
    ],
)
def test_settings_normalizes_platform_admin_emails(platform_admin_emails: object) -> None:
    settings = Settings(platform_admin_emails=platform_admin_emails)

    assert settings.platform_admin_emails == ("admin@example.com", "owner@example.com")


@pytest.mark.parametrize(
    "platform_admin_emails",
    ["not-an-email", "admin@example.com, ", ("not-an-email",), ["admin@example.com", ""]],
)
def test_settings_reject_invalid_platform_admin_emails(platform_admin_emails: object) -> None:
    with pytest.raises(ValueError, match="PLATFORM_ADMIN_EMAILS"):
        Settings(platform_admin_emails=platform_admin_emails)


def test_settings_hides_provider_profile_input_from_validation_errors() -> None:
    sentinel_secret = "never-log-provider-profile-secret"

    with pytest.raises(ValueError) as error:
        Settings(
            provider_profiles_json=(
                '[{"id":"","provider":"openai","model":"example-chat-model",'
                f'"display_name":"Example","api_key":"{sentinel_secret}",'
                '"supports_usage":true,"enabled_by_default":true}]'
            )
        )

    assert sentinel_secret not in str(error.value)


def test_settings_repr_contains_no_provider_api_key_or_base_url() -> None:
    settings = Settings(
        provider_profiles_json=(
            '[{"id":"openai-gpt-4o-mini","provider":"openai","model":"gpt-4o-mini",'
            '"display_name":"OpenAI GPT-4o mini","supports_usage":true,'
            '"enabled_by_default":true}]'
        )
    )

    assert "api_key" not in repr(settings).casefold()
    assert "base_url" not in repr(settings).casefold()


@pytest.mark.parametrize(
    "web_origin",
    [
        pytest.param("*", id="wildcard"),
        pytest.param("ftp://example.com", id="non-http-scheme"),
        pytest.param("https://user:password@example.com", id="userinfo"),
        pytest.param("https://example.com/path", id="path"),
        pytest.param("https://example.com?debug=true", id="query"),
        pytest.param("https://example.com#fragment", id="fragment"),
        pytest.param("https://%zz", id="malformed-percent-escape"),
        pytest.param("https://example\\evil.com", id="backslash"),
        pytest.param("https://*.example.com", id="wildcard-subdomain"),
        pytest.param("https://example.*", id="wildcard-top-level-domain"),
    ],
)
def test_settings_rejects_unsafe_web_origins(web_origin: str) -> None:
    with pytest.raises(
        ValueError,
        match=r"WEB_ORIGIN must be a single absolute HTTP\(S\) origin",
    ):
        Settings(web_origin=web_origin)


@pytest.mark.parametrize(
    ("web_origin", "expected_origin"),
    [
        ("http://localhost:3000", "http://localhost:3000"),
        ("https://example.com", "https://example.com"),
        ("HTTPS://EXAMPLE.COM", "https://example.com"),
        ("https://example.com:443", "https://example.com"),
        ("http://example.com:80", "http://example.com"),
        ("https://example.com:8443", "https://example.com:8443"),
    ],
)
def test_settings_canonicalizes_web_origins(web_origin: str, expected_origin: str) -> None:
    settings = Settings(web_origin=web_origin)

    assert settings.web_origin == expected_origin


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


def test_settings_accepts_production_safe_values() -> None:
    settings = Settings(**SAFE_PRODUCTION_SETTINGS)

    assert settings.production_errors() == []


@pytest.mark.parametrize(
    "database_url",
    [
        pytest.param("sqlite:///./textbook-local.db", id="exact-development-default"),
        pytest.param("sqlite:////var/lib/textbook.db", id="sqlite"),
        pytest.param(
            "postgresql+psycopg://textbook:secret@postgres:5432/textbook",
            id="compose-development-service",
        ),
        pytest.param(
            "postgresql+psycopg://textbook:secret@127.0.0.1:5432/textbook",
            id="loopback",
        ),
        pytest.param("not-a-database-url", id="malformed"),
    ],
)
def test_production_rejects_development_database_urls(database_url: str) -> None:
    settings = Settings(**(SAFE_PRODUCTION_SETTINGS | {"database_url": database_url}))

    assert "DATABASE_URL must use a non-local PostgreSQL database" in settings.production_errors()


@pytest.mark.parametrize(
    "redis_url",
    [
        pytest.param("redis://localhost:6379/0", id="exact-development-default"),
        pytest.param("rediss://cache.example.com:6379/0", id="unauthenticated"),
        pytest.param("redis://:secret@127.0.0.1:6379/0", id="ipv4-loopback"),
        pytest.param("redis://:secret@[::1]:6379/0", id="ipv6-loopback"),
        pytest.param("redis://:secret@localhost:6379/0", id="localhost"),
        pytest.param("redis://:secret@redis:6379/0", id="development-service"),
        pytest.param("redis://:secret@cache.example.com:not-a-port/0", id="malformed"),
    ],
)
def test_production_rejects_development_redis_urls(redis_url: str) -> None:
    settings = Settings(**(SAFE_PRODUCTION_SETTINGS | {"redis_url": redis_url}))

    assert "REDIS_URL must use authenticated, non-local Redis" in settings.production_errors()


@pytest.mark.parametrize(
    "object_storage_endpoint",
    [
        pytest.param("http://localhost:9000", id="exact-development-default"),
        pytest.param("http://minio:9000", id="compose-development-service"),
        pytest.param("http://127.0.0.1:9000", id="ipv4-loopback"),
        pytest.param("http://[::1]:9000", id="ipv6-loopback"),
        pytest.param("objects.example.com", id="malformed"),
        pytest.param("ftp://objects.example.com", id="unsupported-scheme"),
    ],
)
def test_production_rejects_development_object_endpoints(
    object_storage_endpoint: str,
) -> None:
    settings = Settings(
        **(
            SAFE_PRODUCTION_SETTINGS
            | {"object_storage_endpoint": object_storage_endpoint}
        )
    )

    assert (
        "OBJECT_STORAGE_ENDPOINT must use a non-local HTTP(S) endpoint"
        in settings.production_errors()
    )


@pytest.mark.parametrize(
    "object_storage_access_key",
    ["textbook-local", "textbook-storage-app-local"],
)
def test_production_rejects_development_object_access_keys(
    object_storage_access_key: str,
) -> None:
    settings = Settings(
        **(
            SAFE_PRODUCTION_SETTINGS
            | {"object_storage_access_key": object_storage_access_key}
        )
    )

    assert "OBJECT_STORAGE_ACCESS_KEY must be replaced" in settings.production_errors()


@pytest.mark.parametrize(
    "object_storage_access_key",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace-only"),
        pytest.param("ab", id="too-short"),
        pytest.param(" abc", id="leading-whitespace"),
        pytest.param("abc ", id="trailing-whitespace"),
    ],
)
def test_production_rejects_invalid_object_access_key_lengths(
    object_storage_access_key: str,
) -> None:
    settings = Settings(
        **(
            SAFE_PRODUCTION_SETTINGS
            | {"object_storage_access_key": object_storage_access_key}
        )
    )

    assert (
        "OBJECT_STORAGE_ACCESS_KEY must be trimmed and at least 3 characters"
        in settings.production_errors()
    )


@pytest.mark.parametrize(
    "object_storage_secret_key",
    [
        "replace-for-non-local-use",
        "replace-with-long-random-object-app-secret",
        "development-secret",
    ],
)
def test_production_rejects_placeholder_object_secrets(
    object_storage_secret_key: str,
) -> None:
    settings = Settings(
        **(
            SAFE_PRODUCTION_SETTINGS
            | {"object_storage_secret_key": object_storage_secret_key}
        )
    )

    errors = settings.production_errors()
    assert "OBJECT_STORAGE_SECRET_KEY must be replaced" in errors
    assert object_storage_secret_key not in repr(settings)
    assert all(object_storage_secret_key not in error for error in errors)


@pytest.mark.parametrize(
    "object_storage_secret_key",
    [
        pytest.param("", id="empty"),
        pytest.param("        ", id="whitespace-only"),
        pytest.param("1234567", id="too-short"),
        pytest.param(" 12345678", id="leading-whitespace"),
        pytest.param("12345678 ", id="trailing-whitespace"),
    ],
)
def test_production_rejects_invalid_object_secret_lengths(
    object_storage_secret_key: str,
) -> None:
    settings = Settings(
        **(
            SAFE_PRODUCTION_SETTINGS
            | {"object_storage_secret_key": object_storage_secret_key}
        )
    )

    errors = settings.production_errors()
    assert "OBJECT_STORAGE_SECRET_KEY must be trimmed and at least 8 characters" in errors
    if object_storage_secret_key:
        assert object_storage_secret_key not in repr(settings)
        assert all(object_storage_secret_key not in error for error in errors)


def test_production_accepts_minimum_length_object_credentials() -> None:
    settings = Settings(
        **(
            SAFE_PRODUCTION_SETTINGS
            | {
                "object_storage_access_key": "abc",
                "object_storage_secret_key": "12345678",
            }
        )
    )

    assert settings.production_errors() == []


def test_production_rejects_http_web_origin_one_fallback_at_a_time() -> None:
    settings = Settings(
        **(SAFE_PRODUCTION_SETTINGS | {"web_origin": "http://app.example.com"})
    )

    assert settings.production_errors() == ["WEB_ORIGIN must use HTTPS"]


def test_settings_do_not_expose_url_credentials_in_repr_or_errors() -> None:
    database_password = "never-log-database-password"
    redis_password = "never-log-redis-password"
    object_password = "never-log-object-password"
    settings = Settings(
        **(
            SAFE_PRODUCTION_SETTINGS
            | {
                "database_url": (
                    f"postgresql+psycopg://app:{database_password}@db.example.com/textbook"
                ),
                "redis_url": f"redis://app:{redis_password}@localhost:6379/0",
                "object_storage_endpoint": (
                    f"https://app:{object_password}@objects.example.com"
                ),
            }
        )
    )

    errors = settings.production_errors()
    rendered_settings = repr(settings)
    assert redis_password not in rendered_settings
    assert database_password not in rendered_settings
    assert object_password not in rendered_settings
    assert all(redis_password not in error for error in errors)
    assert all(database_password not in error for error in errors)
    assert all(object_password not in error for error in errors)


@pytest.mark.parametrize(
    "session_cookie_name",
    [
        pytest.param("", id="missing"),
        pytest.param("contains space", id="space"),
        pytest.param("session;unsafe", id="separator"),
    ],
)
def test_settings_reject_invalid_session_cookie_names(session_cookie_name: str) -> None:
    with pytest.raises(ValueError, match="SESSION_COOKIE_NAME"):
        Settings(
            **(
                SAFE_PRODUCTION_SETTINGS
                | {"session_cookie_name": session_cookie_name}
            )
        )


@pytest.mark.parametrize("session_ttl_seconds", [3599, 2_592_001])
def test_settings_reject_session_ttl_outside_supported_range(
    session_ttl_seconds: int,
) -> None:
    with pytest.raises(ValueError, match="SESSION_TTL_SECONDS"):
        Settings(
            **(
                SAFE_PRODUCTION_SETTINGS
                | {"session_ttl_seconds": session_ttl_seconds}
            )
        )
