from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


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
