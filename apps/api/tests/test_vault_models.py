from collections.abc import Generator

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault.models import VaultFile


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    active_session = factory()
    try:
        yield active_session
    finally:
        active_session.close()
        engine.dispose()


@pytest.fixture
def knowledge_base(session: Session) -> KnowledgeBase:
    user = User(email="vault@example.com", username="vault-user", password_hash="hash")
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Vault Space")
    session.add(space)
    session.flush()
    model = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name="Vault KB",
    )
    session.add(model)
    session.flush()
    return model


def test_vault_file_path_is_unique_per_knowledge_base(
    session: Session, knowledge_base: KnowledgeBase
) -> None:
    first = VaultFile(
        knowledge_base_id=knowledge_base.id,
        space_id=knowledge_base.space_id,
        relative_path="notes/a.md",
        file_kind="markdown",
        content_hash="0" * 64,
    )
    second = VaultFile(
        knowledge_base_id=knowledge_base.id,
        space_id=knowledge_base.space_id,
        relative_path="notes/a.md",
        file_kind="markdown",
        content_hash="1" * 64,
    )
    session.add_all([first, second])

    with pytest.raises(IntegrityError):
        session.flush()


def test_vault_file_path_constraint_is_postgresql_compatible() -> None:
    ddl = str(CreateTable(VaultFile.__table__).compile(dialect=postgresql.dialect()))

    assert "CONSTRAINT ck_vault_file_path_posix" in ddl
    assert "instr(" not in ddl.lower()
    assert "ESCAPE '!'" in ddl
