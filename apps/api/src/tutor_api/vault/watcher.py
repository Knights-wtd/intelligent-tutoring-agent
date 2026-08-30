"""Production Vault filesystem watcher and durable reconciliation producer."""

from __future__ import annotations

import re
import stat
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from watchfiles import watch

from tutor_api.knowledge.models import (
    IndexVersion,
    IndexVersionState,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeBase,
    KnowledgeBaseState,
)
from tutor_api.knowledge.worker import DurableJobKind

_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PENDING_JOB_STATES = (
    IngestionJobState.QUEUED,
    IngestionJobState.RUNNING,
    IngestionJobState.RETRY_WAIT,
)
_REUSABLE_INDEX_STATES = (
    IndexVersionState.BUILDING,
    IndexVersionState.READY,
    IndexVersionState.ACTIVE,
)
_SCAN_RESERVATION_KEY = "vault-scan:pending"
_SCAN_TERMINAL_KEY_PREFIX = "vault-scan:terminal"


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...


WatchFactory = Callable[..., Iterator[set[tuple[object, str]]]]


@dataclass(frozen=True)
class VaultScope:
    space_id: UUID
    knowledge_base_id: UUID


class VaultScanEnqueueStatus(StrEnum):
    ENQUEUED = "enqueued"
    DEDUPLICATED = "deduplicated"
    MISSING_INDEX_VERSION = "missing_index_version"
    INACTIVE_SCOPE = "inactive_scope"


@dataclass(frozen=True)
class VaultScanEnqueueResult:
    space_id: UUID
    knowledge_base_id: UUID
    status: VaultScanEnqueueStatus
    job_id: UUID | None = None
    error_code: str | None = None


def _canonical_uuid(raw: str) -> UUID | None:
    try:
        value = UUID(raw)
    except ValueError:
        return None
    return value if str(value) == raw else None


def _is_link_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _has_linked_existing_component(root: Path, candidate: Path) -> bool:
    """Reject every existing reparse component, including a deleted event's ancestors."""

    current = root
    if _is_link_or_junction(current):
        return True
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    for part in relative.parts:
        current = current / part
        if _is_link_or_junction(current):
            return True
        try:
            current.lstat()
        except FileNotFoundError:
            break
        except OSError:
            return True
    return False


def scope_for_event(vault_root: Path, event_path: Path | str) -> VaultScope | None:
    """Map one watchfiles path to a canonical, non-linked Vault KB scope."""

    root = Path(vault_root).absolute()
    if not root.is_dir() or _is_link_or_junction(root):
        return None
    candidate = Path(event_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 3 or parts[0] != "spaces":
        return None
    space_id = _canonical_uuid(parts[1])
    knowledge_base_id = _canonical_uuid(parts[2])
    if space_id is None or knowledge_base_id is None:
        return None
    if _has_linked_existing_component(root, candidate):
        return None

    spaces_root = root / "spaces"
    space_root = spaces_root / parts[1]
    scope_root = space_root / parts[2]
    try:
        resolved_root = root.resolve(strict=True)
        resolved_scope = scope_root.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
    except OSError:
        return None
    expected_scope = resolved_root / "spaces" / parts[1] / parts[2]
    if resolved_scope != expected_scope:
        return None
    if not _is_within(resolved_candidate, resolved_scope):
        return None
    return VaultScope(space_id=space_id, knowledge_base_id=knowledge_base_id)


def _pending_scan_job(session: Session, scope: VaultScope) -> IngestionJob | None:
    candidates = session.scalars(
        select(IngestionJob)
        .where(
            IngestionJob.space_id == scope.space_id,
            IngestionJob.knowledge_base_id == scope.knowledge_base_id,
            IngestionJob.kind == IngestionJobKind.BUILD_INDEX,
            IngestionJob.state.in_(_PENDING_JOB_STATES),
        )
        .order_by(IngestionJob.created_at.desc())
    )
    return next(
        (
            job
            for job in candidates
            if job.checkpoint.get("worker_job_kind") == DurableJobKind.VAULT_SCAN.value
        ),
        None,
    )


def _scan_reservation_job(session: Session, scope: VaultScope) -> IngestionJob | None:
    return session.scalar(
        select(IngestionJob).where(
            IngestionJob.knowledge_base_id == scope.knowledge_base_id,
            IngestionJob.idempotency_key == _SCAN_RESERVATION_KEY,
        )
    )


def _release_terminal_scan_reservation(session: Session, reservation: IngestionJob) -> None:
    if reservation.state in _PENDING_JOB_STATES:
        return
    reservation.idempotency_key = f"{_SCAN_TERMINAL_KEY_PREFIX}:{reservation.id}"
    session.flush()


def _reusable_index(session: Session, scope: VaultScope) -> IndexVersion | None:
    return session.scalar(
        select(IndexVersion)
        .where(
            IndexVersion.space_id == scope.space_id,
            IndexVersion.knowledge_base_id == scope.knowledge_base_id,
            IndexVersion.state.in_(_REUSABLE_INDEX_STATES),
        )
        .order_by(IndexVersion.version_number.desc(), IndexVersion.created_at.desc())
        .limit(1)
    )


def enqueue_vault_scan(
    session: Session,
    scope: VaultScope,
    *,
    reason: str,
    now: datetime | None = None,
    bucket: timedelta = timedelta(seconds=1),
) -> VaultScanEnqueueResult:
    """Enqueue or reuse one durable full scan without inventing an index target."""

    if _REASON.fullmatch(reason) is None:
        raise ValueError("vault scan reason must be a safe identifier")
    bucket_seconds = bucket.total_seconds()
    if bucket_seconds <= 0:
        raise ValueError("vault scan bucket must be positive")
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    knowledge_base = session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == scope.knowledge_base_id,
            KnowledgeBase.space_id == scope.space_id,
            KnowledgeBase.state == KnowledgeBaseState.ACTIVE,
        )
    )
    if knowledge_base is None:
        return VaultScanEnqueueResult(
            scope.space_id,
            scope.knowledge_base_id,
            VaultScanEnqueueStatus.INACTIVE_SCOPE,
            error_code="vault_scope_inactive",
        )

    reservation = _scan_reservation_job(session, scope)
    if reservation is not None and reservation.state in _PENDING_JOB_STATES:
        return VaultScanEnqueueResult(
            scope.space_id,
            scope.knowledge_base_id,
            VaultScanEnqueueStatus.DEDUPLICATED,
            job_id=reservation.id,
        )
    if reservation is not None:
        _release_terminal_scan_reservation(session, reservation)

    pending = _pending_scan_job(session, scope)
    if pending is not None:
        return VaultScanEnqueueResult(
            scope.space_id,
            scope.knowledge_base_id,
            VaultScanEnqueueStatus.DEDUPLICATED,
            job_id=pending.id,
        )

    index = _reusable_index(session, scope)
    if index is None:
        return VaultScanEnqueueResult(
            scope.space_id,
            scope.knowledge_base_id,
            VaultScanEnqueueStatus.MISSING_INDEX_VERSION,
            error_code="vault_scan_index_unavailable",
        )

    job = IngestionJob(
        space_id=scope.space_id,
        knowledge_base_id=scope.knowledge_base_id,
        index_version_id=index.id,
        kind=IngestionJobKind.BUILD_INDEX,
        state=IngestionJobState.QUEUED,
        idempotency_key=_SCAN_RESERVATION_KEY,
        available_at=timestamp,
        checkpoint={
            "worker_job_kind": DurableJobKind.VAULT_SCAN.value,
            "force_full_scan": True,
            "reason": reason,
            "producer": "vault_watcher",
        },
        created_by_user_id=knowledge_base.created_by_user_id,
    )
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(IngestionJob).where(
                IngestionJob.knowledge_base_id == scope.knowledge_base_id,
                IngestionJob.idempotency_key == _SCAN_RESERVATION_KEY,
            )
        )
        if existing is None:
            raise
        return VaultScanEnqueueResult(
            scope.space_id,
            scope.knowledge_base_id,
            VaultScanEnqueueStatus.DEDUPLICATED,
            job_id=existing.id,
        )
    return VaultScanEnqueueResult(
        scope.space_id,
        scope.knowledge_base_id,
        VaultScanEnqueueStatus.ENQUEUED,
        job_id=job.id,
    )


class VaultWatcher:
    """Watch AGENT_VAULT_ROOT and periodically reconcile all active KBs."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        vault_root: Path,
        *,
        debounce: timedelta,
        reconcile_interval: timedelta,
        initial_reconcile: bool = True,
        force_polling: bool | None = None,
        watch_factory: WatchFactory = watch,
        retry_delay: timedelta = timedelta(seconds=5),
    ) -> None:
        if debounce <= timedelta(0):
            raise ValueError("debounce must be positive")
        if reconcile_interval <= timedelta(0):
            raise ValueError("reconcile_interval must be positive")
        if retry_delay < timedelta(0):
            raise ValueError("retry_delay must not be negative")
        self.session_factory = session_factory
        self.root = Path(vault_root).absolute()
        self.debounce = debounce
        self.reconcile_interval = reconcile_interval
        self.initial_reconcile = initial_reconcile
        self.force_polling = force_polling
        self.watch_factory = watch_factory
        self.retry_delay = retry_delay
        self.started = threading.Event()
        self.last_error_code: str | None = None

    def _record_error(self, code: str, error: BaseException | None = None) -> None:
        self.last_error_code = code
        detail = f" ({type(error).__name__})" if error is not None else ""
        print(f"[vault-watcher] {code}{detail}", file=sys.stderr, flush=True)

    def _record_results(self, results: Iterable[VaultScanEnqueueResult]) -> None:
        for result in results:
            if result.error_code is not None:
                self._record_error(result.error_code)

    def enqueue_paths(
        self, paths: Iterable[Path | str], *, reason: str = "watch_event"
    ) -> tuple[VaultScanEnqueueResult, ...]:
        scopes = {
            scope for path in paths if (scope := scope_for_event(self.root, path)) is not None
        }
        if not scopes:
            return ()
        with self.session_factory.begin() as session:
            results = tuple(
                enqueue_vault_scan(
                    session,
                    scope,
                    reason=reason,
                    bucket=max(self.debounce, timedelta(seconds=1)),
                )
                for scope in sorted(
                    scopes,
                    key=lambda item: (str(item.space_id), str(item.knowledge_base_id)),
                )
            )
        self._record_results(results)
        return results

    def reconcile_once(
        self, *, reason: str = "periodic_reconciliation"
    ) -> tuple[VaultScanEnqueueResult, ...]:
        with self.session_factory.begin() as session:
            knowledge_bases = session.scalars(
                select(KnowledgeBase)
                .where(KnowledgeBase.state == KnowledgeBaseState.ACTIVE)
                .order_by(KnowledgeBase.id)
            ).all()
            results = tuple(
                enqueue_vault_scan(
                    session,
                    VaultScope(
                        space_id=knowledge_base.space_id,
                        knowledge_base_id=knowledge_base.id,
                    ),
                    reason=reason,
                    bucket=max(self.reconcile_interval, timedelta(seconds=1)),
                )
                for knowledge_base in knowledge_bases
            )
        self._record_results(results)
        return results

    def _safe_reconcile(self, reason: str) -> None:
        try:
            self.reconcile_once(reason=reason)
        except Exception as error:
            self._record_error("vault_reconciliation_unavailable", error)

    def _safe_enqueue_paths(self, paths: Iterable[Path | str]) -> None:
        try:
            self.enqueue_paths(paths)
        except Exception as error:
            self._record_error("vault_queue_unavailable", error)

    def run(self, stop_event: StopEvent) -> None:
        next_reconcile = time.monotonic()
        if not self.initial_reconcile:
            next_reconcile += self.reconcile_interval.total_seconds()
        while not stop_event.is_set():
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                if self.initial_reconcile and next_reconcile <= time.monotonic():
                    self._safe_reconcile("startup_reconciliation")
                    next_reconcile = time.monotonic() + self.reconcile_interval.total_seconds()
                self.started.set()
                timeout_ms = max(
                    100,
                    min(1000, int(self.reconcile_interval.total_seconds() * 1000)),
                )
                for changes in self.watch_factory(
                    self.root,
                    debounce=max(1, int(self.debounce.total_seconds() * 1000)),
                    step=max(1, min(50, int(self.debounce.total_seconds() * 500))),
                    stop_event=stop_event,
                    rust_timeout=timeout_ms,
                    yield_on_timeout=True,
                    force_polling=self.force_polling,
                    ignore_permission_denied=True,
                    raise_interrupt=False,
                ):
                    if stop_event.is_set():
                        break
                    if changes:
                        self._safe_enqueue_paths(change[1] for change in changes)
                    if time.monotonic() >= next_reconcile:
                        self._safe_reconcile("periodic_reconciliation")
                        next_reconcile = time.monotonic() + self.reconcile_interval.total_seconds()
                if not stop_event.is_set():
                    self._record_error("vault_watch_stopped")
            except Exception as error:
                self._record_error("vault_watch_unavailable", error)
            if not stop_event.is_set():
                stop_event.wait(self.retry_delay.total_seconds())


def start_vault_watcher_thread(watcher: VaultWatcher, stop_event: StopEvent) -> threading.Thread:
    thread = threading.Thread(
        target=watcher.run,
        args=(stop_event,),
        name="vault-watcher",
        daemon=True,
    )
    thread.start()
    return thread
