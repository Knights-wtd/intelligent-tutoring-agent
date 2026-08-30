from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tutor_api.core.database import create_engine_from_url


def test_create_engine_rejects_sqlite_outside_test_mode() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        create_engine_from_url("sqlite:///local.db", app_env="development")


@pytest.mark.parametrize("storage", ["memory", "file"])
def test_sqlite_test_engine_binds_savepoint_to_outer_transaction(
    storage: str, tmp_path: Path
) -> None:
    database_url = "sqlite://" if storage == "memory" else f"sqlite:///{tmp_path / 'database.db'}"
    engine = create_engine_from_url(database_url, app_env="test")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE record (id INTEGER PRIMARY KEY, value TEXT)"))
            connection.execute(text("INSERT INTO record (value) VALUES ('before')"))

        with Session(engine) as session:
            outer = session.begin()
            nested = session.begin_nested()
            session.execute(text("UPDATE record SET value = 'after' WHERE id = 1"))
            nested.commit()
            outer.rollback()

        with Session(engine) as verify_session:
            assert verify_session.scalar(text("SELECT value FROM record WHERE id = 1")) == "before"
    finally:
        engine.dispose()


def test_sqlite_test_engine_uses_nonlegacy_transactions_and_foreign_keys() -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    try:
        with engine.connect() as connection:
            driver_connection = connection.connection.driver_connection
            assert driver_connection.autocommit is False
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        engine.dispose()
