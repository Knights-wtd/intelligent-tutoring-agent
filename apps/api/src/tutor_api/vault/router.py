from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import AliasChoices, BaseModel, Field
from sqlalchemy import select

from tutor_api.core.database import session_scope
from tutor_api.identity.router import CurrentUser, _session_factory
from tutor_api.knowledge.access import get_readable_knowledge_base, get_writable_knowledge_base
from tutor_api.vault.models import VaultChangeEntry, VaultChangeSet
from tutor_api.vault.service import VaultResult, VaultService
from tutor_api.vault.storage import VaultConflictError, VaultPathError

router = APIRouter(prefix="/api/v1/knowledge-bases/{knowledge_base_id}/vault", tags=["vault"])


class WriteRequest(BaseModel):
    relative_path: str = Field(min_length=1, max_length=2048)
    markdown: str = Field(validation_alias=AliasChoices("markdown", "content"))


class UpdateRequest(BaseModel):
    markdown: str = Field(validation_alias=AliasChoices("markdown", "content"))
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class MoveRequest(BaseModel):
    relative_path: str = Field(
        min_length=1,
        max_length=2048,
        validation_alias=AliasChoices("relative_path", "target_path"),
    )
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeleteRequest(BaseModel):
    expected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _root(request: Request) -> Path:
    explicit = getattr(request.app.state, "vault_root", None)
    if explicit is not None:
        return Path(explicit)
    settings = getattr(request.app.state, "settings", None)
    configured = getattr(settings, "agent_vault_root", None)
    return Path(configured) if configured is not None else Path.cwd() / ".agent-vault"


def _service(request: Request, db, kb, current_user: CurrentUser) -> VaultService:
    return VaultService(
        db,
        _root(request),
        space_id=kb.space_id,
        knowledge_base_id=kb.id,
        actor_user_id=current_user.id,
    )


def _result(value: VaultResult) -> dict[str, Any]:
    return {
        "vault_file_id": value.vault_file_id,
        "relative_path": value.relative_path,
        "before_hash": value.before_hash,
        "after_hash": value.after_hash,
        "content_hash": value.content_hash,
        "hash": value.content_hash,
        "revision": value.revision,
        "change_set_id": value.change_set_id,
        "size_bytes": value.size_bytes,
        "sync_state": value.sync_state,
        "index_state": "pending",
        "is_tombstoned": value.is_tombstoned,
    }


def _row(row) -> dict[str, Any]:
    return {
        "vault_file_id": row.id,
        "relative_path": row.relative_path,
        "content_hash": row.content_hash,
        "hash": row.content_hash,
        "revision": row.revision,
        "size_bytes": row.size_bytes,
        "sync_state": row.sync_state.value,
        "is_tombstoned": row.is_tombstoned,
        "last_change_set_id": row.last_change_set_id,
        "index_state": "pending" if row.last_index_version_id is None else "indexed",
    }


def _error(error: Exception) -> HTTPException:
    if isinstance(error, KeyError):
        return HTTPException(status_code=404, detail="vault_file_not_found")
    if isinstance(error, VaultPathError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, VaultConflictError):
        detail: dict[str, Any] = {"code": error.code}
        if error.actual_hash is not None:
            detail["actual_hash"] = error.actual_hash
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=500, detail="vault_operation_failed")


@router.get("")
@router.get("/files")
def list_files(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
    include_tombstones: bool = False,
):
    with session_scope(_session_factory(request)) as db:
        kb = get_readable_knowledge_base(db, current_user, knowledge_base_id)
        service = _service(request, db, kb, current_user)
        return [_row(row) for row in service.list(include_tombstones=include_tombstones)]


@router.get("/files/{vault_file_id}")
def read_file(
    knowledge_base_id: UUID,
    vault_file_id: UUID,
    request: Request,
    current_user: CurrentUser,
):
    with session_scope(_session_factory(request)) as db:
        kb = get_readable_knowledge_base(db, current_user, knowledge_base_id)
        try:
            row, content = _service(request, db, kb, current_user).read(vault_file_id)
        except (KeyError, VaultConflictError, VaultPathError) as error:
            raise _error(error) from None
        response = _row(row)
        try:
            response["markdown"] = content.decode("utf-8")
        except UnicodeDecodeError:
            response["markdown"] = None
        return response


@router.post("/files", status_code=201)
def create_file(
    knowledge_base_id: UUID,
    payload: WriteRequest,
    request: Request,
    current_user: CurrentUser,
):
    with session_scope(_session_factory(request)) as db:
        kb = get_writable_knowledge_base(db, current_user, knowledge_base_id)
        try:
            result = _service(request, db, kb, current_user).create(
                payload.relative_path, payload.markdown
            )
            return _result(result)
        except (VaultConflictError, VaultPathError) as error:
            raise _error(error) from None


@router.put("/files/{vault_file_id}")
def update_file(
    knowledge_base_id: UUID,
    vault_file_id: UUID,
    payload: UpdateRequest,
    request: Request,
    current_user: CurrentUser,
):
    with session_scope(_session_factory(request)) as db:
        kb = get_writable_knowledge_base(db, current_user, knowledge_base_id)
        try:
            result = _service(request, db, kb, current_user).update(
                vault_file_id, payload.markdown, expected_hash=payload.expected_hash
            )
            return _result(result)
        except (KeyError, VaultConflictError, VaultPathError) as error:
            raise _error(error) from None


@router.post("/files/{vault_file_id}/move")
def move_file(
    knowledge_base_id: UUID,
    vault_file_id: UUID,
    payload: MoveRequest,
    request: Request,
    current_user: CurrentUser,
):
    with session_scope(_session_factory(request)) as db:
        kb = get_writable_knowledge_base(db, current_user, knowledge_base_id)
        try:
            result = _service(request, db, kb, current_user).move(
                vault_file_id,
                payload.relative_path,
                expected_hash=payload.expected_hash,
            )
            return _result(result)
        except (KeyError, VaultConflictError, VaultPathError) as error:
            raise _error(error) from None


@router.delete("/files/{vault_file_id}")
def delete_file(
    knowledge_base_id: UUID,
    vault_file_id: UUID,
    payload: DeleteRequest,
    request: Request,
    current_user: CurrentUser,
):
    with session_scope(_session_factory(request)) as db:
        kb = get_writable_knowledge_base(db, current_user, knowledge_base_id)
        try:
            result = _service(request, db, kb, current_user).delete(
                vault_file_id, expected_hash=payload.expected_hash
            )
            return _result(result)
        except (KeyError, VaultConflictError, VaultPathError) as error:
            raise _error(error) from None


@router.get("/change-sets/{change_set_id}")
def change_set(
    knowledge_base_id: UUID,
    change_set_id: UUID,
    request: Request,
    current_user: CurrentUser,
):
    with session_scope(_session_factory(request)) as db:
        get_readable_knowledge_base(db, current_user, knowledge_base_id)
        row = db.scalar(
            select(VaultChangeSet).where(
                VaultChangeSet.id == change_set_id,
                VaultChangeSet.knowledge_base_id == knowledge_base_id,
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail="vault_change_set_not_found")
        entries = db.scalars(
            select(VaultChangeEntry)
            .where(VaultChangeEntry.change_set_id == row.id)
            .order_by(VaultChangeEntry.ordinal)
        ).all()
        return {
            "id": row.id,
            "state": row.state.value,
            "source": row.source.value,
            "failure_code": row.failure_code,
            "created_at": row.created_at,
            "committed_at": row.committed_at,
            "indexed_at": row.indexed_at,
            "entries": [
                {
                    "vault_file_id": entry.vault_file_id,
                    "ordinal": entry.ordinal,
                    "operation": entry.operation.value,
                    "before_path": entry.before_path,
                    "after_path": entry.after_path,
                    "before_hash": entry.before_hash,
                    "after_hash": entry.after_hash,
                    "size_delta_bytes": entry.size_delta_bytes,
                }
                for entry in entries
            ],
        }
