from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_engine_from_url(database_url: str, *, app_env: str) -> Engine:
    if app_env != "test" and not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL must use PostgreSQL outside test mode")
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
