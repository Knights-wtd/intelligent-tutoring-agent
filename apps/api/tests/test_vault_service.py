from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from tutor_api.agent import models as agent_models  # noqa: F401
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import KnowledgeBase, MarkdownNote, MarkdownRevision
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault.models import VaultChangeEntry
from tutor_api.vault.service import VaultService
from tutor_api.vault.storage import VaultConflictError


def setup_db():
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def graph(db):
    user = User(email="vault-service@example.com", username="vault-service", password_hash="h")
    db.add(user)
    db.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Vault")
    db.add(space)
    db.flush()
    kb = KnowledgeBase(
        space_id=space.id, owner_user_id=user.id, created_by_user_id=user.id, name="Vault"
    )
    db.add(kb)
    db.flush()
    return space, kb


def test_create_update_move_delete_preserves_stable_id(tmp_path: Path) -> None:
    engine, factory = setup_db()
    with factory() as db:
        space, kb = graph(db)
        service = VaultService(db, tmp_path, space_id=space.id, knowledge_base_id=kb.id)
        created = service.create("a.md", "alpha")
        updated = service.update("a.md", "beta", expected_hash=created.after_hash)
        moved = service.move("a.md", "folder/b.md", expected_hash=updated.after_hash)
        deleted = service.delete("folder/b.md", expected_hash=moved.after_hash)
        assert {
            created.vault_file_id,
            updated.vault_file_id,
            moved.vault_file_id,
            deleted.vault_file_id,
        } == {created.vault_file_id}
        assert service.get_file(created.vault_file_id).is_tombstoned is True
        assert len(db.query(VaultChangeEntry).all()) == 4
    Base.metadata.drop_all(engine)


def test_expected_hash_conflict_preserves_file(tmp_path: Path) -> None:
    engine, factory = setup_db()
    with factory() as db:
        space, kb = graph(db)
        service = VaultService(db, tmp_path, space_id=space.id, knowledge_base_id=kb.id)
        service.create("a.md", "alpha")
        with pytest.raises(VaultConflictError, match="vault_hash_conflict"):
            service.update("a.md", "bad", expected_hash="0" * 64)
        assert service.read("a.md")[1] == b"alpha"
    Base.metadata.drop_all(engine)


def test_reconcile_prefers_vault_and_preserves_database_revision(tmp_path: Path) -> None:
    engine, factory = setup_db()
    with factory() as db:
        space, kb = graph(db)
        service = VaultService(
            db,
            tmp_path,
            space_id=space.id,
            knowledge_base_id=kb.id,
            actor_user_id=kb.created_by_user_id,
        )
        created = service.create("lesson.md", "database version")
        note = MarkdownNote(
            space_id=space.id,
            knowledge_base_id=kb.id,
            vault_file_id=created.vault_file_id,
            vault_relative_path="lesson.md",
            content_hash=created.content_hash,
            sync_state="synced",
            title="Lesson",
            normalized_title="lesson",
            created_by_user_id=kb.created_by_user_id,
        )
        db.add(note)
        db.flush()

        service.external_write("lesson.md", "vault version")
        result = service.reconcile(note.id, database_markdown="database version")

        assert result.markdown == "vault version"
        assert result.conflict_revision.markdown == "database version"
        assert result.conflict_revision.change_source == "conflict_backup"
        assert result.vault_revision.markdown == "vault version"
        revisions = list(
            db.scalars(
                select(MarkdownRevision)
                .where(MarkdownRevision.note_id == note.id)
                .order_by(MarkdownRevision.revision_number)
            )
        )
        assert [revision.revision_number for revision in revisions] == [1, 2]
        assert note.content_hash == service.get_file(created.vault_file_id).content_hash
    Base.metadata.drop_all(engine)
