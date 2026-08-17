"""Database-leased ingestion worker primitives."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.knowledge.indexing import (
    ChunkingConfig,
    EmbeddingAdapter,
    IndexBuildRequest,
    IndexingError,
    build_index,
)
from tutor_api.knowledge.models import (
    IndexVersion,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
)

JobHandler = Callable[[Session, IngestionJob], None]
_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class CodedWorkerError(Protocol):
    code: object


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    worker_id: str
    lease_duration: timedelta = timedelta(minutes=5)
    retry_delay: timedelta = timedelta(seconds=30)
    idle_sleep_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not self.worker_id or len(self.worker_id) > 255:
            raise ValueError("worker_id must be between 1 and 255 characters")
        if self.lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if self.retry_delay < timedelta(0):
            raise ValueError("retry_delay must not be negative")
        if self.idle_sleep_seconds < 0:
            raise ValueError("idle_sleep_seconds must not be negative")


def claim_job_statement(now: datetime):
    runnable = and_(
        IngestionJob.state.in_((IngestionJobState.QUEUED, IngestionJobState.RETRY_WAIT)),
        IngestionJob.available_at <= now,
    )
    stale = and_(
        IngestionJob.state == IngestionJobState.RUNNING,
        IngestionJob.lease_expires_at <= now,
    )
    return (
        select(IngestionJob)
        .where(
            or_(runnable, stale),
            IngestionJob.attempt_count < IngestionJob.max_attempts,
        )
        .order_by(IngestionJob.available_at, IngestionJob.created_at, IngestionJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _fail_exhausted_stale_jobs(session: Session, now: datetime) -> None:
    session.execute(
        update(IngestionJob)
        .where(
            IngestionJob.state == IngestionJobState.RUNNING,
            IngestionJob.lease_expires_at <= now,
            IngestionJob.attempt_count >= IngestionJob.max_attempts,
        )
        .values(
            state=IngestionJobState.FAILED,
            lease_owner=None,
            lease_expires_at=None,
            completed_at=now,
            last_error_code="worker_lease_exhausted",
            last_error_detail=None,
        )
    )


def claim_next_job(
    session: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_duration: timedelta = timedelta(minutes=5),
) -> IngestionJob | None:
    """Atomically lease one runnable job; SQLite is a single-worker test fallback only."""

    if not worker_id or len(worker_id) > 255:
        raise ValueError("worker_id must be between 1 and 255 characters")
    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be positive")
    timestamp = now or datetime.now(UTC)
    _fail_exhausted_stale_jobs(session, timestamp)
    job = session.scalar(claim_job_statement(timestamp))
    if job is None:
        return None
    job.state = IngestionJobState.RUNNING
    job.attempt_count += 1
    job.lease_owner = worker_id
    job.lease_expires_at = timestamp + lease_duration
    if job.started_at is None:
        job.started_at = timestamp
    job.completed_at = None
    session.flush()
    return job


def _owned_running_job(session: Session, job_id: UUID, worker_id: str) -> IngestionJob:
    job = session.scalar(
        select(IngestionJob)
        .where(IngestionJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None or job.state is not IngestionJobState.RUNNING or job.lease_owner != worker_id:
        raise RuntimeError("worker_lease_lost")
    return job


def complete_job(
    session: Session,
    *,
    job_id: UUID,
    worker_id: str,
    now: datetime | None = None,
) -> IngestionJob:
    timestamp = now or datetime.now(UTC)
    job = _owned_running_job(session, job_id, worker_id)
    job.state = IngestionJobState.COMPLETED
    job.lease_owner = None
    job.lease_expires_at = None
    job.completed_at = timestamp
    job.last_error_code = None
    job.last_error_detail = None
    session.flush()
    return job


def _public_error_code(error: Exception) -> str:
    raw = getattr(error, "code", None)
    if hasattr(raw, "value"):
        raw = raw.value
    if isinstance(raw, str):
        normalized = raw.strip().casefold()
        if _SAFE_ERROR_CODE.fullmatch(normalized):
            return normalized
    return "worker_unhandled_error"


def fail_job(
    session: Session,
    *,
    job_id: UUID,
    worker_id: str,
    error: Exception,
    retry_delay: timedelta = timedelta(seconds=30),
    now: datetime | None = None,
) -> IngestionJob:
    if retry_delay < timedelta(0):
        raise ValueError("retry_delay must not be negative")
    timestamp = now or datetime.now(UTC)
    job = _owned_running_job(session, job_id, worker_id)
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error_code = _public_error_code(error)
    job.last_error_detail = None
    if job.attempt_count < job.max_attempts:
        job.state = IngestionJobState.RETRY_WAIT
        job.available_at = timestamp + retry_delay
        job.completed_at = None
    else:
        job.state = IngestionJobState.FAILED
        job.completed_at = timestamp
    session.flush()
    return job


def make_build_index_handler(adapter: EmbeddingAdapter) -> JobHandler:
    """Create the idempotent BUILD_INDEX handler used by the process entrypoint."""

    def handle(session: Session, job: IngestionJob) -> None:
        if job.kind is not IngestionJobKind.BUILD_INDEX or job.index_version_id is None:
            raise IndexingError("index_job_target_invalid")
        index = session.get(IndexVersion, job.index_version_id)
        if index is None:
            raise IndexingError("index_job_target_invalid")
        checkpoint = job.checkpoint
        raw_version_ids = checkpoint.get("document_version_ids")
        try:
            version_ids = tuple(UUID(value) for value in raw_version_ids)
            chunking = ChunkingConfig(
                max_chars=checkpoint["chunk_max_chars"],
                overlap_chars=checkpoint["chunk_overlap_chars"],
            )
            parser_signature = checkpoint["parser_signature"]
            ocr_signature = checkpoint["ocr_signature"]
        except (KeyError, TypeError, ValueError):
            raise IndexingError("index_job_checkpoint_invalid") from None
        if not isinstance(parser_signature, str) or not isinstance(ocr_signature, str):
            raise IndexingError("index_job_checkpoint_invalid")
        request = IndexBuildRequest(
            space_id=job.space_id,
            knowledge_base_id=job.knowledge_base_id,
            created_by_user_id=index.created_by_user_id,
            document_version_ids=version_ids,
            parser_signature=parser_signature,
            ocr_signature=ocr_signature,
            chunking=chunking,
        )
        result = build_index(session, request, adapter)
        if result.index_version_id != index.id:
            raise IndexingError("index_job_signature_mismatch")
        job.checkpoint["chunk_count"] = result.chunk_count
        job.checkpoint["index_version_id"] = str(result.index_version_id)

    return handle


def run_worker_once(
    session_factory: sessionmaker[Session],
    handlers: Mapping[IngestionJobKind, JobHandler],
    *,
    config: WorkerConfig,
    now: datetime | None = None,
) -> bool:
    """Claim in one transaction and execute in a fresh worker-owned Session."""

    timestamp = now or datetime.now(UTC)
    with session_factory.begin() as session:
        claimed = claim_next_job(
            session,
            worker_id=config.worker_id,
            now=timestamp,
            lease_duration=config.lease_duration,
        )
        if claimed is None:
            return False
        job_id = claimed.id
        kind = claimed.kind

    try:
        with session_factory.begin() as session:
            job = _owned_running_job(session, job_id, config.worker_id)
            handler = handlers.get(kind)
            if handler is None:
                raise RuntimeError("worker_handler_missing")
            handler(session, job)
            complete_job(
                session,
                job_id=job_id,
                worker_id=config.worker_id,
                now=timestamp,
            )
    except Exception as error:
        with session_factory.begin() as session:
            try:
                fail_job(
                    session,
                    job_id=job_id,
                    worker_id=config.worker_id,
                    error=error,
                    retry_delay=config.retry_delay,
                    now=timestamp,
                )
            except RuntimeError as lease_error:
                if str(lease_error) != "worker_lease_lost":
                    raise
        return True
    return True


def run_worker_forever(
    session_factory: sessionmaker[Session],
    handlers: Mapping[IngestionJobKind, JobHandler],
    *,
    config: WorkerConfig,
    should_stop: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    stop = should_stop or (lambda: False)
    while not stop():
        worked = run_worker_once(session_factory, handlers, config=config)
        if not worked and not stop():
            sleep(config.idle_sleep_seconds)
