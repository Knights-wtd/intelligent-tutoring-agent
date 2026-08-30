import sqlite3
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def create_engine_from_url(database_url: str, *, app_env: str) -> Engine:
    if app_env != "test" and not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL must use PostgreSQL outside test mode")
    if app_env == "test" and database_url.startswith("sqlite://"):
        engine = create_engine(
            database_url,
            connect_args={"autocommit": False, "check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(connection: sqlite3.Connection, _: object) -> None:
            autocommit = connection.autocommit
            connection.autocommit = True
            try:
                connection.execute("PRAGMA foreign_keys=ON")
            finally:
                connection.autocommit = autocommit

        return engine
    return create_engine(database_url, pool_pre_ping=True)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
