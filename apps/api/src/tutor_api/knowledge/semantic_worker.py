"""Two-stage deterministic + semantic index planning and atomic activation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tutor_api.knowledge.indexing import (
    MAX_LEXICAL_TERMS,
    EmbeddingAdapter,
    IndexBuildRequest,
    IndexingError,
    _activate_building_index,
    build_index,
    normalize_lexical_terms,
)
from tutor_api.knowledge.models import Chunk, IndexVersion, IndexVersionState
from tutor_api.knowledge.semantic_plan import (
    SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT,
    SemanticIndexPlanPayload,
    validate_semantic_index_plan,
)
from tutor_api.vault.models import (
    SemanticIndexPlan,
    SemanticIndexPlanState,
    VaultFile,
)

_SCHEMA_VERSION = "1.0"
_PROMPT_HASH = hashlib.sha256(
    f"{_SCHEMA_VERSION}\n{SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT}".encode()
).hexdigest()
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class SemanticPlanner(Protocol):
    provider: str
    model: str

    def generate(self, *, prompt: str, source_text: str, source_hash: str) -> object: ...


class RawSidecarWriter(Protocol):
    def write(self, *, plan_id: UUID, raw: bytes) -> str: ...


class SemanticJobState(StrEnum):
    ACTIVE = "active"
    FAILED = "failed"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class SemanticIndexJobResult:
    state: SemanticJobState
    index_version_id: UUID
    semantic_plan_id: UUID
    reused_plan: bool = False
    error_code: str | None = None


class FilesystemRawSidecarWriter:
    """Atomic raw planner output storage for audit without truncation."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write(self, *, plan_id: UUID, raw: bytes) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{plan_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_bytes(raw)
        temporary.replace(target)
        return str(target)


def _planner_prompt(source_hash: str) -> str:
    return (
        f"{SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT}\n"
        f"schema_version={_SCHEMA_VERSION}\nsource_hash={source_hash}\n"
        "只返回符合 SemanticIndexPlan JSON schema 的对象。"
    )


def _public_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and _SAFE_CODE.fullmatch(code):
        return code
    return "semantic_provider_unavailable"


def _validate_plan(payload: object, *, expected_source_hash: str) -> SemanticIndexPlanPayload:
    try:
        return validate_semantic_index_plan(
            payload, expected_source_hash=expected_source_hash
        )
    except ValueError as error:
        raise IndexingError("semantic_plan_invalid") from error


def _discard_prepared_index(session: Session, index_id: UUID, now: datetime) -> None:
    index = session.get(IndexVersion, index_id)
    if index is None or index.state in (IndexVersionState.ACTIVE, IndexVersionState.RETIRED):
        return
    session.execute(delete(Chunk).where(Chunk.index_version_id == index.id))
    index.state = IndexVersionState.FAILED
    index.completed_at = now
    index.activated_at = None
    index.activation_status = "semantic_failed"
    session.flush()


def _raw_bytes(payload: object) -> bytes:
    try:
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError):
        return repr(payload).encode("utf-8", errors="replace")


def _semantic_terms(plan: SemanticIndexPlanPayload) -> tuple[set[str], dict[int, set[str]]]:
    global_terms: list[str] = []
    by_ordinal: dict[int, set[str]] = {}
    for concept in plan.concepts:
        global_terms.extend((concept.name, *concept.aliases, *concept.tags))
    for term in plan.terms:
        global_terms.extend((term.term, term.definition))
    for link in plan.links:
        global_terms.extend((link.source, link.target, link.relation))
    for chunk in plan.chunks:
        by_ordinal[chunk.ordinal] = set(
            normalize_lexical_terms(" ".join((*chunk.concepts, *chunk.tags)))
        )
    return set(normalize_lexical_terms(" ".join(global_terms))), by_ordinal


def _apply_semantic_enrichment(
    session: Session, index: IndexVersion, plan: SemanticIndexPlanPayload
) -> None:
    chunks = list(
        session.scalars(
            select(Chunk).where(Chunk.index_version_id == index.id).order_by(Chunk.ordinal)
        )
    )
    if not chunks:
        raise IndexingError("index_validation_failed")
    global_terms, by_ordinal = _semantic_terms(plan)
    for chunk in chunks:
        merged = set(chunk.lexical_terms)
        merged.update(global_terms)
        merged.update(by_ordinal.get(chunk.ordinal, ()))
        chunk.lexical_terms = sorted(merged)[:MAX_LEXICAL_TERMS]
    session.flush()
    persisted = list(
        session.scalars(
            select(Chunk).where(Chunk.index_version_id == index.id).order_by(Chunk.ordinal)
        )
    )
    if len(persisted) != len(chunks) or any(
        chunk.content_sha256 != hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        or chunk.index_signature != index.index_signature
        for chunk in persisted
    ):
        raise IndexingError("index_validation_failed")


def _load_or_create_plan(
    session: Session,
    *,
    vault_file: VaultFile,
    planner: SemanticPlanner,
    change_set_id: UUID | None,
) -> tuple[SemanticIndexPlan, bool]:
    plan = session.scalar(
        select(SemanticIndexPlan).where(
            SemanticIndexPlan.vault_file_id == vault_file.id,
            SemanticIndexPlan.input_hash == vault_file.content_hash,
            SemanticIndexPlan.schema_version == _SCHEMA_VERSION,
            SemanticIndexPlan.prompt_hash == _PROMPT_HASH,
        )
    )
    if plan is not None:
        reusable = (
            plan.state
            in (
                SemanticIndexPlanState.VALIDATED,
                SemanticIndexPlanState.APPLIED,
            )
            and plan.payload is not None
        )
        plan.change_set_id = change_set_id
        if reusable:
            return plan, True
        plan.provider = planner.provider
        plan.model = planner.model
        plan.state = SemanticIndexPlanState.PENDING
        plan.retry_count += 1
        plan.failure_code = None
        plan.validation_errors = []
        plan.payload = None
        plan.raw_sidecar_reference = None
        return plan, False
    plan = SemanticIndexPlan(
        space_id=vault_file.space_id,
        knowledge_base_id=vault_file.knowledge_base_id,
        vault_file_id=vault_file.id,
        change_set_id=change_set_id,
        input_hash=vault_file.content_hash,
        provider=planner.provider,
        model=planner.model,
        schema_version=_SCHEMA_VERSION,
        prompt_hash=_PROMPT_HASH,
        state=SemanticIndexPlanState.PENDING,
    )
    session.add(plan)
    session.flush()
    return plan, False


def run_semantic_index_job(
    session: Session,
    *,
    request: IndexBuildRequest,
    adapter: EmbeddingAdapter,
    vault_file_id: UUID,
    source_text: str,
    planner: SemanticPlanner,
    sidecar_writer: RawSidecarWriter,
    now: datetime | None = None,
) -> SemanticIndexJobResult:
    """Prepare deterministic chunks, validate semantic output, then atomically activate."""

    timestamp = now or datetime.now(UTC)
    vault_file = session.get(VaultFile, vault_file_id)
    if (
        vault_file is None
        or vault_file.knowledge_base_id != request.knowledge_base_id
        or vault_file.space_id != request.space_id
        or vault_file.is_tombstoned
    ):
        raise IndexingError("semantic_source_invalid")
    source_hash = vault_file.content_hash
    prepared_request = replace(request, source_snapshot_hash=source_hash, semantic_plan_id=None)
    deterministic = build_index(session, prepared_request, adapter, now=timestamp, activate=False)
    index = session.get(IndexVersion, deterministic.index_version_id)
    if index is None:
        raise IndexingError("index_validation_failed")
    plan, reused = _load_or_create_plan(
        session,
        vault_file=vault_file,
        planner=planner,
        change_set_id=request.source_change_set_id,
    )
    try:
        if reused:
            validated = _validate_plan(plan.payload, expected_source_hash=source_hash)
        else:
            plan.state = SemanticIndexPlanState.VALIDATING
            session.flush()
            raw_payload = planner.generate(
                prompt=_planner_prompt(source_hash),
                source_text=source_text,
                source_hash=source_hash,
            )
            raw = _raw_bytes(raw_payload)
            plan.raw_sidecar_reference = sidecar_writer.write(plan_id=plan.id, raw=raw)
            session.refresh(vault_file)
            if vault_file.content_hash != source_hash or vault_file.is_tombstoned:
                plan.state = SemanticIndexPlanState.STALE
                plan.failure_code = "semantic_source_stale"
                _discard_prepared_index(session, index.id, timestamp)
                return SemanticIndexJobResult(
                    SemanticJobState.STALE,
                    index.id,
                    plan.id,
                    error_code="semantic_source_stale",
                )
            validated = _validate_plan(raw_payload, expected_source_hash=source_hash)
            plan.payload = validated.model_dump(mode="json")
            plan.state = SemanticIndexPlanState.VALIDATED
            plan.failure_code = None
            plan.validation_errors = []
            session.flush()

        with session.begin_nested():
            _apply_semantic_enrichment(session, index, validated)
            index.planner_provider = plan.provider
            index.planner_model = plan.model
            index.planner_schema_version = plan.schema_version
            index.planner_prompt_hash = plan.prompt_hash
            index.source_snapshot_hash = source_hash
            index.source_change_set_id = request.source_change_set_id
            index.activation_status = "semantic_ready"
            _activate_building_index(session, index, timestamp)
            index.activation_status = "semantic_active"
            plan.index_version_id = index.id
            plan.state = SemanticIndexPlanState.APPLIED
            vault_file.last_index_version_id = index.id
            session.flush()
    except Exception as error:
        plan.state = SemanticIndexPlanState.FAILED
        plan.failure_code = _public_error_code(error)
        plan.validation_errors = [{"code": plan.failure_code}]
        _discard_prepared_index(session, index.id, timestamp)
        return SemanticIndexJobResult(
            SemanticJobState.FAILED,
            index.id,
            plan.id,
            reused_plan=reused,
            error_code=plan.failure_code,
        )

    return SemanticIndexJobResult(
        SemanticJobState.ACTIVE,
        index.id,
        plan.id,
        reused_plan=reused,
    )
