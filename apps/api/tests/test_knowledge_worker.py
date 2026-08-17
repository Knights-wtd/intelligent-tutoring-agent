from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import (
    IndexVersion,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeBase,
)
from tutor_api.knowledge.worker import (
    WorkerConfig,
    claim_job_statement,
    claim_next_job,
    complete_job,
    fail_job,
    run_worker_once,
)
from tutor_api.spaces.models import Space, SpaceKind


@pytest.fixture
def factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    value = sessionmaker(bind=engine, expire_on_commit=False)
    yield value
    Base.metadata.drop_all(engine)
    engine.dispose()


def target(session: Session, suffix: str = "worker") -> tuple[User, KnowledgeBase, IndexVersion]:
    user = User(email=f"{suffix}@example.com", username=f"user-{suffix}", password_hash="h")
    session.add(user)
    session.flush()
    space = Space(owner_id=user.id, kind=SpaceKind.PERSONAL, name=suffix)
    session.add(space)
    session.flush()
    kb = KnowledgeBase(
        space_id=space.id, owner_user_id=user.id, created_by_user_id=user.id, name=suffix
    )
    session.add(kb)
    session.flush()
    index = IndexVersion(
        space_id=space.id,
        knowledge_base_id=kb.id,
        version_number=1,
        parser_signature="tutor:parser:v1:" + "a" * 64,
        ocr_signature="tutor:ocr:v1:" + "b" * 64,
        chunking_signature="tutor:chunking:v1:" + "c" * 64,
        embedding_backend="hash",
        embedding_model="feature-hash-v1",
        embedding_dimension=8,
        index_signature="tutor:index:v1:" + "d" * 64,
        created_by_user_id=user.id,
    )
    session.add(index)
    session.flush()
    return user, kb, index


def add_job(
    session: Session,
    user: User,
    kb: KnowledgeBase,
    index: IndexVersion,
    *,
    now: datetime,
    state: IngestionJobState = IngestionJobState.QUEUED,
    attempts: int = 0,
    maximum: int = 3,
    owner: str | None = None,
    expires: datetime | None = None,
    started: datetime | None = None,
) -> IngestionJob:
    job = IngestionJob(
        space_id=kb.space_id,
        knowledge_base_id=kb.id,
        index_version_id=index.id,
        kind=IngestionJobKind.BUILD_INDEX,
        state=state,
        idempotency_key=f"build:{uuid4()}",
        attempt_count=attempts,
        max_attempts=maximum,
        available_at=now,
        lease_owner=owner,
        lease_expires_at=expires,
        checkpoint={},
        created_by_user_id=user.id,
        started_at=started,
    )
    session.add(job)
    session.flush()
    return job


def test_postgresql_claim_contract_uses_for_update_skip_locked() -> None:
    sql = str(
        claim_job_statement(datetime(2026, 8, 17, tzinfo=UTC)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).upper()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert all(state in sql for state in ("QUEUED", "RETRY_WAIT", "RUNNING"))


def test_claim_leases_job_and_does_not_reclaim_live_lease(factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session)
        queued = add_job(session, user, kb, index, now=now)
    with factory.begin() as session:
        claimed = claim_next_job(
            session, worker_id="a", now=now, lease_duration=timedelta(seconds=30)
        )
        assert claimed and claimed.id == queued.id and claimed.state is IngestionJobState.RUNNING
        assert claimed.attempt_count == 1 and claimed.started_at == now
        assert claimed.lease_owner == "a" and claimed.lease_expires_at == now + timedelta(
            seconds=30
        )
    with factory.begin() as session:
        assert (
            claim_next_job(
                session,
                worker_id="b",
                now=now + timedelta(seconds=10),
                lease_duration=timedelta(seconds=30),
            )
            is None
        )


def test_stale_lease_recovers_but_live_lease_does_not(factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "stale")
        stale = add_job(
            session,
            user,
            kb,
            index,
            now=now - timedelta(minutes=2),
            state=IngestionJobState.RUNNING,
            attempts=1,
            owner="dead",
            expires=now - timedelta(seconds=1),
            started=now - timedelta(minutes=2),
        )
        add_job(
            session,
            user,
            kb,
            index,
            now=now - timedelta(minutes=2),
            state=IngestionJobState.RUNNING,
            attempts=1,
            owner="live",
            expires=now + timedelta(minutes=1),
            started=now - timedelta(minutes=2),
        )
    with factory.begin() as session:
        claimed = claim_next_job(
            session, worker_id="replacement", now=now, lease_duration=timedelta(seconds=30)
        )
        assert claimed and claimed.id == stale.id and claimed.attempt_count == 2
        assert claimed.lease_owner == "replacement"


def test_retry_is_bounded_and_error_detail_is_redacted(factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "retry")
        job = add_job(
            session,
            user,
            kb,
            index,
            now=now,
            state=IngestionJobState.RUNNING,
            attempts=1,
            maximum=2,
            owner="a",
            expires=now + timedelta(seconds=30),
            started=now,
        )
        fail_job(
            session,
            job_id=job.id,
            worker_id="a",
            now=now,
            error=RuntimeError("secret traceback /private"),
            retry_delay=timedelta(seconds=5),
        )
        assert job.state is IngestionJobState.RETRY_WAIT
        assert job.available_at == now + timedelta(seconds=5)
        assert job.last_error_code == "worker_unhandled_error" and job.last_error_detail is None
        assert job.lease_owner is None and job.lease_expires_at is None
    with factory.begin() as session:
        claimed = claim_next_job(
            session,
            worker_id="b",
            now=now + timedelta(seconds=5),
            lease_duration=timedelta(seconds=30),
        )
        assert claimed and claimed.attempt_count == 2
        fail_job(
            session,
            job_id=claimed.id,
            worker_id="b",
            now=now + timedelta(seconds=6),
            error=RuntimeError("secret"),
            retry_delay=timedelta(seconds=5),
        )
        assert claimed.state is IngestionJobState.FAILED
        assert claimed.completed_at == now + timedelta(seconds=6)
        assert claimed.attempt_count == claimed.max_attempts and claimed.last_error_detail is None


def test_restart_after_commit_does_not_duplicate_side_effect(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "restart")
        job = add_job(session, user, kb, index, now=now)
    calls: list[str] = []

    def handler(session: Session, claimed: IngestionJob) -> None:
        if claimed.checkpoint.get("effect_done"):
            return
        calls.append(str(claimed.id))
        claimed.checkpoint["effect_done"] = True

    config = WorkerConfig(
        worker_id="restart-worker",
        lease_duration=timedelta(seconds=30),
        retry_delay=timedelta(seconds=1),
    )
    assert run_worker_once(factory, {IngestionJobKind.BUILD_INDEX: handler}, config=config, now=now)
    assert not run_worker_once(
        factory,
        {IngestionJobKind.BUILD_INDEX: handler},
        config=config,
        now=now + timedelta(seconds=1),
    )
    with factory() as session:
        persisted = session.get(IngestionJob, job.id)
        assert persisted and persisted.state is IngestionJobState.COMPLETED
        assert persisted.checkpoint == {"effect_done": True}
        assert persisted.lease_owner is None and persisted.lease_expires_at is None
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1
    assert calls == [str(job.id)]


def test_compose_worker_reuses_api_image_without_ports_or_root() -> None:
    from pathlib import Path

    import yaml

    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "compose.yaml").read_text(encoding="utf-8")
    )
    api = compose["services"]["api"]
    worker = compose["services"]["worker"]
    assert worker["image"] == api["image"]
    assert worker["build"] == api["build"]
    assert worker["environment"] == api["environment"]
    assert worker["command"] == ["python", "-m", "tutor_api.worker_main"]
    assert "ports" not in worker
    assert worker.get("user") not in {"root", "0", 0}


def test_completion_refreshes_lease_owner_before_committing(
    factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory.begin() as session:
        user, kb, index = target(session, "lease-race")
        job = add_job(
            session,
            user,
            kb,
            index,
            now=now,
            state=IngestionJobState.RUNNING,
            attempts=1,
            owner="original",
            expires=now + timedelta(seconds=30),
            started=now,
        )
        session.get(IngestionJob, job.id)
        session.execute(
            update(IngestionJob).where(IngestionJob.id == job.id).values(lease_owner="replacement"),
            execution_options={"synchronize_session": False},
        )

        with pytest.raises(RuntimeError, match="worker_lease_lost"):
            complete_job(
                session,
                job_id=job.id,
                worker_id="original",
                now=now + timedelta(seconds=1),
            )

        session.expire_all()
        persisted = session.get(IngestionJob, job.id)
        assert persisted and persisted.state is IngestionJobState.RUNNING
        assert persisted.lease_owner == "replacement"
