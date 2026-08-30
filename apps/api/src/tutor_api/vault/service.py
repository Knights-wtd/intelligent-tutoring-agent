from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tutor_api.vault.models import (
    VaultChangeEntry,
    VaultChangeOperation,
    VaultChangeSet,
    VaultChangeSetState,
    VaultChangeSource,
    VaultFile,
    VaultFileKind,
    VaultSyncState,
)
from tutor_api.vault.storage import VaultConflictError, VaultStorage, normalize_relative_path


@dataclass(frozen=True)
class VaultResult:
    vault_file_id: UUID
    relative_path: str
    before_hash: str | None
    after_hash: str | None
    revision: int
    change_set_id: UUID
    size_bytes: int
    sync_state: str
    is_tombstoned: bool = False

    @property
    def content_hash(self) -> str | None:
        return self.after_hash if self.after_hash is not None else self.before_hash


@dataclass(frozen=True)
class ReconcileResult:
    markdown: str
    conflict_revision: Any | None
    vault_revision: Any | None
    change_set_id: UUID | None


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _bytes(content: str | bytes) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else content


class VaultService:
    def __init__(
        self,
        db: Session,
        vault_root: Path,
        *,
        space_id: UUID,
        knowledge_base_id: UUID,
        actor_user_id: UUID | None = None,
    ) -> None:
        self.db = db
        self.space_id = space_id
        self.knowledge_base_id = knowledge_base_id
        self.actor_user_id = actor_user_id
        self.storage = VaultStorage(
            Path(vault_root) / "spaces" / str(space_id) / str(knowledge_base_id)
        )

    def _file(self, path: str, *, include_tombstone: bool = False) -> VaultFile | None:
        normalized = normalize_relative_path(path)
        row = self.db.scalar(
            select(VaultFile).where(
                VaultFile.knowledge_base_id == self.knowledge_base_id,
                VaultFile.relative_path == normalized,
            )
        )
        return row if include_tombstone or row is None or not row.is_tombstoned else None

    def get_file(self, file_id: UUID, *, include_tombstone: bool = True) -> VaultFile:
        row = self.db.scalar(
            select(VaultFile).where(
                VaultFile.id == file_id,
                VaultFile.knowledge_base_id == self.knowledge_base_id,
                VaultFile.space_id == self.space_id,
            )
        )
        if row is None or (row.is_tombstoned and not include_tombstone):
            raise KeyError("vault_file_not_found")
        return row

    def _resolve_file(
        self, identifier: UUID | str, *, include_tombstone: bool = False
    ) -> VaultFile:
        if isinstance(identifier, UUID):
            return self.get_file(identifier, include_tombstone=include_tombstone)
        row = self._file(identifier, include_tombstone=include_tombstone)
        if row is None:
            raise KeyError("vault_file_not_found")
        return row

    def list(self, *, include_tombstones: bool = False) -> list[VaultFile]:
        statement = select(VaultFile).where(
            VaultFile.knowledge_base_id == self.knowledge_base_id,
            VaultFile.space_id == self.space_id,
        )
        if not include_tombstones:
            statement = statement.where(VaultFile.is_tombstoned.is_(False))
        return list(self.db.scalars(statement.order_by(VaultFile.relative_path)))

    def read(self, identifier: UUID | str) -> tuple[VaultFile, bytes]:
        row = self._resolve_file(identifier)
        content = self.storage.read_bytes(row.relative_path)
        actual_hash = _hash(content)
        if actual_hash != row.content_hash:
            row.sync_state = VaultSyncState.CONFLICT
            raise VaultConflictError("vault_hash_conflict", actual_hash=actual_hash)
        return row, content

    def external_write(self, path: str, content: str | bytes) -> Path:
        """Write as an external editor would, without changing the database projection."""
        return self.storage.atomic_write(path, _bytes(content))

    def _change(
        self,
        row: VaultFile,
        operation: VaultChangeOperation,
        *,
        before_path: str | None,
        after_path: str | None,
        before_hash: str | None,
        after_hash: str | None,
        before_size: int,
        after_size: int,
        source: VaultChangeSource,
        session_id: UUID | None = None,
        turn_id: UUID | None = None,
        tool_call_id: str | None = None,
    ) -> VaultChangeSet:
        change = VaultChangeSet(
            space_id=self.space_id,
            knowledge_base_id=self.knowledge_base_id,
            source=source,
            state=VaultChangeSetState.COMMITTED,
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            before_snapshot_hash=before_hash,
            after_snapshot_hash=after_hash,
            committed_at=datetime.now(UTC),
        )
        self.db.add(change)
        self.db.flush()
        details: dict[str, Any] = {"source": source.value}
        if self.actor_user_id is not None:
            details["actor_user_id"] = str(self.actor_user_id)
        self.db.add(
            VaultChangeEntry(
                change_set_id=change.id,
                vault_file_id=row.id,
                space_id=self.space_id,
                knowledge_base_id=self.knowledge_base_id,
                ordinal=0,
                operation=operation,
                before_path=before_path,
                after_path=after_path,
                before_hash=before_hash,
                after_hash=after_hash,
                size_delta_bytes=after_size - before_size,
                details=details,
            )
        )
        row.last_change_set_id = change.id
        return change

    def _touch_filesystem_metadata(self, row: VaultFile) -> None:
        path = self.storage.resolve(row.relative_path, require_exists=True)
        row.filesystem_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

    def create(
        self,
        path: str,
        content: str | bytes,
        *,
        source: VaultChangeSource = VaultChangeSource.API,
        **correlation: Any,
    ) -> VaultResult:
        normalized = normalize_relative_path(path)
        data = _bytes(content)
        existing = self._file(normalized, include_tombstone=True)
        if existing is not None and not existing.is_tombstoned:
            raise VaultConflictError("vault_file_exists", actual_hash=existing.content_hash)
        digest = _hash(data)
        self.storage.atomic_write(normalized, data)
        if existing is None:
            row = VaultFile(
                space_id=self.space_id,
                knowledge_base_id=self.knowledge_base_id,
                relative_path=normalized,
                file_kind=(
                    VaultFileKind.MARKDOWN
                    if normalized.casefold().endswith(".md")
                    else VaultFileKind.OTHER
                ),
                content_hash=digest,
                size_bytes=len(data),
                sync_state=VaultSyncState.SYNCED,
                revision=1,
            )
            self.db.add(row)
            self.db.flush()
        else:
            row = existing
            row.content_hash = digest
            row.size_bytes = len(data)
            row.sync_state = VaultSyncState.SYNCED
            row.is_tombstoned = False
            row.tombstoned_at = None
            row.revision += 1
        self._touch_filesystem_metadata(row)
        change = self._change(
            row,
            VaultChangeOperation.CREATE,
            before_path=None,
            after_path=normalized,
            before_hash=None,
            after_hash=digest,
            before_size=0,
            after_size=len(data),
            source=source,
            **correlation,
        )
        self.db.flush()
        return self._result(row, change, None, digest)

    def update(
        self,
        identifier: UUID | str,
        content: str | bytes,
        *,
        expected_hash: str,
        source: VaultChangeSource = VaultChangeSource.API,
        **correlation: Any,
    ) -> VaultResult:
        row, previous = self.read(identifier)
        if row.content_hash != expected_hash:
            raise VaultConflictError("vault_hash_conflict", actual_hash=row.content_hash)
        data = _bytes(content)
        before, after = row.content_hash, _hash(data)
        self.storage.atomic_write(row.relative_path, data)
        row.content_hash = after
        row.size_bytes = len(data)
        row.revision += 1
        row.sync_state = VaultSyncState.SYNCED
        self._touch_filesystem_metadata(row)
        change = self._change(
            row,
            VaultChangeOperation.UPDATE,
            before_path=row.relative_path,
            after_path=row.relative_path,
            before_hash=before,
            after_hash=after,
            before_size=len(previous),
            after_size=len(data),
            source=source,
            **correlation,
        )
        self.db.flush()
        return self._result(row, change, before, after)

    def move(
        self,
        identifier: UUID | str,
        target_path: str,
        *,
        expected_hash: str,
        source: VaultChangeSource = VaultChangeSource.API,
        **correlation: Any,
    ) -> VaultResult:
        row, content = self.read(identifier)
        if row.content_hash != expected_hash:
            raise VaultConflictError("vault_hash_conflict", actual_hash=row.content_hash)
        target = normalize_relative_path(target_path)
        target_row = self._file(target, include_tombstone=True)
        if target_row is not None and target_row.id != row.id:
            raise VaultConflictError("vault_target_exists", actual_hash=target_row.content_hash)
        before_path = row.relative_path
        self.storage.move(before_path, target)
        row.relative_path = target
        row.revision += 1
        self._touch_filesystem_metadata(row)
        change = self._change(
            row,
            VaultChangeOperation.MOVE,
            before_path=before_path,
            after_path=target,
            before_hash=row.content_hash,
            after_hash=row.content_hash,
            before_size=len(content),
            after_size=len(content),
            source=source,
            **correlation,
        )
        self.db.flush()
        return self._result(row, change, row.content_hash, row.content_hash)

    def delete(
        self,
        identifier: UUID | str,
        *,
        expected_hash: str,
        source: VaultChangeSource = VaultChangeSource.API,
        **correlation: Any,
    ) -> VaultResult:
        row, content = self.read(identifier)
        if row.content_hash != expected_hash:
            raise VaultConflictError("vault_hash_conflict", actual_hash=row.content_hash)
        before = row.content_hash
        change = self._change(
            row,
            VaultChangeOperation.DELETE,
            before_path=row.relative_path,
            after_path=None,
            before_hash=before,
            after_hash=None,
            before_size=len(content),
            after_size=0,
            source=source,
            **correlation,
        )
        row.is_tombstoned = True
        row.tombstoned_at = datetime.now(UTC)
        row.sync_state = VaultSyncState.TOMBSTONED
        row.revision += 1
        self.db.flush()
        self.storage.delete(row.relative_path)
        return self._result(row, change, before, None)

    def reconcile(
        self,
        note_id: UUID,
        *,
        database_markdown: str,
        source: VaultChangeSource = VaultChangeSource.EXTERNAL_EDITOR,
        session_id: UUID | None = None,
        turn_id: UUID | None = None,
        tool_call_id: str | None = None,
    ) -> ReconcileResult:
        from tutor_api.knowledge.models import (
            MarkdownNote,
            MarkdownRevision,
            MarkdownRevisionState,
        )

        note = self.db.scalar(
            select(MarkdownNote).where(
                MarkdownNote.id == note_id,
                MarkdownNote.knowledge_base_id == self.knowledge_base_id,
                MarkdownNote.space_id == self.space_id,
            )
        )
        if note is None or note.vault_file_id is None:
            raise KeyError("markdown_note_not_found")
        row = self.get_file(note.vault_file_id, include_tombstone=False)
        data = self.storage.read_bytes(row.relative_path)
        vault_hash = _hash(data)
        vault_markdown = data.decode("utf-8")
        database_hash = _hash(database_markdown.encode("utf-8"))
        if database_hash == vault_hash:
            row.content_hash = vault_hash
            row.size_bytes = len(data)
            row.sync_state = VaultSyncState.SYNCED
            note.content_hash = vault_hash
            note.sync_state = VaultSyncState.SYNCED.value
            self._touch_filesystem_metadata(row)
            self.db.flush()
            return ReconcileResult(vault_markdown, None, None, None)

        before_hash = row.content_hash
        change = self._change(
            row,
            VaultChangeOperation.UPDATE,
            before_path=row.relative_path,
            after_path=row.relative_path,
            before_hash=before_hash,
            after_hash=vault_hash,
            before_size=row.size_bytes,
            after_size=len(data),
            source=source,
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
        )
        next_revision = (
            self.db.scalar(
                select(func.max(MarkdownRevision.revision_number)).where(
                    MarkdownRevision.note_id == note.id
                )
            )
            or 0
        ) + 1
        actor_user_id = self.actor_user_id or note.created_by_user_id
        conflict_revision = MarkdownRevision(
            space_id=self.space_id,
            knowledge_base_id=self.knowledge_base_id,
            note_id=note.id,
            revision_number=next_revision,
            state=MarkdownRevisionState.DRAFT,
            markdown=database_markdown,
            content_sha256=database_hash,
            change_set_id=change.id,
            agent_session_id=session_id,
            agent_turn_id=turn_id,
            tool_call_id=tool_call_id,
            change_source=VaultChangeSource.CONFLICT_BACKUP.value,
            before_hash=before_hash,
            after_hash=database_hash,
            created_by_user_id=actor_user_id,
        )
        vault_revision = MarkdownRevision(
            space_id=self.space_id,
            knowledge_base_id=self.knowledge_base_id,
            note_id=note.id,
            revision_number=next_revision + 1,
            state=MarkdownRevisionState.DRAFT,
            markdown=vault_markdown,
            content_sha256=vault_hash,
            change_set_id=change.id,
            agent_session_id=session_id,
            agent_turn_id=turn_id,
            tool_call_id=tool_call_id,
            change_source=source.value,
            before_hash=database_hash,
            after_hash=vault_hash,
            created_by_user_id=actor_user_id,
        )
        self.db.add_all([conflict_revision, vault_revision])
        row.content_hash = vault_hash
        row.size_bytes = len(data)
        row.revision += 1
        row.sync_state = VaultSyncState.SYNCED
        note.vault_relative_path = row.relative_path
        note.content_hash = vault_hash
        note.sync_state = VaultSyncState.SYNCED.value
        note.last_change_set_id = change.id
        note.is_tombstoned = False
        note.tombstoned_at = None
        self._touch_filesystem_metadata(row)
        self.db.flush()
        return ReconcileResult(vault_markdown, conflict_revision, vault_revision, change.id)

    @staticmethod
    def _result(
        row: VaultFile, change: VaultChangeSet, before: str | None, after: str | None
    ) -> VaultResult:
        return VaultResult(
            vault_file_id=row.id,
            relative_path=row.relative_path,
            before_hash=before,
            after_hash=after,
            revision=row.revision,
            change_set_id=change.id,
            size_bytes=row.size_bytes,
            sync_state=row.sync_state.value,
            is_tombstoned=row.is_tombstoned,
        )
