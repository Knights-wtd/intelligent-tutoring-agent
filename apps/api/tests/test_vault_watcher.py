from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.agent import models as agent_models  # noqa: F401
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import (
    IndexVersion,
    IndexVersionState,
    IngestionJob,
    IngestionJobState,
    KnowledgeBase,
    KnowledgeBaseState,
)
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault import models as vault_models  # noqa: F401
from tutor_api.vault import watcher as watcher_module
from tutor_api.vault.watcher import (
    VaultScanEnqueueStatus,
    VaultWatcher,
    enqueue_vault_scan,
    scope_for_event,
    start_vault_watcher_thread,
)


@pytest.fixture
def factory(tmp_path: Path) -> Generator[sessionmaker[Session], None, None]:
    database = tmp_path / "watcher.sqlite3"
    engine = create_engine_from_url(f"sqlite:///{database.as_posix()}", app_env="test")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    value = sessionmaker(bind=engine, expire_on_commit=False)
    yield value
    Base.metadata.drop_all(engine)
    engine.dispose()


def add_graph(
    session: Session,
    suffix: str,
    *,
    state: KnowledgeBaseState = KnowledgeBaseState.ACTIVE,
    with_index: bool = True,
    index_state: IndexVersionState = IndexVersionState.ACTIVE,
) -> tuple[User, Space, KnowledgeBase, IndexVersion | None]:
    user = User(email=f"{suffix}@example.com", username=f"watch-{suffix}", password_hash="h")
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name=suffix)
    session.add(space)
    session.flush()
    knowledge_base = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name=f"KB {suffix}",
        state=state,
    )
    session.add(knowledge_base)
    session.flush()
    if not with_index:
        return user, space, knowledge_base, None
    index = IndexVersion(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        version_number=1,
        state=index_state,
        parser_signature="watcher:parser:v1:" + "a" * 64,
        ocr_signature="watcher:ocr:v1:" + "b" * 64,
        chunking_signature="watcher:chunking:v1:" + "c" * 64,
        embedding_backend="hash",
        embedding_model="feature-hash-v1",
        embedding_dimension=8,
        embedding_contract_signature="watcher:embedding:v1:" + "d" * 64,
        index_signature=f"watcher:index:v1:{suffix}:" + "e" * 64,
        created_by_user_id=user.id,
    )
    session.add(index)
    session.flush()
    return user, space, knowledge_base, index


def scoped_root(root: Path, space: Space, knowledge_base: KnowledgeBase) -> Path:
    path = root / "spaces" / str(space.id) / str(knowledge_base.id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def wait_for_job(factory: sessionmaker[Session], knowledge_base_id: object) -> IngestionJob:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        with factory() as session:
            jobs = session.scalars(
                select(IngestionJob).where(IngestionJob.knowledge_base_id == knowledge_base_id)
            ).all()
            job = next(
                (
                    candidate
                    for candidate in jobs
                    if candidate.checkpoint.get("worker_job_kind") == "vault_scan"
                ),
                None,
            )
            if job is not None:
                return job
        time.sleep(0.05)
    raise AssertionError("vault scan job was not durably enqueued")


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


def test_real_watchfiles_event_enqueues_durable_full_scan_job(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    with factory.begin() as session:
        _, space, knowledge_base, index = add_graph(session, "event")
        scope = scoped_root(root, space, knowledge_base)
        knowledge_base_id = knowledge_base.id
        index_id = index.id if index is not None else None

    stop_event = threading.Event()
    watcher = VaultWatcher(
        factory,
        root,
        debounce=timedelta(milliseconds=50),
        reconcile_interval=timedelta(hours=1),
        initial_reconcile=False,
        force_polling=True,
    )
    thread = start_vault_watcher_thread(watcher, stop_event)
    assert watcher.started.wait(2)
    time.sleep(0.15)
    (scope / "event.md").write_text("# watched", encoding="utf-8")

    try:
        job = wait_for_job(factory, knowledge_base_id)
        assert job.index_version_id == index_id
        assert job.state is IngestionJobState.QUEUED
        assert job.checkpoint["worker_job_kind"] == "vault_scan"
        assert job.checkpoint["force_full_scan"] is True
        assert job.checkpoint["reason"] == "watch_event"
    finally:
        stop_event.set()
        thread.join(timeout=3)
    assert not thread.is_alive()


def test_repeated_events_reuse_pending_scan_job_across_time_buckets(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    with factory.begin() as session:
        _, space, knowledge_base, _ = add_graph(session, "dedupe")
        event_path = scoped_root(root, space, knowledge_base) / "note.md"
        event_path.write_text("first", encoding="utf-8")
        scope = scope_for_event(root, event_path)
        assert scope is not None
        first = enqueue_vault_scan(
            session,
            scope,
            reason="watch_event",
            now=datetime(2026, 8, 29, 1, 0, tzinfo=UTC),
            bucket=timedelta(seconds=1),
        )
        second = enqueue_vault_scan(
            session,
            scope,
            reason="watch_event",
            now=datetime(2026, 8, 29, 1, 1, tzinfo=UTC),
            bucket=timedelta(seconds=1),
        )
        count = session.scalar(
            select(func.count(IngestionJob.id)).where(
                IngestionJob.knowledge_base_id == knowledge_base.id
            )
        )

    assert first.status is VaultScanEnqueueStatus.ENQUEUED
    assert second.status is VaultScanEnqueueStatus.DEDUPLICATED
    assert second.job_id == first.job_id
    assert count == 1


def test_periodic_reconciliation_enumerates_active_database_knowledge_bases(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    with factory.begin() as session:
        _, _, active, _ = add_graph(session, "active")
        _, _, archived, _ = add_graph(session, "archived", state=KnowledgeBaseState.ARCHIVED)
        active_id = active.id
        archived_id = archived.id

    watcher = VaultWatcher(
        factory,
        root,
        debounce=timedelta(milliseconds=50),
        reconcile_interval=timedelta(minutes=5),
        initial_reconcile=False,
    )
    results = watcher.reconcile_once(reason="periodic_reconciliation")

    assert [(result.knowledge_base_id, result.status) for result in results] == [
        (active_id, VaultScanEnqueueStatus.ENQUEUED)
    ]
    with factory() as session:
        jobs = session.scalars(select(IngestionJob)).all()
    assert {job.knowledge_base_id for job in jobs} == {active_id}
    assert archived_id not in {job.knowledge_base_id for job in jobs}
    assert jobs[0].checkpoint["reason"] == "periodic_reconciliation"


def test_missing_index_is_explicit_and_reconciliation_can_recover(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with factory.begin() as session:
        user, space, knowledge_base, _ = add_graph(session, "bootstrap", with_index=False)
        scope = scope_for_event(
            tmp_path,
            scoped_root(tmp_path, space, knowledge_base) / "note.md",
        )
        assert scope is not None
        missing = enqueue_vault_scan(
            session,
            scope,
            reason="watch_event",
            now=datetime(2026, 8, 29, tzinfo=UTC),
            bucket=timedelta(seconds=1),
        )
        assert session.scalar(select(func.count(IngestionJob.id))) == 0
        index = IndexVersion(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            version_number=1,
            state=IndexVersionState.BUILDING,
            parser_signature="watcher:parser:v1:" + "a" * 64,
            ocr_signature="watcher:ocr:v1:" + "b" * 64,
            chunking_signature="watcher:chunking:v1:" + "c" * 64,
            embedding_backend="hash",
            embedding_model="feature-hash-v1",
            embedding_dimension=8,
            embedding_contract_signature="watcher:embedding:v1:" + "d" * 64,
            index_signature="watcher:index:v1:bootstrap:" + "e" * 64,
            created_by_user_id=user.id,
        )
        session.add(index)
        session.flush()
        recovered = enqueue_vault_scan(
            session,
            scope,
            reason="periodic_reconciliation",
            now=datetime(2026, 8, 29, 0, 1, tzinfo=UTC),
            bucket=timedelta(seconds=1),
        )

    assert missing.status is VaultScanEnqueueStatus.MISSING_INDEX_VERSION
    assert missing.error_code == "vault_scan_index_unavailable"
    assert recovered.status is VaultScanEnqueueStatus.ENQUEUED


def test_invalid_outside_non_uuid_and_linked_scopes_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    assert scope_for_event(root, outside) is None

    invalid = root / "spaces" / "not-a-uuid" / str(uuid4()) / "note.md"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("invalid", encoding="utf-8")
    assert scope_for_event(root, invalid) is None

    outside_scope = tmp_path / "outside-scope"
    outside_scope.mkdir()
    linked_space = root / "spaces" / str(uuid4())
    linked_space.parent.mkdir(parents=True, exist_ok=True)
    replace_directory_with_link(linked_space, outside_scope)
    linked_event = linked_space / str(uuid4()) / "note.md"
    assert scope_for_event(root, linked_event) is None


def test_root_junction_is_rejected_even_when_target_is_a_valid_vault(tmp_path: Path) -> None:
    target_root = tmp_path / "target-vault"
    space_id = uuid4()
    knowledge_base_id = uuid4()
    target_scope = target_root / "spaces" / str(space_id) / str(knowledge_base_id)
    target_scope.mkdir(parents=True)
    event = target_scope / "note.md"
    event.write_text("secret", encoding="utf-8")

    linked_root = tmp_path / "vault"
    replace_directory_with_link(linked_root, target_root)

    assert (
        scope_for_event(
            linked_root,
            linked_root / "spaces" / str(space_id) / str(knowledge_base_id) / "note.md",
        )
        is None
    )


def test_cross_scope_descendant_junction_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    space_id = uuid4()
    source_knowledge_base_id = uuid4()
    target_knowledge_base_id = uuid4()
    source_scope = root / "spaces" / str(space_id) / str(source_knowledge_base_id)
    target_scope = root / "spaces" / str(space_id) / str(target_knowledge_base_id)
    source_scope.mkdir(parents=True)
    target_scope.mkdir(parents=True)
    secret = target_scope / "secret.md"
    secret.write_text("secret", encoding="utf-8")

    bridge = source_scope / "bridge"
    replace_directory_with_link(bridge, target_scope)

    assert scope_for_event(root, bridge / "secret.md") is None


def test_deleted_event_rejects_cross_scope_junction_in_existing_ancestor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vault"
    space_id = uuid4()
    source_knowledge_base_id = uuid4()
    target_knowledge_base_id = uuid4()
    source_scope = root / "spaces" / str(space_id) / str(source_knowledge_base_id)
    target_scope = root / "spaces" / str(space_id) / str(target_knowledge_base_id)
    source_scope.mkdir(parents=True)
    target_scope.mkdir(parents=True)

    bridge = source_scope / "bridge"
    replace_directory_with_link(bridge, target_scope)
    deleted_event = bridge / "already-deleted.md"
    assert not deleted_event.exists()

    assert scope_for_event(root, deleted_event) is None


def test_concurrent_watch_and_reconciliation_share_one_pending_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "concurrent-watcher.sqlite3"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    def configure_sqlite(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()

    event.listen(engine, "connect", configure_sqlite)
    Base.metadata.create_all(engine)
    concurrent_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with concurrent_factory.begin() as session:
            _, space, knowledge_base, _ = add_graph(session, "concurrent")
            scope = watcher_module.VaultScope(space.id, knowledge_base.id)
            knowledge_base_id = knowledge_base.id

        barrier = threading.Barrier(2)
        original_pending_scan_job = watcher_module._pending_scan_job
        barrier_calls = 0
        barrier_lock = threading.Lock()

        def synchronized_pending_scan_job(
            session: Session, candidate_scope: watcher_module.VaultScope
        ) -> IngestionJob | None:
            nonlocal barrier_calls
            pending = original_pending_scan_job(session, candidate_scope)
            with barrier_lock:
                barrier_calls += 1
                should_wait = barrier_calls <= 2
            if should_wait:
                barrier.wait(timeout=5)
            return pending

        monkeypatch.setattr(watcher_module, "_pending_scan_job", synchronized_pending_scan_job)
        results: list[object] = []
        errors: list[BaseException] = []
        connection_ids: list[int] = []
        result_lock = threading.Lock()

        def produce(reason: str, bucket: timedelta) -> None:
            try:
                with concurrent_factory.begin() as session:
                    connection_id = id(session.connection().connection.driver_connection)
                    result = enqueue_vault_scan(
                        session,
                        scope,
                        reason=reason,
                        now=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
                        bucket=bucket,
                    )
                with result_lock:
                    connection_ids.append(connection_id)
                    results.append(result)
            except BaseException as error:
                with result_lock:
                    errors.append(error)

        threads = [
            threading.Thread(target=produce, args=("watch_event", timedelta(seconds=1))),
            threading.Thread(
                target=produce,
                args=("periodic_reconciliation", timedelta(minutes=5)),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
        assert len(set(connection_ids)) == 2
        assert sorted(result.status for result in results) == [
            VaultScanEnqueueStatus.DEDUPLICATED,
            VaultScanEnqueueStatus.ENQUEUED,
        ]
        assert len({result.job_id for result in results}) == 1

        with concurrent_factory.begin() as session:
            pending_jobs = session.scalars(
                select(IngestionJob).where(
                    IngestionJob.knowledge_base_id == knowledge_base_id,
                    IngestionJob.state.in_(
                        (
                            IngestionJobState.QUEUED,
                            IngestionJobState.RUNNING,
                            IngestionJobState.RETRY_WAIT,
                        )
                    ),
                )
            ).all()
            assert len(pending_jobs) == 1
            completed_job_id = pending_jobs[0].id
            completed_at = datetime(2026, 8, 29, 12, 1, tzinfo=UTC)
            pending_jobs[0].state = IngestionJobState.COMPLETED
            pending_jobs[0].started_at = completed_at
            pending_jobs[0].completed_at = completed_at

        monkeypatch.setattr(watcher_module, "_pending_scan_job", original_pending_scan_job)
        with concurrent_factory.begin() as session:
            future = enqueue_vault_scan(
                session,
                scope,
                reason="periodic_reconciliation",
                now=datetime(2026, 8, 29, 12, 5, tzinfo=UTC),
                bucket=timedelta(minutes=5),
            )

        assert future.status is VaultScanEnqueueStatus.ENQUEUED
        assert future.job_id != completed_job_id
        with concurrent_factory() as session:
            jobs = session.scalars(
                select(IngestionJob)
                .where(IngestionJob.knowledge_base_id == knowledge_base_id)
                .order_by(IngestionJob.created_at, IngestionJob.id)
            ).all()
        assert len(jobs) == 2
        assert sum(job.state in watcher_module._PENDING_JOB_STATES for job in jobs) == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_transient_watch_failure_is_sanitized_and_does_not_kill_thread(
    factory: sessionmaker[Session], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    attempts = 0

    def flaky_watch(*paths: Path, **kwargs: object):
        nonlocal attempts
        del paths
        attempts += 1
        if attempts == 1:
            raise OSError("postgresql://user:secret@database/internal")
        stop_event = kwargs["stop_event"]
        assert isinstance(stop_event, threading.Event)
        while not stop_event.wait(0.01):
            yield set()

    stop_event = threading.Event()
    watcher = VaultWatcher(
        factory,
        tmp_path / "vault",
        debounce=timedelta(milliseconds=10),
        reconcile_interval=timedelta(hours=1),
        initial_reconcile=False,
        watch_factory=flaky_watch,
        retry_delay=timedelta(milliseconds=10),
    )
    thread = start_vault_watcher_thread(watcher, stop_event)
    deadline = time.monotonic() + 2
    while attempts < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert thread.is_alive()
    assert watcher.last_error_code == "vault_watch_unavailable"
    stop_event.set()
    thread.join(timeout=2)
    captured = capsys.readouterr().err
    assert "vault_watch_unavailable" in captured
    assert "secret" not in captured
    assert not thread.is_alive()


def test_enqueue_reuses_latest_nonterminal_index_and_ignores_terminal_versions(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with factory.begin() as session:
        user, space, knowledge_base, _ = add_graph(session, "latest")
        for version_number, state in (
            (2, IndexVersionState.READY),
            (3, IndexVersionState.FAILED),
            (4, IndexVersionState.RETIRED),
        ):
            session.add(
                IndexVersion(
                    space_id=space.id,
                    knowledge_base_id=knowledge_base.id,
                    version_number=version_number,
                    state=state,
                    parser_signature=f"watcher:parser:v{version_number}:" + "a" * 64,
                    ocr_signature=f"watcher:ocr:v{version_number}:" + "b" * 64,
                    chunking_signature=f"watcher:chunking:v{version_number}:" + "c" * 64,
                    embedding_backend="hash",
                    embedding_model="feature-hash-v1",
                    embedding_dimension=8,
                    embedding_contract_signature=(
                        f"watcher:embedding:v{version_number}:" + "d" * 64
                    ),
                    index_signature=f"watcher:index:v{version_number}:" + "e" * 64,
                    created_by_user_id=user.id,
                )
            )
        session.flush()
        expected = session.scalar(
            select(IndexVersion).where(
                IndexVersion.knowledge_base_id == knowledge_base.id,
                IndexVersion.version_number == 2,
            )
        )
        scope = scope_for_event(
            tmp_path,
            scoped_root(tmp_path, space, knowledge_base) / "latest.md",
        )
        assert scope is not None and expected is not None
        result = enqueue_vault_scan(
            session,
            scope,
            reason="watch_event",
            now=datetime(2026, 8, 29, tzinfo=UTC),
        )
        job = session.get(IngestionJob, result.job_id)

    assert result.status is VaultScanEnqueueStatus.ENQUEUED
    assert job is not None
    assert job.index_version_id == expected.id


def test_worker_main_starts_watcher_before_worker_and_joins_same_stop_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tutor_api.worker_main as worker_main
    from tutor_api.core.config import Settings

    order: list[str] = []
    captured: dict[str, object] = {}

    class FakeWatcher:
        def __init__(self, session_factory: object, root: Path, **kwargs: object) -> None:
            captured["session_factory"] = session_factory
            captured["root"] = root
            captured.update(kwargs)
            order.append("construct")

    class FakeThread:
        def join(self, timeout: float) -> None:
            captured["join_timeout"] = timeout
            order.append("join")

    def fake_start(watcher: object, stop_event: threading.Event) -> FakeThread:
        captured["watcher"] = watcher
        captured["stop_event"] = stop_event
        order.append("start")
        return FakeThread()

    def fake_worker(
        session_factory: object,
        handlers: object,
        *,
        config: object,
        should_stop: object,
        maintenance: object,
    ) -> None:
        del handlers, config
        assert callable(maintenance)
        assert session_factory is captured["session_factory"]
        assert callable(should_stop) and not should_stop()
        stop_event = captured["stop_event"]
        assert isinstance(stop_event, threading.Event)
        stop_event.set()
        assert should_stop()
        order.append("worker")

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite://",
        agent_vault_root="test-vault",
        agent_vault_watch_debounce_ms=75,
        agent_vault_reconcile_interval_seconds=40,
    )
    session_factory = object()
    monkeypatch.setattr(worker_main, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_main, "create_session_factory", lambda _: session_factory)
    monkeypatch.setattr(worker_main, "create_object_storage", lambda _: object())
    monkeypatch.setattr(worker_main, "create_handlers", lambda _, **__: {})
    monkeypatch.setattr(worker_main, "VaultWatcher", FakeWatcher)
    monkeypatch.setattr(worker_main, "start_vault_watcher_thread", fake_start)
    monkeypatch.setattr(worker_main, "run_worker_forever", fake_worker)
    monkeypatch.setattr(worker_main.signal, "signal", lambda *_: None)

    worker_main.main()

    assert order == ["construct", "start", "worker", "join"]
    assert captured["root"] == Path("test-vault")
    assert captured["debounce"] == timedelta(milliseconds=75)
    assert captured["reconcile_interval"] == timedelta(seconds=40)
    assert captured["join_timeout"] == 5


def test_transient_database_failure_is_sanitized_and_retried(
    factory: sessionmaker[Session], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with factory.begin() as session:
        _, _, knowledge_base, _ = add_graph(session, "db-retry")
        knowledge_base_id = knowledge_base.id

    class FlakyFactory:
        def __init__(self) -> None:
            self.calls = 0

        def begin(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("postgresql://user:secret@database/internal")
            return factory.begin()

    def timeout_watch(*paths: Path, **kwargs: object):
        del paths
        stop_event = kwargs["stop_event"]
        assert isinstance(stop_event, threading.Event)
        while not stop_event.wait(0.01):
            yield set()

    flaky_factory = FlakyFactory()
    stop_event = threading.Event()
    watcher = VaultWatcher(
        flaky_factory,  # type: ignore[arg-type]
        tmp_path / "vault",
        debounce=timedelta(milliseconds=10),
        reconcile_interval=timedelta(milliseconds=20),
        watch_factory=timeout_watch,
        retry_delay=timedelta(milliseconds=10),
    )
    thread = start_vault_watcher_thread(watcher, stop_event)
    try:
        job = wait_for_job(factory, knowledge_base_id)
        assert job.checkpoint["reason"] == "periodic_reconciliation"
        assert flaky_factory.calls >= 2
        assert thread.is_alive()
        assert watcher.last_error_code == "vault_reconciliation_unavailable"
    finally:
        stop_event.set()
        thread.join(timeout=2)
    captured = capsys.readouterr().err
    assert "vault_reconciliation_unavailable" in captured
    assert "secret" not in captured
    assert not thread.is_alive()
