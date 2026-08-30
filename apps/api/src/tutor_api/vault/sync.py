from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tutor_api.knowledge.models import (
    MarkdownNote,
    MarkdownNoteState,
    MarkdownRevision,
    MarkdownRevisionState,
)
from tutor_api.vault.models import (
    VaultChangeEntry,
    VaultChangeOperation,
    VaultChangeSet,
    VaultChangeSetState,
    VaultChangeSource,
    VaultFile,
    VaultFileKind,
    VaultSyncCursor,
    VaultSyncState,
)
from tutor_api.vault.storage import VaultStorage, normalize_relative_path

_IGNORED_NAMES = {".DS_Store", ".knowledge-base.json", "Thumbs.db"}


@dataclass(frozen=True, slots=True)
class VaultScanResult:
    change_set_id: UUID | None = None
    change_count: int = 0
    deferred: bool = False


@dataclass(frozen=True, slots=True)
class VaultProjectResult:
    change_set_id: UUID
    projected_count: int = 0


@dataclass(frozen=True, slots=True)
class _DiskFile:
    relative_path: str
    content_hash: str
    size_bytes: int
    modified_at: datetime
    file_identity: str | None
    file_kind: VaultFileKind


@dataclass(frozen=True, slots=True)
class _DetectedChange:
    row: VaultFile | None
    disk: _DiskFile | None
    operation: VaultChangeOperation
    before_path: str | None
    after_path: str | None
    before_hash: str | None
    after_hash: str | None
    before_size: int
    after_size: int


class VaultSyncService:
    """Reconcile watcher hints against a canonical full Vault scan.

    OS watcher events are only hints: all persistence decisions come from normalized
    paths and SHA-256 content.  The durable cursor makes watcher overflow and process
    restarts converge through a full scan instead of relying on an in-memory queue.
    """

    def __init__(
        self,
        db: Session,
        vault_root: Path,
        *,
        space_id: UUID,
        knowledge_base_id: UUID,
        actor_user_id: UUID | None = None,
        debounce_window: timedelta = timedelta(milliseconds=250),
    ) -> None:
        if debounce_window < timedelta(0):
            raise ValueError("debounce_window must not be negative")
        self.db = db
        self.space_id = space_id
        self.knowledge_base_id = knowledge_base_id
        self.actor_user_id = actor_user_id
        requested_vault_root = Path(vault_root)
        requested_vault_root.mkdir(parents=True, exist_ok=True)
        self.vault_root = requested_vault_root.resolve(strict=True)
        logical_root = self.vault_root / "spaces" / str(space_id) / str(knowledge_base_id)
        self.storage = VaultStorage(logical_root, anchor_root=self.vault_root)
        self.root = self.storage.root
        self.debounce_window = debounce_window
        self._observed_paths: set[str] = set()
        self._flush_after: datetime | None = None

    @property
    def cursor(self) -> VaultSyncCursor:
        cursor = self.db.scalar(
            select(VaultSyncCursor).where(
                VaultSyncCursor.knowledge_base_id == self.knowledge_base_id,
                VaultSyncCursor.space_id == self.space_id,
            )
        )
        if cursor is None:
            cursor = VaultSyncCursor(
                space_id=self.space_id,
                knowledge_base_id=self.knowledge_base_id,
                pending_count=0,
                requires_full_scan=True,
            )
            self.db.add(cursor)
            self.db.flush()
        return cursor

    def observe(
        self,
        relative_path: str,
        after_hash: str | None,
        *,
        event_id: str | None = None,
        observed_at: datetime | None = None,
    ) -> bool:
        """Record a watcher hint, suppressing known write echoes by content hash."""

        normalized = normalize_relative_path(relative_path)
        cursor = self.cursor
        if event_id is not None:
            cursor.watcher_cursor = event_id[:2048]
        row = self.db.scalar(
            select(VaultFile).where(
                VaultFile.knowledge_base_id == self.knowledge_base_id,
                VaultFile.space_id == self.space_id,
                VaultFile.relative_path == normalized,
                VaultFile.is_tombstoned.is_(False),
            )
        )
        if after_hash is not None and row is not None and row.content_hash == after_hash:
            cursor.last_success_at = observed_at or datetime.now(UTC)
            cursor.last_error = None
            self.db.flush()
            return False
        timestamp = observed_at or datetime.now(UTC)
        self._observed_paths.add(normalized)
        deadline = timestamp + self.debounce_window
        if self._flush_after is None or deadline > self._flush_after:
            self._flush_after = deadline
        cursor.pending_count = max(cursor.pending_count, 1)
        cursor.requires_full_scan = True
        self.db.flush()
        return True

    def flush(self, *, now: datetime | None = None) -> VaultScanResult:
        timestamp = now or datetime.now(UTC)
        if not self._observed_paths:
            return VaultScanResult()
        if self._flush_after is not None and timestamp < self._flush_after:
            return VaultScanResult(deferred=True)
        self._observed_paths.clear()
        self._flush_after = None
        return self.scan(now=timestamp)

    def require_full_scan(self, error_code: str | None = None) -> None:
        cursor = self.cursor
        cursor.requires_full_scan = True
        cursor.last_error = error_code[:1000] if error_code else None
        cursor.pending_count = max(cursor.pending_count, 1)
        self.db.flush()

    def resume(self, *, now: datetime | None = None) -> VaultScanResult:
        if self.cursor.requires_full_scan:
            return self.scan(now=now, force=True)
        return self.flush(now=now)

    def scan(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> VaultScanResult:
        del force  # A scan is canonical and complete regardless of which hint triggered it.
        timestamp = now or datetime.now(UTC)
        cursor = self.cursor
        try:
            disk = self._disk_snapshot()
            rows = list(
                self.db.scalars(
                    select(VaultFile).where(
                        VaultFile.knowledge_base_id == self.knowledge_base_id,
                        VaultFile.space_id == self.space_id,
                    )
                )
            )
            before_snapshot = self._database_snapshot_hash(rows)
            changes = self._detect_changes(rows, disk)
            if not changes:
                self._mark_scan_success(cursor, timestamp)
                self.db.flush()
                return VaultScanResult()
            change_set = VaultChangeSet(
                space_id=self.space_id,
                knowledge_base_id=self.knowledge_base_id,
                source=VaultChangeSource.EXTERNAL_EDITOR,
                state=VaultChangeSetState.COMMITTED,
                summary=f"Vault scan reconciled {len(changes)} change(s)",
                before_snapshot_hash=before_snapshot,
                after_snapshot_hash=self._disk_snapshot_hash(disk),
                committed_at=timestamp,
            )
            self.db.add(change_set)
            self.db.flush()
            for ordinal, detected in enumerate(changes):
                row = self._apply_detected_change(detected, timestamp, change_set.id)
                self.db.add(
                    VaultChangeEntry(
                        change_set_id=change_set.id,
                        vault_file_id=row.id,
                        space_id=self.space_id,
                        knowledge_base_id=self.knowledge_base_id,
                        ordinal=ordinal,
                        operation=detected.operation,
                        before_path=detected.before_path,
                        after_path=detected.after_path,
                        before_hash=detected.before_hash,
                        after_hash=detected.after_hash,
                        size_delta_bytes=detected.after_size - detected.before_size,
                        details={"source": VaultChangeSource.EXTERNAL_EDITOR.value},
                    )
                )
            self._mark_scan_success(cursor, timestamp)
            self.db.flush()
            return VaultScanResult(change_set.id, len(changes))
        except Exception as error:
            cursor.requires_full_scan = True
            cursor.last_error = self._public_error_code(error)
            cursor.pending_count = max(cursor.pending_count, 1)
            self.db.flush()
            raise

    def project(
        self,
        change_set_id: UUID,
        *,
        now: datetime | None = None,
    ) -> VaultProjectResult:
        timestamp = now or datetime.now(UTC)
        change_set = self.db.scalar(
            select(VaultChangeSet).where(
                VaultChangeSet.id == change_set_id,
                VaultChangeSet.knowledge_base_id == self.knowledge_base_id,
                VaultChangeSet.space_id == self.space_id,
            )
        )
        if change_set is None:
            raise KeyError("vault_change_set_not_found")
        if change_set.state in (VaultChangeSetState.INDEXING, VaultChangeSetState.INDEXED):
            return VaultProjectResult(change_set.id)
        entries = list(
            self.db.scalars(
                select(VaultChangeEntry)
                .where(VaultChangeEntry.change_set_id == change_set.id)
                .order_by(VaultChangeEntry.ordinal)
            )
        )
        projected = 0
        for entry in entries:
            row = self.db.get(VaultFile, entry.vault_file_id)
            if row is None or row.file_kind is not VaultFileKind.MARKDOWN:
                continue
            projected += self._project_markdown(row, entry, timestamp)
        change_set.state = VaultChangeSetState.INDEXING
        cursor = self.cursor
        cursor.database_cursor = str(change_set.id)
        cursor.pending_count = self._pending_projection_count(excluding=change_set.id)
        cursor.last_success_at = timestamp
        cursor.last_error = None
        self.db.flush()
        return VaultProjectResult(change_set.id, projected)

    def mark_indexed(
        self,
        change_set_id: UUID,
        *,
        now: datetime | None = None,
    ) -> None:
        change_set = self.db.get(VaultChangeSet, change_set_id)
        if (
            change_set is None
            or change_set.knowledge_base_id != self.knowledge_base_id
            or change_set.space_id != self.space_id
        ):
            raise KeyError("vault_change_set_not_found")
        change_set.state = VaultChangeSetState.INDEXED
        change_set.indexed_at = now or datetime.now(UTC)
        cursor = self.cursor
        cursor.index_cursor = str(change_set.id)
        cursor.pending_count = self._pending_projection_count()
        cursor.last_success_at = now or datetime.now(UTC)
        cursor.last_error = None
        self.db.flush()

    def _disk_snapshot(self) -> dict[str, _DiskFile]:
        snapshot: dict[str, _DiskFile] = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.is_symlink() or self._ignored(path):
                continue
            resolved = path.resolve(strict=True)
            if resolved != self.root and self.root not in resolved.parents:
                continue
            relative = normalize_relative_path(resolved.relative_to(self.root).as_posix())
            data = resolved.read_bytes()
            stat = resolved.stat()
            snapshot[relative] = _DiskFile(
                relative_path=relative,
                content_hash=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                file_identity=self._file_identity(stat),
                file_kind=self._file_kind(relative),
            )
        return snapshot

    @staticmethod
    def _ignored(path: Path) -> bool:
        name = path.name
        return (
            name in _IGNORED_NAMES
            or name.endswith((".tmp", ".swp", ".swx"))
            or (name.startswith(".") and name.endswith(".tmp"))
        )

    @staticmethod
    def _file_identity(stat: object) -> str | None:
        device = getattr(stat, "st_dev", None)
        inode = getattr(stat, "st_ino", None)
        if isinstance(inode, int) and inode > 0:
            return f"{device}:{inode}"
        return None

    @staticmethod
    def _file_kind(path: str) -> VaultFileKind:
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix in {".md", ".markdown"}:
            return VaultFileKind.MARKDOWN
        if suffix in {".json", ".diff", ".patch"}:
            return VaultFileKind.SIDECAR
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}:
            return VaultFileKind.ATTACHMENT
        return VaultFileKind.OTHER

    def _detect_changes(
        self,
        rows: list[VaultFile],
        disk: dict[str, _DiskFile],
    ) -> list[_DetectedChange]:
        live_by_path = {row.relative_path: row for row in rows if not row.is_tombstoned}
        changes: list[_DetectedChange] = []
        removed: list[VaultFile] = []
        added: list[_DiskFile] = []
        for path, row in live_by_path.items():
            observed = disk.get(path)
            if observed is None:
                removed.append(row)
                continue
            if observed.content_hash != row.content_hash:
                changes.append(
                    _DetectedChange(
                        row,
                        observed,
                        VaultChangeOperation.UPDATE,
                        path,
                        path,
                        row.content_hash,
                        observed.content_hash,
                        row.size_bytes,
                        observed.size_bytes,
                    )
                )
            else:
                self._refresh_metadata(row, observed)
        for path, observed in disk.items():
            if path not in live_by_path:
                added.append(observed)

        matched_rows: set[UUID] = set()
        matched_paths: set[str] = set()
        for observed in added:
            row = self._unique_move_candidate(removed, observed, matched_rows)
            if row is None:
                continue
            matched_rows.add(row.id)
            matched_paths.add(observed.relative_path)
            operation = (
                VaultChangeOperation.RENAME
                if PurePosixPath(row.relative_path).parent
                == PurePosixPath(observed.relative_path).parent
                else VaultChangeOperation.MOVE
            )
            changes.append(
                _DetectedChange(
                    row,
                    observed,
                    operation,
                    row.relative_path,
                    observed.relative_path,
                    row.content_hash,
                    observed.content_hash,
                    row.size_bytes,
                    observed.size_bytes,
                )
            )
        for row in removed:
            if row.id not in matched_rows:
                changes.append(
                    _DetectedChange(
                        row,
                        None,
                        VaultChangeOperation.DELETE,
                        row.relative_path,
                        None,
                        row.content_hash,
                        None,
                        row.size_bytes,
                        0,
                    )
                )
        tombstones = {row.relative_path: row for row in rows if row.is_tombstoned}
        for observed in added:
            if observed.relative_path in matched_paths:
                continue
            changes.append(
                _DetectedChange(
                    tombstones.get(observed.relative_path),
                    observed,
                    VaultChangeOperation.CREATE,
                    None,
                    observed.relative_path,
                    None,
                    observed.content_hash,
                    0,
                    observed.size_bytes,
                )
            )
        return sorted(
            changes,
            key=lambda item: (
                item.after_path or item.before_path or "",
                item.operation.value,
            ),
        )

    @staticmethod
    def _unique_move_candidate(
        removed: list[VaultFile], observed: _DiskFile, matched_rows: set[UUID]
    ) -> VaultFile | None:
        candidates = [
            row
            for row in removed
            if row.id not in matched_rows
            and row.file_identity is not None
            and row.file_identity == observed.file_identity
        ]
        if len(candidates) == 1:
            return candidates[0]
        candidates = [
            row
            for row in removed
            if row.id not in matched_rows and row.content_hash == observed.content_hash
        ]
        return candidates[0] if len(candidates) == 1 else None

    def _apply_detected_change(
        self,
        change: _DetectedChange,
        timestamp: datetime,
        change_set_id: UUID,
    ) -> VaultFile:
        row = change.row
        observed = change.disk
        if row is None:
            assert observed is not None
            row = VaultFile(
                space_id=self.space_id,
                knowledge_base_id=self.knowledge_base_id,
                relative_path=observed.relative_path,
                file_kind=observed.file_kind,
                content_hash=observed.content_hash,
                size_bytes=observed.size_bytes,
                filesystem_mtime=observed.modified_at,
                file_identity=observed.file_identity,
                sync_state=VaultSyncState.SYNCED,
                revision=1,
            )
            self.db.add(row)
            self.db.flush()
        elif change.operation is VaultChangeOperation.DELETE:
            row.is_tombstoned = True
            row.tombstoned_at = timestamp
            row.sync_state = VaultSyncState.TOMBSTONED
            row.revision += 1
        else:
            assert observed is not None
            row.relative_path = observed.relative_path
            row.file_kind = observed.file_kind
            row.content_hash = observed.content_hash
            row.size_bytes = observed.size_bytes
            row.filesystem_mtime = observed.modified_at
            row.file_identity = observed.file_identity
            row.sync_state = VaultSyncState.SYNCED
            row.is_tombstoned = False
            row.tombstoned_at = None
            row.revision += 1
        row.last_change_set_id = change_set_id
        return row

    @staticmethod
    def _refresh_metadata(row: VaultFile, observed: _DiskFile) -> None:
        row.filesystem_mtime = observed.modified_at
        row.file_identity = observed.file_identity
        row.size_bytes = observed.size_bytes
        row.sync_state = VaultSyncState.SYNCED

    def _project_markdown(
        self,
        row: VaultFile,
        entry: VaultChangeEntry,
        timestamp: datetime,
    ) -> int:
        note = self.db.scalar(
            select(MarkdownNote).where(
                MarkdownNote.vault_file_id == row.id,
                MarkdownNote.knowledge_base_id == self.knowledge_base_id,
                MarkdownNote.space_id == self.space_id,
            )
        )
        if note is None:
            title = self._markdown_title(row.relative_path, None)
            normalized = self._unique_normalized_title(title, row.relative_path)
            note = MarkdownNote(
                space_id=self.space_id,
                knowledge_base_id=self.knowledge_base_id,
                vault_file_id=row.id,
                vault_relative_path=row.relative_path,
                content_hash=None,
                sync_state=VaultSyncState.PENDING.value,
                title=title,
                normalized_title=normalized,
                state=MarkdownNoteState.DRAFT,
                created_by_user_id=self._projection_actor(),
            )
            self.db.add(note)
            self.db.flush()
        existing = self.db.scalar(
            select(MarkdownRevision.id).where(
                MarkdownRevision.note_id == note.id,
                MarkdownRevision.change_set_id == entry.change_set_id,
            )
        )
        if existing is not None:
            return 0
        if row.is_tombstoned or entry.operation is VaultChangeOperation.DELETE:
            markdown = None
            after_hash = None
            note.is_tombstoned = True
            note.tombstoned_at = timestamp
            note.sync_state = VaultSyncState.TOMBSTONED.value
        else:
            data = self.storage.read_bytes(row.relative_path)
            markdown = data.decode("utf-8")
            actual_hash = hashlib.sha256(data).hexdigest()
            if actual_hash != row.content_hash:
                raise RuntimeError("vault_projection_hash_mismatch")
            after_hash = actual_hash
            note.title = self._markdown_title(row.relative_path, markdown)
            note.normalized_title = self._unique_normalized_title(
                note.title, row.relative_path, excluding_note_id=note.id
            )
            note.is_tombstoned = False
            note.tombstoned_at = None
            note.sync_state = VaultSyncState.SYNCED.value
            note.content_hash = actual_hash
        revision_number = (
            self.db.scalar(
                select(func.max(MarkdownRevision.revision_number)).where(
                    MarkdownRevision.note_id == note.id
                )
            )
            or 0
        ) + 1
        self.db.add(
            MarkdownRevision(
                space_id=self.space_id,
                knowledge_base_id=self.knowledge_base_id,
                note_id=note.id,
                revision_number=revision_number,
                state=MarkdownRevisionState.DRAFT,
                markdown=markdown,
                content_sha256=after_hash,
                change_set_id=entry.change_set_id,
                change_source=VaultChangeSource.EXTERNAL_EDITOR.value,
                before_hash=entry.before_hash,
                after_hash=after_hash,
                created_by_user_id=self._projection_actor(),
            )
        )
        note.vault_relative_path = row.relative_path
        note.last_change_set_id = entry.change_set_id
        row.sync_state = VaultSyncState.TOMBSTONED if row.is_tombstoned else VaultSyncState.SYNCED
        return 1

    def _projection_actor(self) -> UUID:
        if self.actor_user_id is not None:
            return self.actor_user_id
        from tutor_api.knowledge.models import KnowledgeBase

        knowledge_base = self.db.get(KnowledgeBase, self.knowledge_base_id)
        if knowledge_base is None:
            raise RuntimeError("knowledge_base_not_found")
        return knowledge_base.created_by_user_id

    @staticmethod
    def _markdown_title(relative_path: str, markdown: str | None) -> str:
        if markdown is not None:
            for line in markdown.splitlines():
                if line.startswith("# ") and line[2:].strip():
                    return line[2:].strip()[:500]
        return PurePosixPath(relative_path).stem[:500] or "Untitled"

    def _unique_normalized_title(
        self,
        title: str,
        relative_path: str,
        *,
        excluding_note_id: UUID | None = None,
    ) -> str:
        normalized = " ".join(title.casefold().split())
        statement = select(MarkdownNote.id).where(
            MarkdownNote.knowledge_base_id == self.knowledge_base_id,
            MarkdownNote.normalized_title == normalized,
        )
        if excluding_note_id is not None:
            statement = statement.where(MarkdownNote.id != excluding_note_id)
        if self.db.scalar(statement) is None:
            return normalized
        suffix = " ".join(relative_path.casefold().split())
        return f"{normalized} [{suffix}]"[:500]

    def _pending_projection_count(self, *, excluding: UUID | None = None) -> int:
        statement = select(func.count(VaultChangeSet.id)).where(
            VaultChangeSet.knowledge_base_id == self.knowledge_base_id,
            VaultChangeSet.space_id == self.space_id,
            VaultChangeSet.state == VaultChangeSetState.COMMITTED,
        )
        if excluding is not None:
            statement = statement.where(VaultChangeSet.id != excluding)
        return int(self.db.scalar(statement) or 0)

    def _mark_scan_success(self, cursor: VaultSyncCursor, timestamp: datetime) -> None:
        cursor.requires_full_scan = False
        cursor.last_success_at = timestamp
        cursor.last_error = None
        cursor.pending_count = self._pending_projection_count()
        if cursor.watcher_cursor is None:
            cursor.watcher_cursor = timestamp.isoformat()

    @staticmethod
    def _disk_snapshot_hash(snapshot: dict[str, _DiskFile]) -> str:
        payload = "\n".join(
            f"{path}\0{item.content_hash}" for path, item in sorted(snapshot.items())
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _database_snapshot_hash(rows: list[VaultFile]) -> str:
        payload = "\n".join(
            f"{row.relative_path}\0{row.content_hash}"
            for row in sorted(rows, key=lambda item: item.relative_path)
            if not row.is_tombstoned
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _public_error_code(error: Exception) -> str:
        code = getattr(error, "code", None)
        if isinstance(code, str) and code:
            return code[:1000]
        return type(error).__name__.casefold()[:1000]

    def cursor_payload(self) -> str:
        """Return a compact diagnostic snapshot without paths or file contents."""

        cursor = self.cursor
        return json.dumps(
            {
                "pending_count": cursor.pending_count,
                "requires_full_scan": cursor.requires_full_scan,
                "database_cursor": cursor.database_cursor,
                "index_cursor": cursor.index_cursor,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
