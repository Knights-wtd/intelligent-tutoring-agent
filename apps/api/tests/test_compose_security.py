import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _locked_requirements() -> dict[str, Requirement]:
    lock_file = REPOSITORY_ROOT / "apps" / "api" / "requirements.lock"
    requirements = {}
    for line in lock_file.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#"):
            requirement = Requirement(candidate)
            requirements[canonicalize_name(requirement.name)] = requirement
    return requirements


def _environment_example() -> dict[str, str]:
    return {
        key: value
        for line in (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
        for key, value in [line.split("=", maxsplit=1)]
    }


def _service_block(compose: str, service: str, next_service: str) -> str:
    return compose.split(f"  {service}:\n", maxsplit=1)[1].split(
        f"  {next_service}:\n", maxsplit=1
    )[0]


def test_example_uses_distinct_minio_admin_and_application_identities() -> None:
    environment = _environment_example()

    assert environment["MINIO_ROOT_USER"] != environment["OBJECT_STORAGE_ACCESS_KEY"]
    assert environment["MINIO_ROOT_PASSWORD"] != environment["OBJECT_STORAGE_SECRET_KEY"]
    assert "admin" in environment["MINIO_ROOT_USER"]
    assert "app" in environment["OBJECT_STORAGE_ACCESS_KEY"]
    assert "minio-admin-password" in environment["MINIO_ROOT_PASSWORD"]
    assert "object-app-secret" in environment["OBJECT_STORAGE_SECRET_KEY"]


def test_api_receives_only_scoped_object_storage_credentials() -> None:
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    api = _service_block(compose, "api", "web")

    assert "OBJECT_STORAGE_ACCESS_KEY:" in api
    assert "OBJECT_STORAGE_SECRET_KEY:" in api
    assert "MINIO_ROOT_" not in api


def test_api_receives_non_secret_session_settings_from_the_environment() -> None:
    environment = _environment_example()
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    api = _service_block(compose, "api", "web")

    assert environment["SESSION_COOKIE_NAME"] == "session"
    assert environment["SESSION_TTL_SECONDS"] == "604800"
    assert "SESSION_COOKIE_NAME:" in api
    assert "SESSION_TTL_SECONDS:" in api


def test_api_receives_only_non_secret_provider_runtime_configuration() -> None:
    environment = _environment_example()
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    api = _service_block(compose, "api", "web")
    web = _service_block(compose, "web", "volumes")

    assert '"id":"example-chat-model"' in environment["PROVIDER_PROFILES_JSON"]
    assert environment["PLATFORM_ADMIN_EMAILS"] == "admin@example.com"
    assert environment["OPENAI_API_KEY"] == ""
    assert environment["ANTHROPIC_API_KEY"] == ""
    assert "PROVIDER_PROFILES_JSON:" in api
    assert "PLATFORM_ADMIN_EMAILS:" in api
    # FARO_API_KEY is the single sanctioned server-side provider credential (tutor).
    # Generic OpenAI/Anthropic keys must never reach compose, and no credential may
    # leak into the web service.
    assert "OPENAI_API_KEY" not in api
    assert "ANTHROPIC_API_KEY" not in api
    assert "FARO_API_KEY:" in api
    assert "PROVIDER_BASE_URL" not in api
    assert "PROVIDER_PROFILES_JSON" not in web
    assert "PLATFORM_ADMIN_EMAILS" not in web
    assert "FARO_API_KEY" not in web


def test_faro_uses_the_restricted_connect_proxy_without_a_dns_override() -> None:
    environment = _environment_example()
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    api = _service_block(compose, "api", "worker")
    worker = _service_block(compose, "worker", "web")

    assert environment["FARO_PROXY_URL"] == ""
    for service in (api, worker):
        assert "FARO_PROXY_URL:" in service
        assert "extra_hosts:" not in service


def test_web_host_port_can_be_changed_without_changing_the_container_port() -> None:
    environment = _environment_example()
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    web = _service_block(compose, "web", "volumes")

    assert environment["WEB_PORT"] == "3000"
    assert '"127.0.0.1:${WEB_PORT:-3000}:3000"' in web


def test_citation_hmac_secret_reaches_api_and_worker_but_never_web() -> None:
    environment = _environment_example()
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    api = _service_block(compose, "api", "web")
    worker = _service_block(compose, "worker", "web")
    web = _service_block(compose, "web", "volumes")

    assert environment["CITATION_HMAC_SECRET"] == "replace-with-long-random-citation-hmac-secret"
    # api/worker environments stay identical by convention; the browser-facing web
    # service must never see the signing key.
    assert "CITATION_HMAC_SECRET:" in api
    assert "CITATION_HMAC_SECRET:" in worker
    assert "CITATION_HMAC_SECRET" not in web


def test_api_image_includes_and_applies_database_migrations_before_starting() -> None:
    dockerfile = (REPOSITORY_ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY apps/api/migrations ./migrations" in dockerfile
    assert "COPY apps/api/alembic.ini ./alembic.ini" in dockerfile
    assert "python -m alembic -c alembic.ini upgrade head" in dockerfile


def test_multipart_runtime_dependency_is_pinned_in_production_lock() -> None:
    pyproject = tomllib.loads(
        (REPOSITORY_ROOT / "apps" / "api" / "pyproject.toml").read_text(encoding="utf-8")
    )
    declared = {
        canonicalize_name(requirement.name): requirement
        for value in pyproject["project"]["dependencies"]
        for requirement in [Requirement(value)]
    }
    multipart = declared["python-multipart"]
    locked = _locked_requirements()["python-multipart"]

    locked_specifiers = list(locked.specifier)
    assert len(locked_specifiers) == 1
    assert locked_specifiers[0].operator == "=="
    assert locked_specifiers[0].version in multipart.specifier


def test_faro_http_client_is_pinned_in_production_lock() -> None:
    pyproject = tomllib.loads(
        (REPOSITORY_ROOT / "apps" / "api" / "pyproject.toml").read_text(encoding="utf-8")
    )
    declared = {
        canonicalize_name(requirement.name): requirement
        for value in pyproject["project"]["dependencies"]
        for requirement in [Requirement(value)]
    }
    httpx = declared["httpx"]
    locked = _locked_requirements()["httpx"]

    locked_specifiers = list(locked.specifier)
    assert len(locked_specifiers) == 1
    assert locked_specifiers[0].operator == "=="
    assert locked_specifiers[0].version in httpx.specifier


def test_migrations_use_the_runtime_database_url_when_it_is_provided() -> None:
    migration_environment = (REPOSITORY_ROOT / "apps" / "api" / "migrations" / "env.py").read_text(
        encoding="utf-8"
    )

    assert 'os.environ.get("DATABASE_URL")' in migration_environment
    assert 'config.set_main_option("sqlalchemy.url", database_url)' in migration_environment


def test_minio_initializer_provisions_bucket_scoped_application_policy() -> None:
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    initializer = _service_block(compose, "minio-init", "api")

    for variable in (
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
        "OBJECT_STORAGE_BUCKET",
    ):
        assert f"{variable}:" in initializer

    assert '"$${MINIO_ROOT_USER}" "$${MINIO_ROOT_PASSWORD}"' in initializer
    assert '"$${OBJECT_STORAGE_ACCESS_KEY}" "$${OBJECT_STORAGE_SECRET_KEY}"' in initializer
    assert "mc admin policy create" in initializer
    assert "mc admin user info --json" in initializer
    assert "mc admin user add" in initializer
    assert "mc admin policy attach" in initializer
    assert "mc admin user rm" not in initializer
    assert "unexpected policies" in initializer
    assert '"arn:aws:s3:::$${OBJECT_STORAGE_BUCKET}"' in initializer
    assert '"arn:aws:s3:::$${OBJECT_STORAGE_BUCKET}/*"' in initializer
    for action in (
        "s3:GetBucketLocation",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts",
    ):
        assert f'"{action}"' in initializer

    assert '"arn:aws:s3:::*"' not in initializer
