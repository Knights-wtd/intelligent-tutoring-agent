from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.agent import models as agent_models  # noqa: F401
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import KnowledgeBase, MarkdownNote, MarkdownRevision
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault.models import (
    VaultChangeEntry,
    VaultChangeOperation,
    VaultChangeSet,
    VaultFile,
    VaultSyncCursor,
)
from tutor_api.vault.service import VaultService
from tutor_api.vault.storage import VaultPathError
from tutor_api.vault.sync import VaultSyncService


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as active:
        yield active
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def persistent_sessions(tmp_path: Path) -> Generator[sessionmaker[Session], None, None]:
    database_path = (tmp_path / "vault-sync.sqlite3").as_posix()
    engine = create_engine_from_url(f"sqlite:///{database_path}", app_env="test")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def graph(session: Session, suffix: str = "sync") -> tuple[User, Space, KnowledgeBase]:
    user = User(
        email=f"{suffix}@example.com",
        username=f"user-{suffix}",
        password_hash="h",
    )
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name=suffix)
    session.add(space)
    session.flush()
    kb = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name=f"KB {suffix}",
    )
    session.add(kb)
    session.flush()
    return user, space, kb


def sync_service(
    session: Session,
    root: Path,
    user: User,
    space: Space,
    kb: KnowledgeBase,
    *,
    debounce: timedelta = timedelta(milliseconds=250),
) -> VaultSyncService:
    return VaultSyncService(
        session,
        root,
        space_id=space.id,
        knowledge_base_id=kb.id,
        actor_user_id=user.id,
        debounce_window=debounce,
    )


def scoped_root(root: Path, space: Space, kb: KnowledgeBase) -> Path:
    value = root / "spaces" / str(space.id) / str(kb.id)
    value.mkdir(parents=True, exist_ok=True)
    return value


def replace_directory_with_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            pytest.skip(f"junction creation unavailable: {completed.stderr.strip()}")
        return
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"directory symlink creation unavailable: {error}")


def replace_file_with_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"file symlink creation unavailable: {error}")


def test_external_file_is_auto_enrolled_once_and_cursor_tracks_backlog(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session, "enroll")
    root = scoped_root(tmp_path, space, kb)
    (root / "new-concept.md").write_text("# New concept", encoding="utf-8")
    service = sync_service(session, tmp_path, user, space, kb)

    first = service.scan()
    second = service.scan()

    assert first.change_count == 1
    assert second.change_count == 0
    assert (
        session.scalar(
            select(func.count(VaultFile.id)).where(
                VaultFile.knowledge_base_id == kb.id,
                VaultFile.relative_path == "new-concept.md",
            )
        )
        == 1
    )
    assert (
        session.scalar(
            select(func.count(VaultChangeSet.id)).where(VaultChangeSet.knowledge_base_id == kb.id)
        )
        == 1
    )
    cursor = session.scalar(
        select(VaultSyncCursor).where(VaultSyncCursor.knowledge_base_id == kb.id)
    )
    assert cursor is not None
    assert cursor.pending_count == 1
    assert cursor.requires_full_scan is False
    assert cursor.last_success_at is not None


def test_runtime_echo_survives_committed_restart_without_recovery_scan(
    persistent_sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    with persistent_sessions() as first_session:
        user, space, kb = graph(first_session, "echo")
        writer = VaultService(
            first_session,
            tmp_path,
            space_id=space.id,
            knowledge_base_id=kb.id,
            actor_user_id=user.id,
        )
        created = writer.create("echo.md", "# Echo")
        service = sync_service(first_session, tmp_path, user, space, kb)
        service.scan()
        user_id, space_id, knowledge_base_id = user.id, space.id, kb.id
        after_hash = created.after_hash
        before = first_session.scalar(select(func.count(VaultChangeSet.id)))
        first_session.commit()

    observed_at = datetime(2026, 8, 29, 0, 30, tzinfo=UTC)
    with persistent_sessions() as watcher_session:
        watcher = VaultSyncService(
            watcher_session,
            tmp_path,
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            actor_user_id=user_id,
        )
        assert (
            watcher.observe("echo.md", after_hash, event_id="runtime:1", observed_at=observed_at)
            is False
        )
        watcher_session.commit()

    with persistent_sessions() as restarted_session:
        restarted = VaultSyncService(
            restarted_session,
            tmp_path,
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            actor_user_id=user_id,
        )
        resumed = restarted.resume(now=observed_at + timedelta(seconds=1))
        cursor = restarted_session.scalar(
            select(VaultSyncCursor).where(VaultSyncCursor.knowledge_base_id == knowledge_base_id)
        )

        assert resumed.change_count == 0
        assert resumed.deferred is False
        assert restarted_session.scalar(select(func.count(VaultChangeSet.id))) == before
        assert cursor is not None
        assert cursor.requires_full_scan is False
        assert cursor.watcher_cursor == "runtime:1"


def test_event_storm_is_debounced_into_one_full_scan_change_set(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session, "storm")
    root = scoped_root(tmp_path, space, kb)
    (root / "a.md").write_text("A", encoding="utf-8")
    (root / "b.md").write_text("B", encoding="utf-8")
    service = sync_service(session, tmp_path, user, space, kb, debounce=timedelta(seconds=1))
    start = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)

    assert service.observe("a.md", None, event_id="os:1", observed_at=start) is True
    assert (
        service.observe(
            "a.md", None, event_id="os:2", observed_at=start + timedelta(milliseconds=100)
        )
        is True
    )
    assert (
        service.observe(
            "b.md", None, event_id="os:3", observed_at=start + timedelta(milliseconds=200)
        )
        is True
    )
    assert service.flush(now=start + timedelta(milliseconds=900)).deferred is True
    result = service.flush(now=start + timedelta(seconds=2))

    assert result.change_count == 2
    change_sets = session.scalars(select(VaultChangeSet)).all()
    assert len(change_sets) == 1
    entries = session.scalars(
        select(VaultChangeEntry).where(VaultChangeEntry.change_set_id == change_sets[0].id)
    ).all()
    assert {entry.after_path for entry in entries} == {"a.md", "b.md"}


def test_rename_and_move_preserve_file_identity_and_classify_operation(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session, "rename")
    root = scoped_root(tmp_path, space, kb)
    source = root / "chapter.md"
    source.write_text("same body", encoding="utf-8")
    service = sync_service(session, tmp_path, user, space, kb)
    service.scan()
    enrolled = session.scalar(select(VaultFile).where(VaultFile.knowledge_base_id == kb.id))
    assert enrolled is not None
    original_id = enrolled.id

    source.rename(root / "renamed.md")
    renamed = service.scan()
    (root / "unit").mkdir()
    (root / "renamed.md").rename(root / "unit" / "renamed.md")
    moved = service.scan()

    session.expire_all()
    current = session.get(VaultFile, original_id)
    assert current is not None and current.relative_path == "unit/renamed.md"
    rename_entry = session.scalar(
        select(VaultChangeEntry).where(VaultChangeEntry.change_set_id == renamed.change_set_id)
    )
    move_entry = session.scalar(
        select(VaultChangeEntry).where(VaultChangeEntry.change_set_id == moved.change_set_id)
    )
    assert rename_entry is not None and rename_entry.operation is VaultChangeOperation.RENAME
    assert move_entry is not None and move_entry.operation is VaultChangeOperation.MOVE


def test_edit_and_delete_create_revisioned_change_entries_and_tombstone(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session, "edit-delete")
    root = scoped_root(tmp_path, space, kb)
    path = root / "lesson.md"
    path.write_text("first", encoding="utf-8")
    service = sync_service(session, tmp_path, user, space, kb)
    service.scan()
    row = session.scalar(select(VaultFile).where(VaultFile.knowledge_base_id == kb.id))
    assert row is not None

    path.write_text("second", encoding="utf-8")
    edited = service.scan()
    path.unlink()
    deleted = service.scan()

    edit_entry = session.scalar(
        select(VaultChangeEntry).where(VaultChangeEntry.change_set_id == edited.change_set_id)
    )
    delete_entry = session.scalar(
        select(VaultChangeEntry).where(VaultChangeEntry.change_set_id == deleted.change_set_id)
    )
    session.refresh(row)
    assert edit_entry is not None and edit_entry.operation is VaultChangeOperation.UPDATE
    assert delete_entry is not None and delete_entry.operation is VaultChangeOperation.DELETE
    assert row.revision == 3
    assert row.is_tombstoned is True


def test_observed_event_is_committed_before_debounce_and_resumes_in_new_session(
    persistent_sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    observed_at = datetime(2026, 8, 29, 1, 0, tzinfo=UTC)
    with persistent_sessions() as first_session:
        user, space, kb = graph(first_session, "debounce-restart")
        root = scoped_root(tmp_path, space, kb)
        service = sync_service(
            first_session, tmp_path, user, space, kb, debounce=timedelta(minutes=5)
        )
        service.scan()
        first_session.commit()
        (root / "pending.md").write_text("found after restart", encoding="utf-8")

        assert (
            service.observe("pending.md", None, event_id="os:pending", observed_at=observed_at)
            is True
        )
        assert service.cursor.requires_full_scan is True
        user_id, space_id, knowledge_base_id = user.id, space.id, kb.id
        first_session.commit()

    with persistent_sessions() as restarted_session:
        restarted = VaultSyncService(
            restarted_session,
            tmp_path,
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            actor_user_id=user_id,
            debounce_window=timedelta(minutes=5),
        )
        result = restarted.resume(now=observed_at + timedelta(seconds=1))
        cursor = restarted.cursor

        assert result.deferred is False
        assert result.change_count == 1
        assert (
            restarted_session.scalar(
                select(func.count(VaultFile.id)).where(
                    VaultFile.knowledge_base_id == knowledge_base_id,
                    VaultFile.relative_path == "pending.md",
                )
            )
            == 1
        )
        assert cursor.requires_full_scan is False
        assert cursor.pending_count == 1
        assert cursor.last_error is None


def test_missed_event_full_scan_and_cursor_restart_recover_changes(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session, "restart")
    root = scoped_root(tmp_path, space, kb)
    service = sync_service(session, tmp_path, user, space, kb)
    service.scan()
    (root / "missed.md").write_text("found by full scan", encoding="utf-8")
    service.require_full_scan("watcher_overflow")
    session.flush()

    restarted = sync_service(session, tmp_path, user, space, kb)
    result = restarted.resume()

    assert result.change_count == 1
    assert (
        session.scalar(
            select(func.count(VaultFile.id)).where(VaultFile.relative_path == "missed.md")
        )
        == 1
    )
    cursor = session.scalar(
        select(VaultSyncCursor).where(VaultSyncCursor.knowledge_base_id == kb.id)
    )
    assert cursor is not None
    assert cursor.requires_full_scan is False
    assert cursor.last_error is None


def test_project_markdown_is_idempotent_and_delete_keeps_history(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session, "project")
    root = scoped_root(tmp_path, space, kb)
    path = root / "concept.md"
    path.write_text("# Concept\n\nBody", encoding="utf-8")
    service = sync_service(session, tmp_path, user, space, kb)
    created = service.scan()

    first = service.project(created.change_set_id)
    second = service.project(created.change_set_id)

    assert first.projected_count == 1
    assert second.projected_count == 0
    note = session.scalar(select(MarkdownNote).where(MarkdownNote.knowledge_base_id == kb.id))
    assert note is not None
    assert note.vault_relative_path == "concept.md"
    assert note.content_hash == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (
        session.scalar(
            select(func.count(MarkdownRevision.id)).where(MarkdownRevision.note_id == note.id)
        )
        == 1
    )

    path.unlink()
    deleted = service.scan()
    service.project(deleted.change_set_id)
    session.refresh(note)
    assert note.is_tombstoned is True
    assert (
        session.scalar(
            select(func.count(MarkdownRevision.id)).where(MarkdownRevision.note_id == note.id)
        )
        == 2
    )


@pytest.mark.parametrize("replace_ancestor", [False, True], ids=["file", "ancestor"])
def test_project_rejects_path_replaced_by_link_outside_scoped_root(
    session: Session, tmp_path: Path, *, replace_ancestor: bool
) -> None:
    user, space, kb = graph(session, f"project-link-{replace_ancestor}")
    root = scoped_root(tmp_path, space, kb)
    folder = root / "unit"
    folder.mkdir()
    source = folder / "concept.md"
    content = b"# Same trusted hash\n"
    source.write_bytes(content)
    service = sync_service(session, tmp_path, user, space, kb)
    created = service.scan()
    outside = tmp_path / "outside"
    outside.mkdir()

    if replace_ancestor:
        (outside / "concept.md").write_bytes(content)
        detached = root / "unit-detached"
        folder.rename(detached)
        replace_directory_with_link(folder, outside)
    else:
        outside_file = outside / "concept.md"
        outside_file.write_bytes(content)
        source.unlink()
        replace_file_with_symlink(source, outside_file)

    with pytest.raises(VaultPathError, match="vault_path_escape"):
        service.project(created.change_set_id)

    assert session.scalar(select(func.count(MarkdownRevision.id))) == 0


@pytest.mark.parametrize("redirected_component", ["root", "space"], ids=["root", "ancestor"])
def test_new_service_rejects_scoped_root_redirected_within_global_vault(
    session: Session, tmp_path: Path, redirected_component: str
) -> None:
    user, space, kb = graph(session, f"scope-redirect-{redirected_component}")
    root = scoped_root(tmp_path, space, kb)
    source = root / "concept.md"
    content = b"# Same trusted hash\n"
    source.write_bytes(content)
    scanner = sync_service(session, tmp_path, user, space, kb)
    created = scanner.scan()

    spaces_root = tmp_path / "spaces"
    if redirected_component == "root":
        detached = root.with_name(f"{root.name}-detached")
        root.rename(detached)
        redirected_root = spaces_root / "redirect-target" / str(kb.id)
        redirected_root.mkdir(parents=True)
        (redirected_root / "concept.md").write_bytes(content)
        replace_directory_with_link(root, redirected_root)
    else:
        space_root = root.parent
        detached = space_root.with_name(f"{space_root.name}-detached")
        space_root.rename(detached)
        redirected_space = spaces_root / "redirect-target"
        redirected_root = redirected_space / str(kb.id)
        redirected_root.mkdir(parents=True)
        (redirected_root / "concept.md").write_bytes(content)
        replace_directory_with_link(space_root, redirected_space)

    with pytest.raises(VaultPathError, match="vault_path_escape"):
        restarted = sync_service(session, tmp_path, user, space, kb)
        restarted.project(created.change_set_id)

    assert session.scalar(select(func.count(MarkdownRevision.id))) == 0
