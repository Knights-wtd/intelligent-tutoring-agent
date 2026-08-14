import pytest

from tutor_api.core.database import create_engine_from_url


def test_create_engine_rejects_sqlite_outside_test_mode() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        create_engine_from_url("sqlite:///local.db", app_env="development")
