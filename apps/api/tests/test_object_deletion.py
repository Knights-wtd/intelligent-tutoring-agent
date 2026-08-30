from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

import tutor_api.agent.models  # noqa: F401
import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.knowledge.worker as knowledge_worker
import tutor_api.question_bank.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
import tutor_api.tutor.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.knowledge.models import ObjectDeletionOutbox, ObjectDeletionState
from tutor_api.knowledge.object_deletion import (
    build_vault_scope_deletion_key,
    run_object_deletion_once,
)
from tutor_api.knowledge.storage import MemoryObjectStorage, ObjectNotFoundError
from tutor_api.knowledge.worker import WorkerConfig, run_worker_forever


def make_session_factory() -> tuple[sessionmaker[Session], object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


def test_memory_storage_delete_is_idempotent() -> None:
    storage = MemoryObjectStorage()
    storage.put_if_absent("delete/me.txt", b"data", content_type="text/plain")

    storage.delete_object("delete/me.txt")
    storage.delete_object("delete/me.txt")

    try:
        storage.get_object("delete/me.txt")
    except ObjectNotFoundError:
        pass
    else:
        raise AssertionError("deleted object must not remain readable")


def test_cleanup_worker_deletes_scoped_vault_directory_and_marks_completed(
    tmp_path: Path,
) -> None:
    factory, engine = make_session_factory()
    storage = MemoryObjectStorage()
    space_id = uuid4()
    knowledge_base_id = uuid4()
    scope = tmp_path / "spaces" / str(space_id) / str(knowledge_base_id)
    scope.mkdir(parents=True)
    (scope / "lesson.md").write_text("sensitive lesson", encoding="utf-8")
    with factory.begin() as session:
        item = ObjectDeletionOutbox(
            object_key=build_vault_scope_deletion_key(space_id, knowledge_base_id)
        )
        session.add(item)
        session.flush()
        item_id = item.id

    worked = run_object_deletion_once(
        factory,
        storage,
        worker_id="vault-cleanup-worker",
        vault_root=tmp_path,
    )

    assert worked is True
    assert not scope.exists()
    with factory() as session:
        completed = session.get(ObjectDeletionOutbox, item_id)
        assert completed is not None
        assert completed.state == ObjectDeletionState.COMPLETED
        assert completed.last_error_code is None
    engine.dispose()


def test_cleanup_worker_unlinks_vault_scope_symlink_without_deleting_target(
    tmp_path: Path,
) -> None:
    factory, engine = make_session_factory()
    storage = MemoryObjectStorage()
    space_id = uuid4()
    knowledge_base_id = uuid4()
    outside = tmp_path / "outside-scope"
    outside.mkdir()
    lesson = outside / "lesson.md"
    lesson.write_text("must remain", encoding="utf-8")
    scope = tmp_path / "vault" / "spaces" / str(space_id) / str(knowledge_base_id)
    scope.parent.mkdir(parents=True)
    try:
        scope.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")
    with factory.begin() as session:
        session.add(
            ObjectDeletionOutbox(
                object_key=build_vault_scope_deletion_key(space_id, knowledge_base_id)
            )
        )

    assert run_object_deletion_once(
        factory,
        storage,
        worker_id="vault-cleanup-worker",
        vault_root=tmp_path / "vault",
    )

    assert not scope.exists()
    assert lesson.read_text(encoding="utf-8") == "must remain"
    engine.dispose()


def test_cleanup_worker_refuses_vault_scope_through_parent_symlink(
    tmp_path: Path,
) -> None:
    factory, engine = make_session_factory()
    storage = MemoryObjectStorage()
    space_id = uuid4()
    knowledge_base_id = uuid4()
    outside_space = tmp_path / "outside-space"
    outside_scope = outside_space / str(knowledge_base_id)
    outside_scope.mkdir(parents=True)
    lesson = outside_scope / "lesson.md"
    lesson.write_text("must remain", encoding="utf-8")
    linked_space = tmp_path / "vault" / "spaces" / str(space_id)
    linked_space.parent.mkdir(parents=True)
    try:
        linked_space.symlink_to(outside_space, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")
    with factory.begin() as session:
        item = ObjectDeletionOutbox(
            object_key=build_vault_scope_deletion_key(space_id, knowledge_base_id)
        )
        session.add(item)
        session.flush()
        item_id = item.id

    assert run_object_deletion_once(
        factory,
        storage,
        worker_id="vault-cleanup-worker",
        vault_root=tmp_path / "vault",
    )

    assert lesson.read_text(encoding="utf-8") == "must remain"
    with factory() as session:
        retrying = session.get(ObjectDeletionOutbox, item_id)
        assert retrying is not None
        assert retrying.state == ObjectDeletionState.RETRY_WAIT
        assert retrying.last_error_code == "vault_scope_delete_failed"
    engine.dispose()


def test_cleanup_worker_retries_vault_scope_when_root_is_unavailable() -> None:
    factory, engine = make_session_factory()
    storage = MemoryObjectStorage()
    with factory.begin() as session:
        item = ObjectDeletionOutbox(
            object_key=build_vault_scope_deletion_key(uuid4(), uuid4())
        )
        session.add(item)
        session.flush()
        item_id = item.id

    worked = run_object_deletion_once(
        factory,
        storage,
        worker_id="vault-cleanup-worker",
        retry_delay=timedelta(seconds=5),
        now=datetime(2026, 8, 30, tzinfo=UTC),
    )

    assert worked is True
    with factory() as session:
        retrying = session.get(ObjectDeletionOutbox, item_id)
        assert retrying is not None
        assert retrying.state == ObjectDeletionState.RETRY_WAIT
        assert retrying.last_error_code == "vault_scope_delete_failed"
    engine.dispose()


def test_cleanup_worker_deletes_object_and_marks_outbox_completed() -> None:
    factory, engine = make_session_factory()
    storage = MemoryObjectStorage()
    storage.put_if_absent("cleanup/success.txt", b"data", content_type="text/plain")
    with factory.begin() as session:
        item = ObjectDeletionOutbox(object_key="cleanup/success.txt")
        session.add(item)
        session.flush()
        item_id = item.id

    worked = run_object_deletion_once(
        factory,
        storage,
        worker_id="cleanup-worker",
        lease_duration=timedelta(minutes=1),
        retry_delay=timedelta(seconds=5),
        now=datetime(2026, 8, 30, tzinfo=UTC),
    )

    assert worked is True
    with factory() as session:
        item = session.get(ObjectDeletionOutbox, item_id)
        assert item is not None
        assert item.state == ObjectDeletionState.COMPLETED
        assert item.attempt_count == 1
        assert item.completed_at == datetime(2026, 8, 30)
        assert item.lease_owner is None
        assert item.last_error_code is None
    try:
        storage.get_object("cleanup/success.txt")
    except ObjectNotFoundError:
        pass
    else:
        raise AssertionError("cleanup worker must delete the object")
    engine.dispose()


class FlakyStorage(MemoryObjectStorage):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    def delete_object(self, key: str) -> None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("secret provider response must not be persisted")
        super().delete_object(key)


def test_cleanup_worker_retries_failure_without_persisting_sensitive_detail() -> None:
    factory, engine = make_session_factory()
    storage = FlakyStorage()
    storage.put_if_absent("cleanup/retry.txt", b"data", content_type="text/plain")
    started = datetime(2026, 8, 30, tzinfo=UTC)
    with factory.begin() as session:
        item = ObjectDeletionOutbox(object_key="cleanup/retry.txt")
        session.add(item)
        session.flush()
        item_id = item.id

    first = run_object_deletion_once(
        factory,
        storage,
        worker_id="cleanup-worker",
        lease_duration=timedelta(minutes=1),
        retry_delay=timedelta(seconds=5),
        now=started,
    )

    assert first is True
    with factory() as session:
        failed = session.get(ObjectDeletionOutbox, item_id)
        assert failed is not None
        assert failed.state == ObjectDeletionState.RETRY_WAIT
        assert failed.attempt_count == 1
        assert failed.available_at == (started + timedelta(seconds=5)).replace(tzinfo=None)
        assert failed.last_error_code == "object_storage_request_failed"
        assert not hasattr(failed, "last_error_detail")
    assert (
        run_object_deletion_once(
            factory,
            storage,
            worker_id="cleanup-worker",
            lease_duration=timedelta(minutes=1),
            retry_delay=timedelta(seconds=5),
            now=started + timedelta(seconds=4),
        )
        is False
    )
    assert (
        run_object_deletion_once(
            factory,
            storage,
            worker_id="cleanup-worker",
            lease_duration=timedelta(minutes=1),
            retry_delay=timedelta(seconds=5),
            now=started + timedelta(seconds=5),
        )
        is True
    )
    with factory() as session:
        completed = session.get(ObjectDeletionOutbox, item_id)
        assert completed is not None
        assert completed.state == ObjectDeletionState.COMPLETED
        assert completed.attempt_count == 2
    engine.dispose()


def test_cleanup_worker_reclaims_expired_lease() -> None:
    factory, engine = make_session_factory()
    storage = MemoryObjectStorage()
    now = datetime(2026, 8, 30, tzinfo=UTC)
    with factory.begin() as session:
        item = ObjectDeletionOutbox(
            object_key=f"cleanup/{uuid4()}.txt",
            state=ObjectDeletionState.RUNNING,
            attempt_count=1,
            lease_owner="dead-worker",
            lease_expires_at=now - timedelta(seconds=1),
        )
        session.add(item)
        session.flush()
        item_id = item.id

    assert run_object_deletion_once(
        factory,
        storage,
        worker_id="replacement-worker",
        lease_duration=timedelta(minutes=1),
        retry_delay=timedelta(seconds=5),
        now=now,
    )

    with factory() as session:
        item = session.get(ObjectDeletionOutbox, item_id)
        assert item is not None
        assert item.state == ObjectDeletionState.COMPLETED
        assert item.attempt_count == 2
    engine.dispose()


class LeaseStealingStorage(MemoryObjectStorage):
    def __init__(
        self, session_factory: sessionmaker[Session], item_id: object
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._item_id = item_id

    def delete_object(self, key: str) -> None:
        super().delete_object(key)
        with self._session_factory.begin() as session:
            item = session.get(ObjectDeletionOutbox, self._item_id)
            assert item is not None
            item.lease_owner = "replacement-worker"
            item.lease_expires_at = datetime(2026, 8, 30, tzinfo=UTC) + timedelta(
                minutes=2
            )


def test_cleanup_worker_does_not_crash_after_success_when_lease_was_reclaimed() -> None:
    factory, engine = make_session_factory()
    with factory.begin() as session:
        item = ObjectDeletionOutbox(object_key="cleanup/lease-lost.txt")
        session.add(item)
        session.flush()
        item_id = item.id
    storage = LeaseStealingStorage(factory, item_id)
    storage.put_if_absent(
        "cleanup/lease-lost.txt", b"data", content_type="text/plain"
    )

    worked = run_object_deletion_once(
        factory,
        storage,
        worker_id="original-worker",
        lease_duration=timedelta(minutes=1),
        now=datetime(2026, 8, 30, tzinfo=UTC),
    )

    assert worked is True
    with factory() as session:
        item = session.get(ObjectDeletionOutbox, item_id)
        assert item is not None
        assert item.state == ObjectDeletionState.RUNNING
        assert item.lease_owner == "replacement-worker"
    engine.dispose()


def test_ingestion_worker_runs_primary_queue_before_cleanup_maintenance(
    monkeypatch: object,
) -> None:
    factory, engine = make_session_factory()
    calls: list[str] = []

    def run_ingestion(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        calls.append("ingestion")
        return False

    def maintenance() -> bool:
        calls.append("cleanup")
        return False

    monkeypatch.setattr(knowledge_worker, "run_worker_once", run_ingestion)
    run_worker_forever(
        factory,
        {},
        config=WorkerConfig(worker_id="ordered-worker", idle_sleep_seconds=0),
        should_stop=lambda: len(calls) >= 2,
        maintenance=maintenance,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("must not sleep")),
    )

    assert calls == ["ingestion", "cleanup"]
    engine.dispose()


def test_ingestion_worker_loop_runs_object_cleanup_maintenance() -> None:
    factory, engine = make_session_factory()
    calls: list[str] = []

    def maintenance() -> bool:
        calls.append("cleanup")
        return True

    run_worker_forever(
        factory,
        {},
        config=WorkerConfig(worker_id="combined-worker", idle_sleep_seconds=0),
        should_stop=lambda: bool(calls),
        maintenance=maintenance,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("must not sleep")),
    )

    assert calls == ["cleanup"]
    engine.dispose()
