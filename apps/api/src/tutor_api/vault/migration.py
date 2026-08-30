"""Auditable, resumable migration from legacy DB/object storage into permanent Vaults."""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from tutor_api.knowledge.models import (
    IndexVersion,
    IndexVersionState,
    KnowledgeBase,
    MarkdownNote,
    MarkdownNoteState,
    MarkdownRevision,
    MarkdownRevisionState,
)
from tutor_api.knowledge.storage import ObjectStorage
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

_OBJECT_MARKER = "object:"
_MANIFEST_VERSION = "1.0"
_ROUTE_SUMMARY_PREFIX = "vault-migration-route:"
_PENDING_STATE_WRITES_KEY = "vault_migration_pending_state_writes"


class MigrationPhase(StrEnum):
    INVENTORIED = "inventoried"
    COPIED = "copied"
    VERIFIED = "verified"
    SHADOW = "shadow"
    VAULT_AUTHORITATIVE = "vault_authoritative"
    LEGACY_AUTHORITATIVE = "legacy_authoritative"


@dataclass(frozen=True, slots=True)
class MigrationEntry:
    space_id: UUID
    knowledge_base_id: UUID
    note_id: UUID
    revision_id: UUID
    revision_number: int
    relative_path: str
    source_kind: str
    source_reference: str
    size_bytes: int
    sha256: str
    provenance: str = "initial_migration"


@dataclass(frozen=True, slots=True)
class MigrationManifest:
    path: Path
    entries: tuple[MigrationEntry, ...]
    space_id: UUID
    knowledge_base_id: UUID
    source_snapshot_sha256: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class MigrationConflict:
    relative_path: str
    source_hash: str
    existing_hash: str
    suggested_relative_path: str


@dataclass(frozen=True, slots=True)
class MigrationCopyResult:
    copied: int
    reused: int
    conflicts: list[MigrationConflict]
    conflict_report_path: Path


@dataclass(frozen=True, slots=True)
class MigrationVerifyResult:
    source_file_count: int
    vault_file_count: int
    source_total_bytes: int
    vault_total_bytes: int
    hash_mismatches: list[str]


@dataclass(frozen=True, slots=True)
class MigrationState:
    phase: MigrationPhase
    verified: bool
    previous_active_index_id: UUID | None
    manifest_sha256: str | None = None
    knowledge_base_id: UUID | None = None
    space_id: UUID | None = None
    source_snapshot_sha256: str | None = None
    conflict_count: int = 0
    verified_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MigrationRoute:
    phase: MigrationPhase
    vault_root: Path
    manifest_sha256: str
    source_snapshot_sha256: str


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_migration_relative_path(value: str) -> str:
    if not value or value != value.strip() or "\x00" in value or "\\" in value:
        raise ValueError("migration_path_invalid")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ValueError("migration_path_invalid")
    if not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError("migration_path_invalid")
    normalized = posix.as_posix()
    if normalized != value:
        raise ValueError("migration_path_invalid")
    return normalized


def resolve_vault_path(vault_root: Path, relative_path: str) -> Path:
    root = vault_root.resolve()
    normalized = validate_migration_relative_path(relative_path)
    target = (root / Path(*PurePosixPath(normalized).parts)).resolve()
    if root != target and root not in target.parents:
        raise RuntimeError("migration_path_escape")
    return target


def knowledge_base_vault_root(vault_root: Path, space_id: UUID, knowledge_base_id: UUID) -> Path:
    root = vault_root.resolve()
    scoped = (root / "spaces" / str(space_id) / str(knowledge_base_id)).resolve()
    if root != scoped and root not in scoped.parents:
        raise RuntimeError("migration_path_escape")
    return scoped


def _entry_json(entry: MigrationEntry) -> dict[str, object]:
    payload = asdict(entry)
    for key in ("space_id", "knowledge_base_id", "note_id", "revision_id"):
        payload[key] = str(payload[key])
    payload["record_type"] = "entry"
    return payload


def _entry_from_json(payload: dict[str, object]) -> MigrationEntry:
    entry = MigrationEntry(
        space_id=UUID(str(payload["space_id"])),
        knowledge_base_id=UUID(str(payload["knowledge_base_id"])),
        note_id=UUID(str(payload["note_id"])),
        revision_id=UUID(str(payload["revision_id"])),
        revision_number=int(payload["revision_number"]),
        relative_path=validate_migration_relative_path(str(payload["relative_path"])),
        source_kind=str(payload["source_kind"]),
        source_reference=str(payload["source_reference"]),
        size_bytes=int(payload["size_bytes"]),
        sha256=str(payload["sha256"]),
        provenance=str(payload.get("provenance", "initial_migration")),
    )
    if entry.revision_number <= 0 or entry.size_bytes < 0:
        raise ValueError("migration_manifest_invalid")
    if len(entry.sha256) != 64 or any(c not in "0123456789abcdef" for c in entry.sha256):
        raise ValueError("migration_manifest_invalid")
    if entry.source_kind not in {"database_markdown", "object_storage"}:
        raise ValueError("migration_manifest_invalid")
    return entry


def _snapshot_sha256(entries: tuple[MigrationEntry, ...] | list[MigrationEntry]) -> str:
    raw = "".join(
        json.dumps(_entry_json(entry), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for entry in entries
    )
    return _sha256(raw.encode("utf-8"))


def load_manifest(path: Path) -> MigrationManifest:
    resolved = path.resolve()
    raw = resolved.read_bytes()
    payloads = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    header: dict[str, Any] | None = None
    if payloads and payloads[0].get("record_type") == "manifest":
        header = payloads.pop(0)
        if header.get("schema_version") != _MANIFEST_VERSION:
            raise ValueError("migration_manifest_version_invalid")
    entries = tuple(_entry_from_json(payload) for payload in payloads)
    if entries:
        spaces = {entry.space_id for entry in entries}
        knowledge_bases = {entry.knowledge_base_id for entry in entries}
        if len(spaces) != 1 or len(knowledge_bases) != 1:
            raise ValueError("migration_manifest_scope_invalid")
        space_id = next(iter(spaces))
        knowledge_base_id = next(iter(knowledge_bases))
    elif header is not None:
        space_id = UUID(str(header["space_id"]))
        knowledge_base_id = UUID(str(header["knowledge_base_id"]))
    else:
        raise ValueError("migration_manifest_identity_missing")
    snapshot = _snapshot_sha256(entries)
    if header is not None:
        if UUID(str(header["space_id"])) != space_id:
            raise ValueError("migration_manifest_scope_invalid")
        if UUID(str(header["knowledge_base_id"])) != knowledge_base_id:
            raise ValueError("migration_manifest_scope_invalid")
        if str(header.get("source_snapshot_sha256")) != snapshot:
            raise ValueError("migration_manifest_snapshot_invalid")
    return MigrationManifest(
        path=resolved,
        entries=entries,
        space_id=space_id,
        knowledge_base_id=knowledge_base_id,
        source_snapshot_sha256=snapshot,
        manifest_sha256=_sha256(raw),
    )


def _safe_relative_path(title: str) -> str:
    normalized = unicodedata.normalize("NFC", title).replace("\\", "/")
    parts = []
    for raw in normalized.split("/"):
        part = raw.strip().replace(":", "-").replace("\x00", "")
        if part and part not in {".", ".."}:
            parts.append(part)
    candidate = PurePosixPath("notes", *(parts or ["untitled"]))
    if candidate.suffix.casefold() != ".md":
        candidate = candidate.with_name(candidate.name + ".md")
    return validate_migration_relative_path(candidate.as_posix())


def _deduplicate_path(path: str, revision_id: UUID, occupied: set[str]) -> str:
    if path not in occupied:
        occupied.add(path)
        return path
    original = PurePosixPath(path)
    candidate = original.with_name(f"{original.stem}--{str(revision_id)[:8]}{original.suffix}")
    counter = 2
    while candidate.as_posix() in occupied:
        candidate = original.with_name(
            f"{original.stem}--{str(revision_id)[:8]}-{counter}{original.suffix}"
        )
        counter += 1
    occupied.add(candidate.as_posix())
    return candidate.as_posix()


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def _state_payload(state: MigrationState) -> dict[str, object]:
    return {
        "phase": state.phase.value,
        "verified": state.verified,
        "previous_active_index_id": (
            str(state.previous_active_index_id) if state.previous_active_index_id else None
        ),
        "manifest_sha256": state.manifest_sha256,
        "knowledge_base_id": (str(state.knowledge_base_id) if state.knowledge_base_id else None),
        "space_id": str(state.space_id) if state.space_id else None,
        "source_snapshot_sha256": state.source_snapshot_sha256,
        "conflict_count": state.conflict_count,
        "verified_at": state.verified_at.isoformat() if state.verified_at else None,
    }


class MigrationStatePublishError(RuntimeError):
    """A database commit succeeded but its migration state artifact did not publish."""


def _pending_state_writes(session: Session) -> dict[object, dict[str, tuple[Path, object]]]:
    pending = session.info.setdefault(_PENDING_STATE_WRITES_KEY, {})
    if not isinstance(pending, dict):
        raise RuntimeError("migration_state_publish_queue_invalid")
    return pending


def _current_state_transaction(session: Session) -> object:
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        raise RuntimeError("migration_state_publish_transaction_missing")
    return transaction


@event.listens_for(Session, "after_commit")
def _publish_committed_migration_states(session: Session) -> None:
    transaction = session.get_nested_transaction() or session.get_transaction()
    pending_by_transaction = session.info.get(_PENDING_STATE_WRITES_KEY)
    if transaction is None or not isinstance(pending_by_transaction, dict):
        return
    pending = pending_by_transaction.pop(transaction, None)
    if not isinstance(pending, dict):
        if not pending_by_transaction:
            session.info.pop(_PENDING_STATE_WRITES_KEY, None)
        return

    parent = getattr(transaction, "parent", None)
    if parent is not None:
        parent_pending = pending_by_transaction.setdefault(parent, {})
        if not isinstance(parent_pending, dict):
            raise RuntimeError("migration_state_publish_queue_invalid")
        parent_pending.update(pending)
        return

    if not pending_by_transaction:
        session.info.pop(_PENDING_STATE_WRITES_KEY, None)
    try:
        for state_path, payload in tuple(pending.values()):
            _write_json_atomic(state_path, payload)
    except Exception as error:
        raise MigrationStatePublishError("migration_state_publish_failed") from error


@event.listens_for(Session, "after_soft_rollback")
def _discard_soft_rolled_back_migration_states(
    session: Session, previous_transaction: object
) -> None:
    pending_by_transaction = session.info.get(_PENDING_STATE_WRITES_KEY)
    if not isinstance(pending_by_transaction, dict):
        return
    pending_by_transaction.pop(previous_transaction, None)
    if not pending_by_transaction:
        session.info.pop(_PENDING_STATE_WRITES_KEY, None)


def _route_change_set_id(knowledge_base_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"vault-migration-route:{knowledge_base_id}")


def migration_route_for_knowledge_base(
    session: Session, knowledge_base_id: UUID
) -> MigrationRoute | None:
    row = session.get(VaultChangeSet, _route_change_set_id(knowledge_base_id))
    if (
        row is None
        or row.knowledge_base_id != knowledge_base_id
        or row.source is not VaultChangeSource.INITIAL_MIGRATION
        or row.state is not VaultChangeSetState.COMMITTED
        or not row.summary
        or not row.summary.startswith(_ROUTE_SUMMARY_PREFIX)
    ):
        return None
    try:
        payload = json.loads(row.summary.removeprefix(_ROUTE_SUMMARY_PREFIX))
        return MigrationRoute(
            phase=MigrationPhase(payload["phase"]),
            vault_root=Path(payload["vault_root"]).resolve(),
            manifest_sha256=str(payload["manifest_sha256"]),
            source_snapshot_sha256=str(payload["source_snapshot_sha256"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def mirror_legacy_published_revision(
    session: Session,
    note: MarkdownNote,
    revision: MarkdownRevision,
) -> UUID | None:
    route = migration_route_for_knowledge_base(session, note.knowledge_base_id)
    if route is None or route.phase not in {
        MigrationPhase.SHADOW,
        MigrationPhase.VAULT_AUTHORITATIVE,
    }:
        return None
    if revision.markdown is None:
        raise RuntimeError("migration_shadow_source_missing")

    from tutor_api.vault.service import VaultService

    service = VaultService(
        session,
        route.vault_root,
        space_id=note.space_id,
        knowledge_base_id=note.knowledge_base_id,
        actor_user_id=revision.created_by_user_id,
    )
    data = revision.markdown.encode("utf-8")
    digest = _sha256(data)
    if note.vault_file_id is None:
        occupied = set(
            session.scalars(
                select(VaultFile.relative_path).where(
                    VaultFile.knowledge_base_id == note.knowledge_base_id,
                    VaultFile.space_id == note.space_id,
                )
            )
        )
        relative_path = _deduplicate_path(_safe_relative_path(note.title), revision.id, occupied)
        result = service.create(
            relative_path,
            data,
            source=VaultChangeSource.API,
        )
    else:
        row, current = service.read(note.vault_file_id)
        if current == data:
            note.vault_relative_path = row.relative_path
            note.content_hash = digest
            note.sync_state = VaultSyncState.SYNCED.value
            return row.last_change_set_id
        result = service.update(
            row.id,
            data,
            expected_hash=row.content_hash,
            source=VaultChangeSource.API,
        )

    note.vault_file_id = result.vault_file_id
    note.vault_relative_path = result.relative_path
    note.content_hash = digest
    note.sync_state = VaultSyncState.SYNCED.value
    note.last_change_set_id = result.change_set_id
    revision.change_set_id = result.change_set_id
    revision.change_source = VaultChangeSource.API.value
    revision.before_hash = result.before_hash
    revision.after_hash = result.after_hash
    session.flush()
    return result.change_set_id


class VaultMigrator:
    def __init__(
        self,
        *,
        session: Session,
        object_storage: ObjectStorage,
        vault_root: Path,
        artifact_root: Path,
    ) -> None:
        self.session = session
        self.object_storage = object_storage
        self.vault_root = vault_root.resolve()
        self.artifact_root = artifact_root.resolve()

    def scoped_vault_root(self, manifest: MigrationManifest) -> Path:
        return knowledge_base_vault_root(
            self.vault_root, manifest.space_id, manifest.knowledge_base_id
        )

    def _state_path(self, manifest: MigrationManifest) -> Path:
        return manifest.path.with_suffix(".state.json")

    def _read_state(self, manifest: MigrationManifest) -> MigrationState:
        path = self._state_path(manifest)
        if not path.exists():
            return MigrationState(MigrationPhase.INVENTORIED, False, None)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return MigrationState(
            phase=MigrationPhase(payload["phase"]),
            verified=bool(payload.get("verified", False)),
            previous_active_index_id=(
                UUID(payload["previous_active_index_id"])
                if payload.get("previous_active_index_id")
                else None
            ),
            manifest_sha256=payload.get("manifest_sha256"),
            knowledge_base_id=(
                UUID(payload["knowledge_base_id"]) if payload.get("knowledge_base_id") else None
            ),
            space_id=UUID(payload["space_id"]) if payload.get("space_id") else None,
            source_snapshot_sha256=payload.get("source_snapshot_sha256"),
            conflict_count=int(payload.get("conflict_count", 0)),
            verified_at=(
                datetime.fromisoformat(payload["verified_at"])
                if payload.get("verified_at")
                else None
            ),
        )

    def _state(
        self,
        manifest: MigrationManifest,
        phase: MigrationPhase,
        verified: bool,
        previous: UUID | None,
        *,
        conflicts: int = 0,
        verified_at: datetime | None = None,
    ) -> MigrationState:
        return MigrationState(
            phase=phase,
            verified=verified,
            previous_active_index_id=previous,
            manifest_sha256=manifest.manifest_sha256,
            knowledge_base_id=manifest.knowledge_base_id,
            space_id=manifest.space_id,
            source_snapshot_sha256=manifest.source_snapshot_sha256,
            conflict_count=conflicts,
            verified_at=verified_at,
        )

    def _write_state(self, manifest: MigrationManifest, state: MigrationState) -> MigrationState:
        _write_json_atomic(self._state_path(manifest), _state_payload(state))
        return state

    def _write_state_after_commit(
        self, manifest: MigrationManifest, state: MigrationState
    ) -> MigrationState:
        pending_by_transaction = _pending_state_writes(self.session)
        transaction = _current_state_transaction(self.session)
        pending = pending_by_transaction.setdefault(transaction, {})
        if not isinstance(pending, dict):
            raise RuntimeError("migration_state_publish_queue_invalid")
        state_path = self._state_path(manifest)
        pending[str(state_path)] = (state_path, _state_payload(state))
        return state

    def _source_bytes(self, entry: MigrationEntry) -> bytes:
        if entry.source_kind == "database_markdown":
            revision = self.session.get(MarkdownRevision, entry.revision_id)
            if revision is None or revision.markdown is None:
                raise RuntimeError("migration_source_missing")
            raw = revision.markdown.encode("utf-8")
        elif entry.source_kind == "object_storage":
            raw = self.object_storage.get_object(entry.source_reference).data
        else:
            raise RuntimeError("migration_source_kind_invalid")
        if len(raw) != entry.size_bytes or _sha256(raw) != entry.sha256:
            raise RuntimeError("migration_source_changed")
        return raw

    def _inventory_entries(
        self, knowledge_base_id: UUID
    ) -> tuple[UUID, tuple[MigrationEntry, ...]]:
        kb = self.session.get(KnowledgeBase, knowledge_base_id)
        if kb is None:
            raise RuntimeError("migration_knowledge_base_missing")
        rows = self.session.execute(
            select(MarkdownNote, MarkdownRevision)
            .join(MarkdownRevision, MarkdownRevision.note_id == MarkdownNote.id)
            .where(
                MarkdownNote.knowledge_base_id == knowledge_base_id,
                MarkdownNote.space_id == kb.space_id,
                MarkdownNote.state == MarkdownNoteState.PUBLISHED,
                MarkdownNote.is_tombstoned.is_(False),
                MarkdownRevision.state == MarkdownRevisionState.PUBLISHED,
            )
            .order_by(MarkdownNote.title, MarkdownNote.id, MarkdownRevision.revision_number)
        ).all()
        occupied: set[str] = set()
        entries: list[MigrationEntry] = []
        for note, revision in rows:
            if revision.markdown is not None:
                raw = revision.markdown.encode("utf-8")
                source_kind = "database_markdown"
                source_reference = str(revision.id)
            else:
                source_reference = next(
                    (
                        marker.removeprefix(_OBJECT_MARKER)
                        for marker in revision.source_markers
                        if marker.startswith(_OBJECT_MARKER)
                    ),
                    "",
                )
                if not source_reference:
                    raise RuntimeError("migration_source_missing")
                raw = self.object_storage.get_object(source_reference).data
                source_kind = "object_storage"
            entries.append(
                MigrationEntry(
                    space_id=note.space_id,
                    knowledge_base_id=note.knowledge_base_id,
                    note_id=note.id,
                    revision_id=revision.id,
                    revision_number=revision.revision_number,
                    relative_path=_deduplicate_path(
                        _safe_relative_path(note.title), revision.id, occupied
                    ),
                    source_kind=source_kind,
                    source_reference=source_reference,
                    size_bytes=len(raw),
                    sha256=_sha256(raw),
                )
            )
        return kb.space_id, tuple(entries)

    def _assert_manifest_unchanged(
        self, manifest: MigrationManifest, state: MigrationState | None = None
    ) -> None:
        current = _sha256(manifest.path.read_bytes())
        if current != manifest.manifest_sha256:
            raise RuntimeError("migration_manifest_changed")
        if state is not None:
            if state.manifest_sha256 != current:
                raise RuntimeError("migration_manifest_changed")
            if (
                state.knowledge_base_id != manifest.knowledge_base_id
                or state.space_id != manifest.space_id
                or state.source_snapshot_sha256 != manifest.source_snapshot_sha256
            ):
                raise RuntimeError("migration_state_identity_mismatch")

    def _assert_source_unchanged(self, manifest: MigrationManifest) -> None:
        try:
            space_id, entries = self._inventory_entries(manifest.knowledge_base_id)
        except Exception as error:
            raise RuntimeError("migration_source_changed") from error
        if (
            space_id != manifest.space_id
            or _snapshot_sha256(entries) != manifest.source_snapshot_sha256
        ):
            raise RuntimeError("migration_source_changed")

    def _assert_shadow_projection_current(self, manifest: MigrationManifest) -> None:
        rows = self.session.execute(
            select(MarkdownNote, MarkdownRevision)
            .join(MarkdownRevision, MarkdownRevision.note_id == MarkdownNote.id)
            .where(
                MarkdownNote.knowledge_base_id == manifest.knowledge_base_id,
                MarkdownNote.space_id == manifest.space_id,
                MarkdownNote.state == MarkdownNoteState.PUBLISHED,
                MarkdownNote.is_tombstoned.is_(False),
                MarkdownRevision.state == MarkdownRevisionState.PUBLISHED,
            )
        ).all()
        scoped_root = self.scoped_vault_root(manifest)
        for note, revision in rows:
            if note.vault_file_id is None or note.vault_relative_path is None:
                raise RuntimeError("migration_source_changed")
            vault_file = self.session.get(VaultFile, note.vault_file_id)
            if (
                vault_file is None
                or vault_file.space_id != manifest.space_id
                or vault_file.knowledge_base_id != manifest.knowledge_base_id
                or vault_file.relative_path != note.vault_relative_path
                or vault_file.is_tombstoned
            ):
                raise RuntimeError("migration_source_changed")
            if revision.markdown is not None:
                source = revision.markdown.encode("utf-8")
            else:
                source_reference = next(
                    (
                        marker.removeprefix(_OBJECT_MARKER)
                        for marker in revision.source_markers
                        if marker.startswith(_OBJECT_MARKER)
                    ),
                    "",
                )
                if not source_reference:
                    raise RuntimeError("migration_source_changed")
                source = self.object_storage.get_object(source_reference).data
            try:
                target = resolve_vault_path(scoped_root, vault_file.relative_path)
                vaulted = target.read_bytes()
            except (OSError, RuntimeError):
                raise RuntimeError("migration_source_changed") from None
            digest = _sha256(source)
            if (
                vaulted != source
                or vault_file.content_hash != digest
                or vault_file.size_bytes != len(source)
            ):
                raise RuntimeError("migration_source_changed")

    def inventory(self, *, knowledge_base_id: UUID) -> MigrationManifest:
        space_id, entries = self._inventory_entries(knowledge_base_id)
        snapshot = _snapshot_sha256(entries)
        directory = self.artifact_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "manifest.jsonl"
        header = {
            "record_type": "manifest",
            "schema_version": _MANIFEST_VERSION,
            "space_id": str(space_id),
            "knowledge_base_id": str(knowledge_base_id),
            "source_snapshot_sha256": snapshot,
        }
        path.write_text(
            json.dumps(header, ensure_ascii=False, sort_keys=True)
            + "\n"
            + "".join(
                json.dumps(_entry_json(entry), ensure_ascii=False, sort_keys=True) + "\n"
                for entry in entries
            ),
            encoding="utf-8",
        )
        manifest = load_manifest(path)
        active = self.session.scalar(
            select(IndexVersion.id).where(
                IndexVersion.knowledge_base_id == knowledge_base_id,
                IndexVersion.state == IndexVersionState.ACTIVE,
            )
        )
        self._write_state(
            manifest,
            self._state(manifest, MigrationPhase.INVENTORIED, False, active),
        )
        return manifest

    def _preflight_projection(self, manifest: MigrationManifest) -> None:
        for entry in manifest.entries:
            resolve_vault_path(self.scoped_vault_root(manifest), entry.relative_path)
            stable_id = uuid5(
                NAMESPACE_URL,
                f"vault-migration:{entry.knowledge_base_id}:{entry.relative_path}",
            )
            by_path = self.session.scalar(
                select(VaultFile).where(
                    VaultFile.knowledge_base_id == entry.knowledge_base_id,
                    VaultFile.relative_path == entry.relative_path,
                )
            )
            by_id = self.session.get(VaultFile, stable_id)
            for row in (by_path, by_id):
                if row is not None and (
                    row.content_hash != entry.sha256
                    or row.relative_path != entry.relative_path
                    or row.space_id != entry.space_id
                ):
                    raise RuntimeError("migration_projection_conflict")

    def _normalize_existing_ordinals(
        self, change_set: VaultChangeSet, manifest: MigrationManifest
    ) -> None:
        rows = list(
            self.session.scalars(
                select(VaultChangeEntry).where(VaultChangeEntry.change_set_id == change_set.id)
            )
        )
        if not rows:
            return
        expected = {
            str(entry.revision_id): ordinal for ordinal, entry in enumerate(manifest.entries)
        }
        offset = len(manifest.entries) + len(rows) + 1000
        for row in rows:
            row.ordinal += offset
        self.session.flush()
        for row in rows:
            revision_id = str(row.details.get("legacy_revision_id", ""))
            if revision_id not in expected:
                raise RuntimeError("migration_change_entry_manifest_mismatch")
            row.ordinal = expected[revision_id]
        self.session.flush()

    def _project_vault_file(
        self, entry: MigrationEntry, *, change_set: VaultChangeSet, ordinal: int
    ) -> None:
        stable_id = uuid5(
            NAMESPACE_URL,
            f"vault-migration:{entry.knowledge_base_id}:{entry.relative_path}",
        )
        vault_file = self.session.scalar(
            select(VaultFile).where(
                VaultFile.knowledge_base_id == entry.knowledge_base_id,
                VaultFile.relative_path == entry.relative_path,
            )
        )
        if vault_file is None:
            vault_file = VaultFile(
                id=stable_id,
                space_id=entry.space_id,
                knowledge_base_id=entry.knowledge_base_id,
                relative_path=entry.relative_path,
                file_kind=VaultFileKind.MARKDOWN,
                content_hash=entry.sha256,
                size_bytes=entry.size_bytes,
                sync_state=VaultSyncState.SYNCED,
                revision=entry.revision_number,
            )
            self.session.add(vault_file)
            self.session.flush()
        existing = self.session.scalar(
            select(VaultChangeEntry).where(
                VaultChangeEntry.change_set_id == change_set.id,
                VaultChangeEntry.vault_file_id == vault_file.id,
            )
        )
        details = {
            "migration_provenance": entry.provenance,
            "legacy_note_id": str(entry.note_id),
            "legacy_revision_id": str(entry.revision_id),
            "legacy_source_kind": entry.source_kind,
            "legacy_source_reference": entry.source_reference,
        }
        if existing is None:
            self.session.add(
                VaultChangeEntry(
                    change_set_id=change_set.id,
                    vault_file_id=vault_file.id,
                    space_id=entry.space_id,
                    knowledge_base_id=entry.knowledge_base_id,
                    ordinal=ordinal,
                    operation=VaultChangeOperation.CREATE,
                    after_path=entry.relative_path,
                    after_hash=entry.sha256,
                    size_delta_bytes=entry.size_bytes,
                    details=details,
                )
            )
        else:
            existing.ordinal = ordinal
            existing.details = details
        vault_file.last_change_set_id = change_set.id
        vault_file.sync_state = VaultSyncState.SYNCED
        vault_file.revision = max(vault_file.revision, entry.revision_number)
        note = self.session.get(MarkdownNote, entry.note_id)
        if note is not None:
            note.vault_file_id = vault_file.id
            note.vault_relative_path = entry.relative_path
            note.content_hash = entry.sha256
            note.sync_state = "synced"
            note.last_change_set_id = change_set.id
        revision = self.session.get(MarkdownRevision, entry.revision_id)
        if revision is not None:
            revision.change_set_id = change_set.id
            revision.change_source = VaultChangeSource.INITIAL_MIGRATION.value
            revision.before_hash = entry.sha256
            revision.after_hash = entry.sha256

    def copy(self, manifest: MigrationManifest) -> MigrationCopyResult:
        self._assert_manifest_unchanged(manifest)
        self._preflight_projection(manifest)
        copied = reused = 0
        conflicts: list[MigrationConflict] = []
        successful: list[tuple[int, MigrationEntry]] = []
        for ordinal, entry in enumerate(manifest.entries):
            raw = self._source_bytes(entry)
            target = resolve_vault_path(self.scoped_vault_root(manifest), entry.relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                existing_hash = _sha256(target.read_bytes())
                if existing_hash == entry.sha256:
                    reused += 1
                    successful.append((ordinal, entry))
                    continue
                conflicts.append(
                    MigrationConflict(
                        entry.relative_path,
                        entry.sha256,
                        existing_hash,
                        _deduplicate_path(
                            entry.relative_path, entry.revision_id, {entry.relative_path}
                        ),
                    )
                )
                continue
            temporary = target.with_name(target.name + f".{entry.revision_id}.tmp")
            temporary.write_bytes(raw)
            if _sha256(temporary.read_bytes()) != entry.sha256:
                temporary.unlink(missing_ok=True)
                raise RuntimeError("migration_copy_hash_mismatch")
            os.replace(temporary, target)
            copied += 1
            successful.append((ordinal, entry))
        report = manifest.path.with_name("conflicts.json")
        _write_json_atomic(report, [asdict(conflict) for conflict in conflicts])
        if successful:
            change_set_id = uuid5(
                NAMESPACE_URL,
                f"vault-migration-change-set:{manifest.knowledge_base_id}:{manifest.manifest_sha256}",
            )
            change_set = self.session.get(VaultChangeSet, change_set_id)
            if change_set is None:
                change_set = VaultChangeSet(
                    id=change_set_id,
                    space_id=manifest.space_id,
                    knowledge_base_id=manifest.knowledge_base_id,
                    source=VaultChangeSource.INITIAL_MIGRATION,
                    summary=f"Initial Vault migration from {manifest.path}",
                    before_snapshot_hash=manifest.source_snapshot_sha256,
                    after_snapshot_hash=manifest.source_snapshot_sha256,
                )
                self.session.add(change_set)
                self.session.flush()
            self._normalize_existing_ordinals(change_set, manifest)
            change_set.state = (
                VaultChangeSetState.CONFLICTED if conflicts else VaultChangeSetState.COMMITTED
            )
            change_set.committed_at = datetime.now(UTC)
            change_set.conflicted_at = datetime.now(UTC) if conflicts else None
            for ordinal, entry in successful:
                self._project_vault_file(entry, change_set=change_set, ordinal=ordinal)
            self.session.flush()
        old = self._read_state(manifest)
        self._write_state(
            manifest,
            self._state(
                manifest,
                MigrationPhase.COPIED,
                False,
                old.previous_active_index_id,
                conflicts=len(conflicts),
            ),
        )
        return MigrationCopyResult(copied, reused, conflicts, report)

    def _verify_vault_snapshot(self, manifest: MigrationManifest) -> MigrationVerifyResult:
        mismatches: list[str] = []
        vault_count = vault_bytes = 0
        scoped_root = self.scoped_vault_root(manifest)
        for entry in manifest.entries:
            target = resolve_vault_path(scoped_root, entry.relative_path)
            if not target.is_file():
                mismatches.append(f"missing:{entry.relative_path}")
                continue
            raw = target.read_bytes()
            vault_count += 1
            vault_bytes += len(raw)
            if len(raw) != entry.size_bytes or _sha256(raw) != entry.sha256:
                mismatches.append(f"hash:{entry.relative_path}")
        return MigrationVerifyResult(
            len(manifest.entries),
            vault_count,
            sum(entry.size_bytes for entry in manifest.entries),
            vault_bytes,
            mismatches,
        )

    def verify(self, manifest: MigrationManifest) -> MigrationVerifyResult:
        self._assert_manifest_unchanged(manifest)
        result = self._verify_vault_snapshot(manifest)
        mismatches = result.hash_mismatches
        try:
            self._assert_source_unchanged(manifest)
        except RuntimeError:
            mismatches.append("source:snapshot")
        old = self._read_state(manifest)
        verified = (
            result.source_file_count == result.vault_file_count
            and result.source_total_bytes == result.vault_total_bytes
            and not mismatches
            and old.conflict_count == 0
        )
        self._write_state(
            manifest,
            self._state(
                manifest,
                MigrationPhase.VERIFIED if verified else MigrationPhase.COPIED,
                verified,
                old.previous_active_index_id,
                conflicts=old.conflict_count,
                verified_at=datetime.now(UTC) if verified else None,
            ),
        )
        return result

    def _write_route(self, manifest: MigrationManifest, state: MigrationState) -> None:
        route = self.session.get(VaultChangeSet, _route_change_set_id(manifest.knowledge_base_id))
        if route is None:
            route = VaultChangeSet(
                id=_route_change_set_id(manifest.knowledge_base_id),
                space_id=manifest.space_id,
                knowledge_base_id=manifest.knowledge_base_id,
                source=VaultChangeSource.INITIAL_MIGRATION,
            )
            self.session.add(route)
        route.state = VaultChangeSetState.COMMITTED
        route.summary = _ROUTE_SUMMARY_PREFIX + json.dumps(
            {
                "phase": state.phase.value,
                "vault_root": str(self.vault_root),
                "manifest_sha256": manifest.manifest_sha256,
                "source_snapshot_sha256": manifest.source_snapshot_sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        route.before_snapshot_hash = manifest.source_snapshot_sha256
        route.after_snapshot_hash = manifest.manifest_sha256
        route.committed_at = datetime.now(UTC)
        self.session.flush()

    def activate_shadow(self, manifest: MigrationManifest) -> MigrationState:
        old = self._read_state(manifest)
        if not old.verified:
            raise RuntimeError("migration_not_verified")
        if old.conflict_count:
            raise RuntimeError("migration_conflicts_unresolved")
        self._assert_manifest_unchanged(manifest, old)
        self._assert_source_unchanged(manifest)
        shadow_result = self._verify_vault_snapshot(manifest)
        if (
            shadow_result.source_file_count != shadow_result.vault_file_count
            or shadow_result.source_total_bytes != shadow_result.vault_total_bytes
            or shadow_result.hash_mismatches
        ):
            raise RuntimeError("migration_shadow_mismatch")
        state = self._state(
            manifest,
            MigrationPhase.SHADOW,
            True,
            old.previous_active_index_id,
            verified_at=old.verified_at,
        )
        self._write_route(manifest, state)
        return self._write_state(manifest, state)

    def cutover(self, manifest: MigrationManifest) -> MigrationState:
        old = self._read_state(manifest)
        if not old.verified:
            raise RuntimeError("migration_not_verified")
        if old.phase is not MigrationPhase.SHADOW:
            raise RuntimeError("migration_shadow_required")
        if old.conflict_count:
            raise RuntimeError("migration_conflicts_unresolved")
        self._assert_manifest_unchanged(manifest, old)
        self._assert_shadow_projection_current(manifest)
        for entry in manifest.entries:
            target = resolve_vault_path(self.scoped_vault_root(manifest), entry.relative_path)
            if not target.is_file() or _sha256(target.read_bytes()) != entry.sha256:
                raise RuntimeError("migration_vault_changed")
        state = self._state(
            manifest,
            MigrationPhase.VAULT_AUTHORITATIVE,
            True,
            old.previous_active_index_id,
            verified_at=old.verified_at,
        )
        self._write_route(manifest, state)
        return self._write_state(manifest, state)

    def rollback(self, manifest: MigrationManifest) -> MigrationState:
        old = self._read_state(manifest)
        self._assert_manifest_unchanged(manifest, old)
        previous_id = old.previous_active_index_id
        previous: IndexVersion | None = None
        if previous_id is not None:
            previous = self.session.get(IndexVersion, previous_id)
            if previous is None:
                raise RuntimeError("migration_previous_index_missing")
            if (
                previous.knowledge_base_id != manifest.knowledge_base_id
                or previous.space_id != manifest.space_id
            ):
                raise RuntimeError("migration_previous_index_scope_mismatch")

        active_indexes = update(IndexVersion).where(
            IndexVersion.knowledge_base_id == manifest.knowledge_base_id,
            IndexVersion.space_id == manifest.space_id,
            IndexVersion.state == IndexVersionState.ACTIVE,
        )
        if previous is not None:
            active_indexes = active_indexes.where(IndexVersion.id != previous.id)
        self.session.execute(
            active_indexes.values(
                state=IndexVersionState.RETIRED,
                activation_status="retired",
            )
        )
        self.session.flush()
        if previous is not None:
            previous.state = IndexVersionState.ACTIVE
            previous.activation_status = "active"
            if previous.activated_at is None:
                previous.activated_at = datetime.now(UTC)
            self.session.flush()
        state = self._state(
            manifest,
            MigrationPhase.LEGACY_AUTHORITATIVE,
            old.verified,
            previous_id,
            conflicts=old.conflict_count,
            verified_at=old.verified_at,
        )
        self._write_route(manifest, state)
        return self._write_state_after_commit(manifest, state)
