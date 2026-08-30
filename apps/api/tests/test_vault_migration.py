from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.agent import models as agent_models  # noqa: F401
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import (
    IndexVersion,
    IndexVersionState,
    KnowledgeBase,
    MarkdownNote,
    MarkdownNoteState,
    MarkdownRevision,
    MarkdownRevisionState,
)
from tutor_api.knowledge.storage import MemoryObjectStorage
from tutor_api.knowledge.workspace import load_published_note
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault import migration, migration_cli
from tutor_api.vault.migration import (
    MigrationManifest,
    MigrationPhase,
    VaultMigrator,
    load_manifest,
    migration_route_for_knowledge_base,
)
from tutor_api.vault.migration_cli import build_parser
from tutor_api.vault.models import (
    VaultChangeEntry,
    VaultChangeSet,
    VaultFile,
    VaultFileKind,
    VaultSyncState,
)
from tutor_api.vault.service import VaultService


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


def graph(session: Session) -> tuple[User, Space, KnowledgeBase]:
    user = User(email="migration@example.com", username="migration", password_hash="h")
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name="Migration")
    session.add(space)
    session.flush()
    kb = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name="Migration KB",
    )
    session.add(kb)
    session.flush()
    return user, space, kb


def add_note(
    session: Session,
    user: User,
    space: Space,
    kb: KnowledgeBase,
    *,
    title: str,
    markdown: str | None,
    object_key: str | None = None,
) -> MarkdownNote:
    note = MarkdownNote(
        space_id=space.id,
        knowledge_base_id=kb.id,
        title=title,
        normalized_title=title.casefold(),
        state=MarkdownNoteState.PUBLISHED,
        created_by_user_id=user.id,
    )
    session.add(note)
    session.flush()
    revision = MarkdownRevision(
        space_id=space.id,
        knowledge_base_id=kb.id,
        note_id=note.id,
        revision_number=1,
        state=MarkdownRevisionState.PUBLISHED,
        markdown=markdown,
        content_sha256=(
            hashlib.sha256(markdown.encode("utf-8")).hexdigest() if markdown is not None else None
        ),
        source_markers=([f"object:{object_key}"] if object_key else []),
        created_by_user_id=user.id,
    )
    session.add(revision)
    session.flush()
    return note


def migrator(session: Session, tmp_path: Path, storage: MemoryObjectStorage) -> VaultMigrator:
    return VaultMigrator(
        session=session,
        object_storage=storage,
        vault_root=tmp_path / "vault",
        artifact_root=tmp_path / "artifacts",
    )


def add_index(
    session: Session,
    user: User,
    space: Space,
    kb: KnowledgeBase,
    *,
    version: int,
    state: IndexVersionState,
) -> IndexVersion:
    index = IndexVersion(
        space_id=space.id,
        knowledge_base_id=kb.id,
        version_number=version,
        state=state,
        parser_signature=f"parser-{version}",
        ocr_signature=f"ocr-{version}",
        chunking_signature=f"chunking-{version}",
        embedding_backend="hash",
        embedding_model="migration-test",
        embedding_dimension=8,
        embedding_contract_signature=f"embedding-{version}",
        index_signature=f"index-{version}",
        activation_status="active" if state is IndexVersionState.ACTIVE else "retired",
        created_by_user_id=user.id,
        completed_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
    )
    session.add(index)
    session.flush()
    return index


def test_migration_preserves_file_count_size_and_hash(session: Session, tmp_path: Path) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="第一章", markdown="# 第一章\n内容")
    add_note(session, user, space, kb, title="第二章", markdown="# 第二章\n更多内容")
    storage = MemoryObjectStorage()
    service = migrator(session, tmp_path, storage)

    manifest = service.inventory(knowledge_base_id=kb.id)
    copy_result = service.copy(manifest)
    verify_result = service.verify(manifest)

    assert copy_result.conflicts == []
    assert verify_result.source_file_count == verify_result.vault_file_count == 2
    assert verify_result.source_total_bytes == verify_result.vault_total_bytes
    assert verify_result.hash_mismatches == []
    assert len(list(session.scalars(select(VaultFile)))) == 2
    assert len(list(session.scalars(select(VaultChangeSet)))) == 1
    assert len(load_manifest(manifest.path).entries) == 2


def test_minio_fallback_unicode_windows_path_and_duplicate_title_are_stable(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    key = "legacy/教材/章一.md"
    storage = MemoryObjectStorage()
    storage.put_if_absent(key, "来自 MinIO".encode(), content_type="text/markdown")
    add_note(
        session,
        user,
        space,
        kb,
        title="教材\\章一",
        markdown=None,
        object_key=key,
    )
    add_note(session, user, space, kb, title="教材/章一", markdown="数据库正文")
    service = migrator(session, tmp_path, storage)

    manifest = service.inventory(knowledge_base_id=kb.id)
    assert len({entry.relative_path for entry in manifest.entries}) == 2
    assert all(
        "\\" not in entry.relative_path and ".." not in entry.relative_path
        for entry in manifest.entries
    )
    assert any("教材/章一" in entry.relative_path for entry in manifest.entries)
    service.copy(manifest)
    assert service.verify(manifest).hash_mismatches == []


def test_conflict_does_not_overwrite_existing_vault_file(session: Session, tmp_path: Path) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="冲突", markdown="legacy")
    storage = MemoryObjectStorage()
    service = migrator(session, tmp_path, storage)
    manifest = service.inventory(knowledge_base_id=kb.id)
    target = service.scoped_vault_root(manifest) / manifest.entries[0].relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("existing", encoding="utf-8")

    result = service.copy(manifest)

    assert len(result.conflicts) == 1
    assert result.conflicts[0].suggested_relative_path != manifest.entries[0].relative_path
    assert target.read_text(encoding="utf-8") == "existing"
    report = json.loads(result.conflict_report_path.read_text(encoding="utf-8"))
    assert report[0]["source_hash"] == manifest.entries[0].sha256


def test_copy_resumes_after_crash_without_rewriting_verified_files(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="恢复", markdown="resume")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    first = service.copy(manifest)
    target = service.scoped_vault_root(manifest) / manifest.entries[0].relative_path
    first_mtime = target.stat().st_mtime_ns
    second = service.copy(manifest)
    assert first.copied == 1
    assert second.reused == 1 and second.copied == 0
    assert target.stat().st_mtime_ns == first_mtime
    assert len(list(session.scalars(select(VaultChangeSet)))) == 1


def test_cutover_requires_verified_manifest_and_rollback_keeps_vault_files(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="切换", markdown="cutover")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    service.copy(manifest)
    with pytest.raises(RuntimeError, match="migration_not_verified"):
        service.cutover(manifest)
    service.verify(manifest)
    assert service.activate_shadow(manifest).phase is MigrationPhase.SHADOW
    assert service.cutover(manifest).phase is MigrationPhase.VAULT_AUTHORITATIVE
    target = service.scoped_vault_root(manifest) / manifest.entries[0].relative_path
    assert service.rollback(manifest).phase is MigrationPhase.LEGACY_AUTHORITATIVE
    assert target.exists()


def test_empty_knowledge_base_migrates_and_verifies(session: Session, tmp_path: Path) -> None:
    _, _, kb = graph(session)
    service = migrator(session, tmp_path, MemoryObjectStorage())

    manifest = service.inventory(knowledge_base_id=kb.id)
    copy_result = service.copy(manifest)
    verify_result = service.verify(manifest)

    assert manifest.entries == ()
    assert copy_result.copied == copy_result.reused == 0
    assert copy_result.conflicts == []
    assert verify_result.source_file_count == verify_result.vault_file_count == 0
    assert verify_result.source_total_bytes == verify_result.vault_total_bytes == 0
    assert verify_result.hash_mismatches == []
    service.activate_shadow(manifest)
    assert service.cutover(manifest).phase is MigrationPhase.VAULT_AUTHORITATIVE


def test_cli_parser_exposes_all_reversible_phases(tmp_path: Path) -> None:
    parser = build_parser()
    inventory = parser.parse_args(
        ["inventory", "--knowledge-base-id", "11111111-1111-1111-1111-111111111111"]
    )
    assert inventory.command == "inventory"
    manifest = tmp_path / "manifest.jsonl"
    for command in ("copy", "verify", "activate-shadow", "cutover", "rollback"):
        parsed = parser.parse_args([command, "--manifest", str(manifest)])
        assert parsed.command == command
        assert parsed.manifest == manifest
        assert callable(parsed.handler)


def test_rollback_restores_previous_active_index(session: Session, tmp_path: Path) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="回滚索引", markdown="rollback index")
    previous = add_index(session, user, space, kb, version=1, state=IndexVersionState.ACTIVE)
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    previous.state = IndexVersionState.RETIRED
    previous.activation_status = "retired"
    session.flush()
    replacement = add_index(session, user, space, kb, version=2, state=IndexVersionState.ACTIVE)
    service.copy(manifest)
    service.verify(manifest)
    service.activate_shadow(manifest)
    service.cutover(manifest)

    service.rollback(manifest)
    session.expire_all()

    restored_previous = session.get(IndexVersion, previous.id)
    retired_replacement = session.get(IndexVersion, replacement.id)
    assert restored_previous is not None
    assert retired_replacement is not None
    assert restored_previous.state is IndexVersionState.ACTIVE
    assert restored_previous.activation_status == "active"
    assert retired_replacement.state is IndexVersionState.RETIRED
    assert retired_replacement.activation_status == "retired"
    assert (service.scoped_vault_root(manifest) / manifest.entries[0].relative_path).exists()


def _prepare_index_rollback(
    session: Session, tmp_path: Path
) -> tuple[
    VaultMigrator,
    MigrationManifest,
    User,
    Space,
    KnowledgeBase,
    IndexVersion,
    IndexVersion,
]:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="回滚校验", markdown="rollback validation")
    previous = add_index(session, user, space, kb, version=1, state=IndexVersionState.ACTIVE)
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    previous.state = IndexVersionState.RETIRED
    previous.activation_status = "retired"
    session.flush()
    replacement = add_index(session, user, space, kb, version=2, state=IndexVersionState.ACTIVE)
    service.copy(manifest)
    service.verify(manifest)
    service.activate_shadow(manifest)
    service.cutover(manifest)
    return service, manifest, user, space, kb, previous, replacement


def test_rollback_rejects_previous_index_from_foreign_knowledge_base_before_updates(
    session: Session, tmp_path: Path
) -> None:
    service, manifest, user, space, kb, previous, replacement = _prepare_index_rollback(
        session, tmp_path
    )
    foreign_kb = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name="Foreign KB",
    )
    session.add(foreign_kb)
    session.flush()
    foreign_previous = add_index(
        session, user, space, foreign_kb, version=1, state=IndexVersionState.RETIRED
    )
    foreign_current = add_index(
        session, user, space, foreign_kb, version=2, state=IndexVersionState.ACTIVE
    )
    state_path = manifest.path.with_suffix(".state.json")
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state_payload["previous_active_index_id"] = str(foreign_previous.id)
    state_path.write_text(json.dumps(state_payload), encoding="utf-8")
    state_before = state_path.read_bytes()
    route_before = migration_route_for_knowledge_base(session, kb.id)

    with pytest.raises(RuntimeError, match="^migration_previous_index_scope_mismatch$"):
        service.rollback(manifest)

    assert state_path.read_bytes() == state_before
    assert migration_route_for_knowledge_base(session, kb.id) == route_before
    assert previous.state is IndexVersionState.RETIRED
    assert replacement.state is IndexVersionState.ACTIVE
    assert foreign_previous.state is IndexVersionState.RETIRED
    assert foreign_current.state is IndexVersionState.ACTIVE


def test_rollback_rejects_previous_index_from_foreign_space_before_updates(
    session: Session, tmp_path: Path
) -> None:
    service, manifest, user, _, kb, previous, replacement = _prepare_index_rollback(
        session, tmp_path
    )
    foreign_owner = User(
        email="foreign-space@example.com", username="foreign-space", password_hash="h"
    )
    session.add(foreign_owner)
    session.flush()
    foreign_space = Space(owner_id=foreign_owner.id, kind=SpaceKind.PERSONAL, name="Foreign Space")
    session.add(foreign_space)
    session.flush()
    foreign_kb = KnowledgeBase(
        space_id=foreign_space.id,
        owner_user_id=foreign_owner.id,
        created_by_user_id=foreign_owner.id,
        name="Foreign Space KB",
    )
    session.add(foreign_kb)
    session.flush()
    foreign_previous = add_index(
        session,
        foreign_owner,
        foreign_space,
        foreign_kb,
        version=1,
        state=IndexVersionState.RETIRED,
    )
    state_path = manifest.path.with_suffix(".state.json")
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state_payload["previous_active_index_id"] = str(foreign_previous.id)
    state_path.write_text(json.dumps(state_payload), encoding="utf-8")
    state_before = state_path.read_bytes()
    route_before = migration_route_for_knowledge_base(session, kb.id)

    with pytest.raises(RuntimeError, match="^migration_previous_index_scope_mismatch$"):
        service.rollback(manifest)

    assert state_path.read_bytes() == state_before
    assert migration_route_for_knowledge_base(session, kb.id) == route_before
    assert previous.state is IndexVersionState.RETIRED
    assert replacement.state is IndexVersionState.ACTIVE
    assert foreign_previous.state is IndexVersionState.RETIRED


def test_rollback_rejects_missing_previous_index_without_publishing_legacy_state(
    session: Session, tmp_path: Path
) -> None:
    service, manifest, _, _, kb, previous, replacement = _prepare_index_rollback(session, tmp_path)
    session.delete(previous)
    session.flush()
    state_path = manifest.path.with_suffix(".state.json")
    state_before = state_path.read_bytes()
    route_before = migration_route_for_knowledge_base(session, kb.id)

    with pytest.raises(RuntimeError, match="^migration_previous_index_missing$"):
        service.rollback(manifest)

    assert state_path.read_bytes() == state_before
    assert migration_route_for_knowledge_base(session, kb.id) == route_before
    assert replacement.state is IndexVersionState.ACTIVE


def test_cli_rollback_publishes_state_only_after_successful_commit(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, manifest, _, _, kb, previous, replacement = _prepare_index_rollback(session, tmp_path)
    session.commit()
    state_path = manifest.path.with_suffix(".state.json")
    state_before = state_path.read_bytes()
    route_before = migration_route_for_knowledge_base(session, kb.id)

    original_commit = session.commit

    def fail_commit() -> None:
        raise RuntimeError("forced_commit_failure")

    monkeypatch.setattr(session, "commit", fail_commit)
    monkeypatch.setattr(migration_cli, "_SERVICE_FACTORY", lambda _args: service)

    with pytest.raises(RuntimeError, match="^forced_commit_failure$"):
        migration_cli.main(["rollback", "--manifest", str(manifest.path)])

    session.expire_all()
    assert state_path.read_bytes() == state_before
    assert migration_route_for_knowledge_base(session, kb.id) == route_before
    restored_previous = session.get(IndexVersion, previous.id)
    active_replacement = session.get(IndexVersion, replacement.id)
    assert restored_previous is not None
    assert active_replacement is not None
    assert restored_previous.state is IndexVersionState.RETIRED
    assert restored_previous.activation_status == "retired"
    assert active_replacement.state is IndexVersionState.ACTIVE
    assert active_replacement.activation_status == "active"

    monkeypatch.setattr(session, "commit", original_commit)
    assert migration_cli.main(["rollback", "--manifest", str(manifest.path)]) == 0
    session.expire_all()

    published_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert published_state["phase"] == MigrationPhase.LEGACY_AUTHORITATIVE.value
    committed_route = migration_route_for_knowledge_base(session, kb.id)
    assert committed_route is not None
    assert committed_route.phase is MigrationPhase.LEGACY_AUTHORITATIVE
    restored_previous = session.get(IndexVersion, previous.id)
    retired_replacement = session.get(IndexVersion, replacement.id)
    assert restored_previous is not None
    assert retired_replacement is not None
    assert restored_previous.state is IndexVersionState.ACTIVE
    assert restored_previous.activation_status == "active"
    assert retired_replacement.state is IndexVersionState.RETIRED
    assert retired_replacement.activation_status == "retired"


def test_nested_commit_then_outer_rollback_restores_db_without_outer_dml(
    session: Session, tmp_path: Path
) -> None:
    service, manifest, _, _, kb, previous, replacement = _prepare_index_rollback(session, tmp_path)
    session.commit()
    state_path = manifest.path.with_suffix(".state.json")
    state_before = state_path.read_bytes()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    with factory() as rollback_session:
        rollback_service = migrator(rollback_session, tmp_path, service.object_storage)
        outer = rollback_session.begin()
        nested = rollback_session.begin_nested()
        rollback_service.rollback(manifest)
        nested.commit()

        assert state_path.read_bytes() == state_before
        outer.rollback()
        assert migration._PENDING_STATE_WRITES_KEY not in rollback_session.info

        rollback_session.commit()
        assert state_path.read_bytes() == state_before
        assert migration._PENDING_STATE_WRITES_KEY not in rollback_session.info

    with factory() as verify_session:
        route = migration_route_for_knowledge_base(verify_session, kb.id)
        assert route is not None
        assert route.phase is MigrationPhase.VAULT_AUTHORITATIVE
        restored_previous = verify_session.get(IndexVersion, previous.id)
        active_replacement = verify_session.get(IndexVersion, replacement.id)
        assert restored_previous is not None
        assert active_replacement is not None
        assert restored_previous.state is IndexVersionState.RETIRED
        assert restored_previous.activation_status == "retired"
        assert active_replacement.state is IndexVersionState.ACTIVE
        assert active_replacement.activation_status == "active"


def test_outer_rollback_state_survives_unrelated_savepoint_rollback(
    session: Session, tmp_path: Path
) -> None:
    service, manifest, _, _, kb, previous, replacement = _prepare_index_rollback(session, tmp_path)
    session.commit()
    state_path = manifest.path.with_suffix(".state.json")

    outer = session.begin()
    service.rollback(manifest)
    nested = session.begin_nested()
    kb.name = "Nested marker that is rolled back"
    session.flush()
    nested.rollback()
    outer.commit()
    session.expire_all()

    published_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert published_state["phase"] == MigrationPhase.LEGACY_AUTHORITATIVE.value
    route = migration_route_for_knowledge_base(session, kb.id)
    assert route is not None
    assert route.phase is MigrationPhase.LEGACY_AUTHORITATIVE
    restored_previous = session.get(IndexVersion, previous.id)
    retired_replacement = session.get(IndexVersion, replacement.id)
    assert restored_previous is not None
    assert retired_replacement is not None
    assert restored_previous.state is IndexVersionState.ACTIVE
    assert retired_replacement.state is IndexVersionState.RETIRED


def test_rollback_without_previous_index_retires_active_replacement(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="No previous index", markdown="body")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    replacement = add_index(session, user, space, kb, version=1, state=IndexVersionState.ACTIVE)
    service.copy(manifest)
    service.verify(manifest)
    service.activate_shadow(manifest)
    service.cutover(manifest)

    state = service.rollback(manifest)
    session.commit()
    session.expire_all()

    assert state.previous_active_index_id is None
    retired_replacement = session.get(IndexVersion, replacement.id)
    assert retired_replacement is not None
    assert retired_replacement.state is IndexVersionState.RETIRED
    assert retired_replacement.activation_status == "retired"
    active_indexes = list(
        session.scalars(
            select(IndexVersion).where(
                IndexVersion.knowledge_base_id == kb.id,
                IndexVersion.space_id == space.id,
                IndexVersion.state == IndexVersionState.ACTIVE,
            )
        )
    )
    assert active_indexes == []


def test_outer_commit_publishes_multiple_pending_manifest_states(
    session: Session, tmp_path: Path
) -> None:
    service, first_manifest, user, space, _, _, _ = _prepare_index_rollback(session, tmp_path)
    second_kb = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name="Second migration KB",
    )
    session.add(second_kb)
    session.flush()
    add_note(session, user, space, second_kb, title="Second", markdown="second body")
    second_previous = add_index(
        session, user, space, second_kb, version=1, state=IndexVersionState.ACTIVE
    )
    second_manifest = service.inventory(knowledge_base_id=second_kb.id)
    second_previous.state = IndexVersionState.RETIRED
    second_previous.activation_status = "retired"
    session.flush()
    add_index(session, user, space, second_kb, version=2, state=IndexVersionState.ACTIVE)
    service.copy(second_manifest)
    service.verify(second_manifest)
    service.activate_shadow(second_manifest)
    service.cutover(second_manifest)
    session.commit()

    outer = session.begin()
    service.rollback(first_manifest)
    service.rollback(second_manifest)
    outer.commit()

    for manifest in (first_manifest, second_manifest):
        payload = json.loads(manifest.path.with_suffix(".state.json").read_text(encoding="utf-8"))
        assert payload["phase"] == MigrationPhase.LEGACY_AUTHORITATIVE.value


def test_cli_post_commit_publish_failure_is_stable_and_fresh_session_retry_recovers(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service, manifest, _, _, kb, previous, replacement = _prepare_index_rollback(session, tmp_path)
    session.commit()
    bind = session.get_bind()
    knowledge_base_id = kb.id
    previous_id = previous.id
    replacement_id = replacement.id
    state_path = manifest.path.with_suffix(".state.json")
    state_before = state_path.read_bytes()
    original_write = migration._write_json_atomic
    original_rollback = session.rollback
    rollback_calls = 0
    sensitive_detail = r"C:\Users\asus\private-vault\manifest.state.json"

    def fail_publish(_path: Path, _payload: object) -> None:
        raise OSError(sensitive_detail)

    def count_rollback() -> None:
        nonlocal rollback_calls
        rollback_calls += 1
        original_rollback()

    monkeypatch.setattr(migration, "_write_json_atomic", fail_publish)
    monkeypatch.setattr(session, "rollback", count_rollback)
    monkeypatch.setattr(migration_cli, "_SERVICE_FACTORY", lambda _args: service)

    with pytest.raises(RuntimeError, match="^migration_state_publish_failed$") as caught:
        migration_cli.main(["rollback", "--manifest", str(manifest.path)])

    assert rollback_calls == 0
    assert isinstance(caught.value.__cause__, OSError)
    assert str(caught.value) == "migration_state_publish_failed"
    captured = capsys.readouterr()
    assert sensitive_detail not in captured.out
    assert sensitive_detail not in captured.err
    assert state_path.read_bytes() == state_before
    session.close()
    factory = sessionmaker(bind=bind, expire_on_commit=False)
    with factory() as probe_session:
        committed_route = migration_route_for_knowledge_base(probe_session, knowledge_base_id)
        assert committed_route is not None
        assert committed_route.phase is MigrationPhase.LEGACY_AUTHORITATIVE
        assert probe_session.get(IndexVersion, previous_id).state is IndexVersionState.ACTIVE
        assert probe_session.get(IndexVersion, replacement_id).state is IndexVersionState.RETIRED

    writes: list[Path] = []

    def record_publish(path: Path, payload: object) -> None:
        writes.append(path)
        original_write(path, payload)

    monkeypatch.setattr(migration, "_write_json_atomic", record_publish)
    with factory() as retry_session:
        retry_service = migrator(retry_session, tmp_path, MemoryObjectStorage())
        monkeypatch.setattr(migration_cli, "_SERVICE_FACTORY", lambda _args: retry_service)
        assert migration_cli.main(["rollback", "--manifest", str(manifest.path)]) == 0
        published_state = json.loads(state_path.read_text(encoding="utf-8"))
        assert published_state["phase"] == MigrationPhase.LEGACY_AUTHORITATIVE.value
        assert writes == [state_path]

        retry_session.commit()
        assert writes == [state_path]
        route = migration_route_for_knowledge_base(retry_session, knowledge_base_id)
        assert route is not None
        assert route.phase is MigrationPhase.LEGACY_AUTHORITATIVE


def test_cli_entrypoint_logs_only_stable_publish_failure_code(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service, manifest, *_ = _prepare_index_rollback(session, tmp_path)
    session.commit()
    sensitive_detail = r"C:\Users\asus\private-vault\manifest.state.json"

    def fail_publish(_path: Path, _payload: object) -> None:
        raise OSError(sensitive_detail)

    monkeypatch.setattr(migration, "_write_json_atomic", fail_publish)
    monkeypatch.setattr(migration_cli, "_SERVICE_FACTORY", lambda _args: service)

    assert migration_cli.entrypoint(["rollback", "--manifest", str(manifest.path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "migration_state_publish_failed"
    assert sensitive_detail not in captured.err


def test_load_manifest_rejects_parent_traversal(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    payload = {
        "space_id": str(uuid4()),
        "knowledge_base_id": str(uuid4()),
        "note_id": str(uuid4()),
        "revision_id": str(uuid4()),
        "revision_number": 1,
        "relative_path": "../../outside.md",
        "source_kind": "database_markdown",
        "source_reference": str(uuid4()),
        "size_bytes": len(outside.read_bytes()),
        "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
    }
    path = tmp_path / "malicious.jsonl"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="migration_path_invalid"):
        load_manifest(path)


def test_conflict_resolution_reuses_manifest_ordinals_without_unique_collision(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="A", markdown="alpha")
    add_note(session, user, space, kb, title="B", markdown="beta")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    first_target = service.scoped_vault_root(manifest) / manifest.entries[0].relative_path
    first_target.parent.mkdir(parents=True, exist_ok=True)
    first_target.write_text("conflict", encoding="utf-8")

    assert len(service.copy(manifest).conflicts) == 1
    first_target.write_bytes(service._source_bytes(manifest.entries[0]))
    resumed = service.copy(manifest)

    assert resumed.conflicts == []
    entries = list(session.scalars(select(VaultChangeEntry).order_by(VaultChangeEntry.ordinal)))
    assert [(entry.ordinal, entry.after_path) for entry in entries] == [
        (0, manifest.entries[0].relative_path),
        (1, manifest.entries[1].relative_path),
    ]


def test_projection_conflict_is_detected_before_any_file_is_written(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="投影冲突", markdown="source")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    entry = manifest.entries[0]
    session.add(
        VaultFile(
            space_id=space.id,
            knowledge_base_id=kb.id,
            relative_path=entry.relative_path,
            file_kind=VaultFileKind.MARKDOWN,
            content_hash=hashlib.sha256(b"different").hexdigest(),
            size_bytes=len(b"different"),
            sync_state=VaultSyncState.SYNCED,
        )
    )
    session.flush()
    target = service.scoped_vault_root(manifest) / entry.relative_path

    with pytest.raises(RuntimeError, match="migration_projection_conflict"):
        service.copy(manifest)

    assert not target.exists()


def test_migration_revision_records_change_set_provenance(session: Session, tmp_path: Path) -> None:
    user, space, kb = graph(session)
    note = add_note(session, user, space, kb, title="来源", markdown="provenance")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)

    service.copy(manifest)
    revision = session.scalar(select(MarkdownRevision).where(MarkdownRevision.note_id == note.id))
    change_set = session.scalar(select(VaultChangeSet))

    assert revision is not None and change_set is not None
    assert revision.change_set_id == change_set.id
    assert revision.change_source == "initial_migration"
    assert revision.before_hash == revision.after_hash == manifest.entries[0].sha256


def test_cutover_rejects_manifest_tampering_and_source_snapshot_changes(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    note = add_note(session, user, space, kb, title="绑定", markdown="original")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    service.copy(manifest)
    service.verify(manifest)
    service.activate_shadow(manifest)

    manifest.path.write_text(manifest.path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="migration_manifest_changed"):
        service.cutover(manifest)

    manifest = service.inventory(knowledge_base_id=kb.id)
    service.copy(manifest)
    service.verify(manifest)
    service.activate_shadow(manifest)
    revision = session.scalar(select(MarkdownRevision).where(MarkdownRevision.note_id == note.id))
    assert revision is not None
    revision.markdown = "changed after verification"
    revision.content_sha256 = hashlib.sha256(revision.markdown.encode()).hexdigest()
    session.flush()

    with pytest.raises(RuntimeError, match="migration_source_changed"):
        service.cutover(manifest)


def test_cutover_requires_shadow_and_clean_conflict_state(session: Session, tmp_path: Path) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="阶段", markdown="phase")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    service.copy(manifest)
    service.verify(manifest)

    with pytest.raises(RuntimeError, match="migration_shadow_required"):
        service.cutover(manifest)

    state_payload = json.loads(manifest.path.with_suffix(".state.json").read_text(encoding="utf-8"))
    assert (
        state_payload["manifest_sha256"] == hashlib.sha256(manifest.path.read_bytes()).hexdigest()
    )
    assert state_payload["knowledge_base_id"] == str(kb.id)
    assert state_payload["space_id"] == str(space.id)
    assert state_payload["source_snapshot_sha256"]
    assert state_payload["conflict_count"] == 0


def test_cutover_and_rollback_switch_workspace_note_reads_between_vault_and_legacy(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    note = add_note(session, user, space, kb, title="真实路由", markdown="vault source")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    service.copy(manifest)
    service.verify(manifest)
    service.activate_shadow(manifest)
    service.cutover(manifest)

    revision = session.scalar(select(MarkdownRevision).where(MarkdownRevision.note_id == note.id))
    assert revision is not None
    revision.markdown = "legacy changed after cutover"
    revision.content_sha256 = hashlib.sha256(revision.markdown.encode()).hexdigest()
    session.flush()

    assert load_published_note(session, user, kb.id, note.id).markdown == "vault source"
    service.rollback(manifest)
    assert (
        load_published_note(session, user, kb.id, note.id).markdown
        == "legacy changed after cutover"
    )
    assert (service.scoped_vault_root(manifest) / manifest.entries[0].relative_path).exists()


def test_cli_default_bootstrap_commits_and_emits_artifact_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine_from_url(database_url, app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as seed:
        user, space, kb = graph(seed)
        add_note(seed, user, space, kb, title="CLI", markdown="cli body")
        knowledge_base_id = kb.id
        seed.commit()
    engine.dispose()
    settings = Settings(
        app_env="test",
        database_url=database_url,
        agent_vault_root=str(tmp_path / "vault"),
    )
    monkeypatch.setattr(migration_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(migration_cli, "create_object_storage", lambda _: MemoryObjectStorage())

    assert (
        migration_cli.main(
            [
                "inventory",
                "--knowledge-base-id",
                str(knowledge_base_id),
                "--artifact-root",
                str(tmp_path / "artifacts"),
            ]
        )
        == 0
    )
    inventory_output = json.loads(capsys.readouterr().out)
    manifest_path = Path(inventory_output["manifest_path"])
    assert manifest_path.is_file()

    assert migration_cli.main(["copy", "--manifest", str(manifest_path)]) == 0
    copy_output = json.loads(capsys.readouterr().out)
    assert Path(copy_output["result_path"]).is_file()
    verify_engine = create_engine_from_url(database_url, app_env="test")
    with sessionmaker(bind=verify_engine)() as verify_session:
        assert verify_session.scalar(select(func.count()).select_from(VaultFile)) == 1
    verify_engine.dispose()


def test_cli_default_bootstrap_rolls_back_failed_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "rollback.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine_from_url(database_url, app_env="test")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as seed:
        user, space, kb = graph(seed)
        add_note(seed, user, space, kb, title="CLI rollback", markdown="body")
        knowledge_base_id = kb.id
        seed.commit()
    engine.dispose()
    settings = Settings(
        app_env="test",
        database_url=database_url,
        agent_vault_root=str(tmp_path / "vault"),
    )
    monkeypatch.setattr(migration_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(migration_cli, "create_object_storage", lambda _: MemoryObjectStorage())
    assert (
        migration_cli.main(
            [
                "inventory",
                "--knowledge-base-id",
                str(knowledge_base_id),
                "--artifact-root",
                str(tmp_path / "artifacts"),
            ]
        )
        == 0
    )
    manifest_path = Path(json.loads(capsys.readouterr().out)["manifest_path"])
    original = VaultMigrator.copy

    def fail_after_projection(self: VaultMigrator, manifest):
        original(self, manifest)
        raise RuntimeError("forced_cli_failure")

    monkeypatch.setattr(VaultMigrator, "copy", fail_after_projection)
    with pytest.raises(RuntimeError, match="forced_cli_failure"):
        migration_cli.main(["copy", "--manifest", str(manifest_path)])

    verify_engine = create_engine_from_url(database_url, app_env="test")
    with sessionmaker(bind=verify_engine)() as verify_session:
        assert verify_session.scalar(select(func.count()).select_from(VaultFile)) == 0
    verify_engine.dispose()


def test_migration_uses_knowledge_base_scoped_permanent_vault_layout(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    note = add_note(session, user, space, kb, title="Scoped", markdown="scoped body")
    service = migrator(session, tmp_path, MemoryObjectStorage())

    manifest = service.inventory(knowledge_base_id=kb.id)
    service.copy(manifest)
    service.verify(manifest)
    service.activate_shadow(manifest)
    service.cutover(manifest)

    scoped_path = (
        service.vault_root
        / "spaces"
        / str(space.id)
        / str(kb.id)
        / manifest.entries[0].relative_path
    )
    assert scoped_path.read_text(encoding="utf-8") == "scoped body"
    vault = VaultService(
        session,
        service.vault_root,
        space_id=space.id,
        knowledge_base_id=kb.id,
        actor_user_id=user.id,
    )
    row, raw = vault.read(note.vault_file_id)
    assert row.relative_path == manifest.entries[0].relative_path
    assert raw == b"scoped body"


def test_migration_scopes_same_relative_path_between_knowledge_bases(
    session: Session, tmp_path: Path
) -> None:
    user, space, first = graph(session)
    second = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name="Second KB",
    )
    session.add(second)
    session.flush()
    add_note(session, user, space, first, title="Shared", markdown="first")
    add_note(session, user, space, second, title="Shared", markdown="second")
    service = migrator(session, tmp_path, MemoryObjectStorage())

    first_manifest = service.inventory(knowledge_base_id=first.id)
    second_manifest = service.inventory(knowledge_base_id=second.id)
    service.copy(first_manifest)
    service.copy(second_manifest)

    first_path = (
        service.vault_root
        / "spaces"
        / str(space.id)
        / str(first.id)
        / first_manifest.entries[0].relative_path
    )
    second_path = (
        service.vault_root
        / "spaces"
        / str(space.id)
        / str(second.id)
        / second_manifest.entries[0].relative_path
    )
    assert first_path.read_text(encoding="utf-8") == "first"
    assert second_path.read_text(encoding="utf-8") == "second"


def test_activate_shadow_rechecks_vault_bytes_after_verify(
    session: Session, tmp_path: Path
) -> None:
    user, space, kb = graph(session)
    add_note(session, user, space, kb, title="Shadow", markdown="verified")
    service = migrator(session, tmp_path, MemoryObjectStorage())
    manifest = service.inventory(knowledge_base_id=kb.id)
    service.copy(manifest)
    service.verify(manifest)
    target = (
        service.vault_root
        / "spaces"
        / str(space.id)
        / str(kb.id)
        / manifest.entries[0].relative_path
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("tampered", encoding="utf-8")

    with pytest.raises(RuntimeError, match="migration_shadow_mismatch"):
        service.activate_shadow(manifest)
