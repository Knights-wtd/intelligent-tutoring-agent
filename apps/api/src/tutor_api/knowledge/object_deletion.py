"""Reliable object-storage cleanup for knowledge-base deletion outbox rows."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.knowledge.models import ObjectDeletionOutbox, ObjectDeletionState
from tutor_api.knowledge.storage import ObjectStorage

_VAULT_SCOPE_PREFIX = "local-vault-scope:"


def build_vault_scope_deletion_key(space_id: UUID, knowledge_base_id: UUID) -> str:
    """Encode a server-owned Vault scope for the durable deletion outbox."""

    return f"{_VAULT_SCOPE_PREFIX}{space_id}/{knowledge_base_id}"


def _vault_scope_ids(object_key: str) -> tuple[UUID, UUID] | None:
    if not object_key.startswith(_VAULT_SCOPE_PREFIX):
        return None
    raw = object_key.removeprefix(_VAULT_SCOPE_PREFIX)
    parts = raw.split("/")
    if len(parts) != 2:
        raise ValueError("vault_scope_deletion_key_invalid")
    try:
        return UUID(parts[0]), UUID(parts[1])
    except ValueError as error:
        raise ValueError("vault_scope_deletion_key_invalid") from error


def _delete_vault_scope(vault_root: Path, *, space_id: UUID, knowledge_base_id: UUID) -> None:
    root = Path(vault_root).resolve()
    raw_scope = root / "spaces" / str(space_id) / str(knowledge_base_id)
    try:
        raw_scope.parent.resolve().relative_to(root)
    except ValueError as error:
        raise RuntimeError("vault_scope_outside_root") from error

    if raw_scope.is_symlink():
        raw_scope.unlink(missing_ok=True)
        return

    scope = raw_scope.resolve()
    try:
        scope.relative_to(root)
    except ValueError as error:
        raise RuntimeError("vault_scope_outside_root") from error
    if scope.exists():
        shutil.rmtree(scope)


def _claim_next(
    session: Session,
    *,
    worker_id: str,
    now: datetime,
    lease_duration: timedelta,
) -> ObjectDeletionOutbox | None:
    runnable = or_(
        ObjectDeletionOutbox.state == ObjectDeletionState.PENDING,
        and_(
            ObjectDeletionOutbox.state == ObjectDeletionState.RETRY_WAIT,
            ObjectDeletionOutbox.available_at <= now,
        ),
    )
    stale = and_(
        ObjectDeletionOutbox.state == ObjectDeletionState.RUNNING,
        ObjectDeletionOutbox.lease_expires_at <= now,
    )
    item = session.scalar(
        select(ObjectDeletionOutbox)
        .where(or_(runnable, stale))
        .order_by(ObjectDeletionOutbox.created_at, ObjectDeletionOutbox.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if item is None:
        return None
    item.state = ObjectDeletionState.RUNNING
    item.attempt_count += 1
    item.lease_owner = worker_id
    item.lease_expires_at = now + lease_duration
    item.completed_at = None
    session.flush()
    return item


def _owned_item(
    session: Session, item_id: UUID, worker_id: str
) -> ObjectDeletionOutbox:
    item = session.scalar(
        select(ObjectDeletionOutbox)
        .where(ObjectDeletionOutbox.id == item_id)
        .with_for_update()
    )
    if (
        item is None
        or item.state != ObjectDeletionState.RUNNING
        or item.lease_owner != worker_id
    ):
        raise RuntimeError("object_deletion_lease_lost")
    return item


def run_object_deletion_once(
    session_factory: sessionmaker[Session],
    object_storage: ObjectStorage,
    *,
    worker_id: str,
    lease_duration: timedelta = timedelta(minutes=5),
    retry_delay: timedelta = timedelta(seconds=30),
    now: datetime | None = None,
    vault_root: Path | None = None,
) -> bool:
    """Claim one row, delete outside database transactions, then persist outcome."""

    if not worker_id or len(worker_id) > 255:
        raise ValueError("worker_id must be between 1 and 255 characters")
    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be positive")
    if retry_delay < timedelta(0):
        raise ValueError("retry_delay must not be negative")
    timestamp = now or datetime.now(UTC)
    with session_factory.begin() as session:
        claimed = _claim_next(
            session,
            worker_id=worker_id,
            now=timestamp,
            lease_duration=lease_duration,
        )
        if claimed is None:
            return False
        item_id = claimed.id
        object_key = claimed.object_key

    vault_scope = _vault_scope_ids(object_key)
    try:
        if vault_scope is None:
            object_storage.delete_object(object_key)
        else:
            if vault_root is None:
                raise RuntimeError("vault_root_unavailable")
            _delete_vault_scope(
                vault_root,
                space_id=vault_scope[0],
                knowledge_base_id=vault_scope[1],
            )
    except Exception:
        with session_factory.begin() as session:
            try:
                item = _owned_item(session, item_id, worker_id)
            except RuntimeError as lease_error:
                if str(lease_error) != "object_deletion_lease_lost":
                    raise
                return True
            item.state = ObjectDeletionState.RETRY_WAIT
            item.available_at = timestamp + retry_delay
            item.lease_owner = None
            item.lease_expires_at = None
            item.last_error_code = (
                "object_storage_request_failed"
                if vault_scope is None
                else "vault_scope_delete_failed"
            )
            item.completed_at = None
            session.flush()
        return True

    with session_factory.begin() as session:
        try:
            item = _owned_item(session, item_id, worker_id)
        except RuntimeError as lease_error:
            if str(lease_error) != "object_deletion_lease_lost":
                raise
            return True
        item.state = ObjectDeletionState.COMPLETED
        item.lease_owner = None
        item.lease_expires_at = None
        item.last_error_code = None
        item.completed_at = timestamp
        session.flush()
    return True
