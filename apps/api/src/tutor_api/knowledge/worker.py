"""Database-leased ingestion worker primitives."""

from __future__ import annotations

import hashlib
import re
import sys
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.knowledge.candidates import CandidateValidationError
from tutor_api.knowledge.indexing import (
    ChunkingConfig,
    EmbeddingAdapter,
    IndexBuildRequest,
    IndexingError,
    build_index,
    make_pipeline_signature,
    prepare_index_build,
)
from tutor_api.knowledge.markdown import (
    MarkdownSourceBlock,
    build_knowledge_candidates_prompt,
    build_structure_candidates_prompt,
    merge_knowledge_candidates,
    merge_structure_candidates,
    parse_knowledge_candidates,
    parse_structure_candidates,
    split_for_context,
)
from tutor_api.knowledge.models import (
    Block,
    CandidateBatchState,
    Chunk,
    Document,
    DocumentVersion,
    DocumentVersionState,
    IndexVersion,
    IndexVersionState,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeCandidateBatch,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
    Page,
)
from tutor_api.knowledge.ocr import (
    DisabledOCRAdapter,
    OCRAdapter,
    OCRError,
    OCRErrorCode,
    OCRPageStatus,
    PDFiumPageRenderer,
    PDFPageRenderer,
    apply_selective_ocr,
)
from tutor_api.knowledge.parsers import (
    ParsedDocument,
    parse_docx,
    parse_jpeg,
    parse_markdown,
    parse_obsidian_vault_zip,
    parse_pdf,
    parse_png,
)
from tutor_api.knowledge.semantic_worker import (
    FilesystemRawSidecarWriter,
    SemanticIndexJobResult,
    SemanticJobState,
    SemanticPlanner,
    run_semantic_index_job,
)
from tutor_api.knowledge.service import (
    enqueue_index_build,
    persist_parsed_document_and_enqueue_build,
)
from tutor_api.knowledge.storage import ObjectStorage
from tutor_api.llm.ports import MarkdownLlmAdapter
from tutor_api.vault.models import (
    VaultChangeEntry,
    VaultChangeOperation,
    VaultChangeSet,
    VaultChangeSetState,
    VaultFile,
    VaultFileKind,
    VaultSyncCursor,
)
from tutor_api.vault.sync import VaultSyncService

_WORKER_INVOCATION_TIME: ContextVar[datetime | None] = ContextVar(
    "worker_invocation_time", default=None
)

JobHandler = Callable[[Session, IngestionJob], None]


class DurableJobKind(StrEnum):
    """Logical jobs carried by the existing leased ingestion queue.

    The database schema predates workspace jobs, so the durable logical kind is
    stored in the checkpoint while the immutable transport kind remains a valid
    existing IngestionJobKind. This preserves old rows and queue behavior.
    """

    VAULT_SCAN = "vault_scan"
    VAULT_PROJECT = "vault_project"
    SEMANTIC_PLAN = "semantic_plan"


WorkerJobKind = IngestionJobKind | DurableJobKind
WorkerHandlers = Mapping[WorkerJobKind, JobHandler]
_WORKER_JOB_KIND_KEY = "worker_job_kind"
_SEMANTIC_JOB_IDS_KEY = "semantic_job_ids"
_SEMANTIC_VAULT_FILE_IDS_KEY = "semantic_vault_file_ids"
_SEMANTIC_EXPECTATION_INITIALIZED_KEY = "semantic_expectation_initialized"
_DURABLE_TRANSPORT_KIND = {
    DurableJobKind.VAULT_SCAN: IngestionJobKind.BUILD_INDEX,
    DurableJobKind.VAULT_PROJECT: IngestionJobKind.BUILD_INDEX,
    DurableJobKind.SEMANTIC_PLAN: IngestionJobKind.BUILD_INDEX,
}
_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _optional_checkpoint_uuid(checkpoint: Mapping[str, object], key: str) -> UUID | None:
    raw = checkpoint.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError
    parsed = UUID(raw)
    if str(parsed) != raw:
        raise ValueError
    return parsed


def _optional_checkpoint_sha256(checkpoint: Mapping[str, object], key: str) -> str | None:
    raw = checkpoint.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or _SHA256.fullmatch(raw) is None:
        raise ValueError
    return raw


def _required_checkpoint_sha256(checkpoint: Mapping[str, object], key: str) -> str:
    value = _optional_checkpoint_sha256(checkpoint, key)
    if value is None:
        raise ValueError
    return value


def _required_checkpoint_uuid(checkpoint: Mapping[str, object], key: str) -> UUID:
    value = _optional_checkpoint_uuid(checkpoint, key)
    if value is None:
        raise ValueError
    return value


def _required_checkpoint_string(checkpoint: Mapping[str, object], key: str) -> str:
    value = checkpoint.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError
    return value


def _required_checkpoint_int(checkpoint: Mapping[str, object], key: str) -> int:
    value = checkpoint.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError
    return value


def _checkpoint_uuid_tuple(checkpoint: Mapping[str, object], key: str) -> tuple[UUID, ...]:
    raw = checkpoint.get(key)
    if not isinstance(raw, list) or not raw:
        raise ValueError
    values = tuple(UUID(value) for value in raw if isinstance(value, str))
    if len(values) != len(raw) or len(set(values)) != len(values):
        raise ValueError
    return values


def _durable_job_kind(job: IngestionJob) -> DurableJobKind | None:
    raw = job.checkpoint.get(_WORKER_JOB_KIND_KEY)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise WorkerPublicError("worker_job_kind_invalid")
    try:
        logical = DurableJobKind(raw)
    except ValueError:
        raise WorkerPublicError("worker_job_kind_invalid") from None
    expected_transport = _DURABLE_TRANSPORT_KIND[logical]
    if job.kind is not expected_transport:
        raise WorkerPublicError("worker_job_transport_invalid")
    return logical


def _logical_checkpoint_expression():
    return IngestionJob.checkpoint[_WORKER_JOB_KIND_KEY].as_string()


def _job_kind_filter(
    kinds: tuple[IngestionJobKind, ...] | None,
    logical_kinds: tuple[DurableJobKind, ...] | None,
):
    alternatives = []
    logical_expression = _logical_checkpoint_expression()
    if kinds:
        durable_transports = set(_DURABLE_TRANSPORT_KIND.values())
        for kind in kinds:
            direct = IngestionJob.kind == kind
            if kind in durable_transports:
                direct = and_(direct, logical_expression.is_(None))
            alternatives.append(direct)
    if logical_kinds:
        transports = tuple({_DURABLE_TRANSPORT_KIND[kind] for kind in logical_kinds})
        requested = and_(
            IngestionJob.kind.in_(transports),
            logical_expression.in_(tuple(kind.value for kind in logical_kinds)),
        )
        unknown = and_(
            IngestionJob.kind.in_(transports),
            logical_expression.is_not(None),
            logical_expression.not_in(tuple(kind.value for kind in DurableJobKind)),
        )
        alternatives.append(or_(requested, unknown))
    if not alternatives:
        return None
    return alternatives[0] if len(alternatives) == 1 else or_(*alternatives)


class FormulaEvidenceProvider(Protocol):
    def collect(self, source_text: str) -> tuple[dict[str, str], ...]: ...


class CodedWorkerError(Protocol):
    code: object


class WorkerPublicError(RuntimeError):
    """Stable, detail-free error emitted by the parse worker boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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


def claim_job_statement(
    now: datetime,
    kinds: tuple[IngestionJobKind, ...] | None = None,
    logical_kinds: tuple[DurableJobKind, ...] | None = None,
):
    runnable = and_(
        IngestionJob.state.in_((IngestionJobState.QUEUED, IngestionJobState.RETRY_WAIT)),
        IngestionJob.available_at <= now,
    )
    stale = and_(
        IngestionJob.state == IngestionJobState.RUNNING,
        IngestionJob.lease_expires_at <= now,
    )
    filters = [
        or_(runnable, stale),
        IngestionJob.attempt_count < IngestionJob.max_attempts,
    ]
    kind_filter = _job_kind_filter(kinds, logical_kinds)
    if kind_filter is not None:
        filters.append(kind_filter)
    return (
        select(IngestionJob)
        .where(*filters)
        .order_by(IngestionJob.available_at, IngestionJob.created_at, IngestionJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


_STALE_FAILURE_BATCH_SIZE = 100


def _terminally_fail_parse_target(session: Session, job: IngestionJob) -> None:
    if job.kind is not IngestionJobKind.PARSE_DOCUMENT or job.document_version_id is None:
        return
    version = session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.id == job.document_version_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if version is not None:
        version.state = DocumentVersionState.FAILED


def _worker_now() -> datetime:
    return _WORKER_INVOCATION_TIME.get() or datetime.now(UTC)


def _terminally_fail_build_target(session: Session, job: IngestionJob, now: datetime) -> None:
    if job.kind is not IngestionJobKind.BUILD_INDEX or job.index_version_id is None:
        return
    try:
        logical_kind = _durable_job_kind(job)
    except WorkerPublicError:
        return
    if logical_kind in (
        DurableJobKind.VAULT_SCAN,
        DurableJobKind.VAULT_PROJECT,
        DurableJobKind.SEMANTIC_PLAN,
    ):
        return
    index = session.scalar(
        select(IndexVersion)
        .where(IndexVersion.id == job.index_version_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if index is None or index.state not in (
        IndexVersionState.BUILDING,
        IndexVersionState.READY,
        IndexVersionState.FAILED,
    ):
        return
    session.execute(delete(Chunk).where(Chunk.index_version_id == index.id))
    index.state = IndexVersionState.FAILED
    index.completed_at = now
    index.activated_at = None


def _record_candidate_failure(
    session: Session,
    job: IngestionJob,
    *,
    terminal: bool,
) -> None:
    if job.kind is not IngestionJobKind.GENERATE_MARKDOWN:
        return
    raw_batch_id = job.checkpoint.get("candidate_batch_id")
    try:
        batch_id = UUID(raw_batch_id)
    except (TypeError, ValueError, AttributeError):
        return
    batch = session.scalar(
        select(KnowledgeCandidateBatch)
        .where(KnowledgeCandidateBatch.id == batch_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if batch is None:
        return
    batch.failure_code = job.last_error_code
    if terminal:
        batch.state = CandidateBatchState.FAILED



def _record_durable_failure(
    session: Session,
    job: IngestionJob,
    *,
    error_code: str,
    terminal: bool,
) -> None:
    try:
        logical_kind = _durable_job_kind(job)
    except WorkerPublicError:
        return
    if logical_kind is None:
        return
    if logical_kind is DurableJobKind.VAULT_SCAN:
        cursor = session.scalar(
            select(VaultSyncCursor)
            .where(
                VaultSyncCursor.knowledge_base_id == job.knowledge_base_id,
                VaultSyncCursor.space_id == job.space_id,
            )
            .with_for_update()
        )
        if cursor is None:
            cursor = VaultSyncCursor(
                space_id=job.space_id,
                knowledge_base_id=job.knowledge_base_id,
            )
            session.add(cursor)
        cursor.requires_full_scan = True
        cursor.pending_count = max(cursor.pending_count or 0, 1)
        cursor.last_error = error_code

    checkpoint_key = (
        "source_change_set_id"
        if logical_kind is DurableJobKind.SEMANTIC_PLAN
        else "change_set_id"
    )
    try:
        change_set_id = _optional_checkpoint_uuid(job.checkpoint, checkpoint_key)
    except (AttributeError, TypeError, ValueError):
        change_set_id = None
    if change_set_id is None:
        return
    change_set = session.scalar(
        select(VaultChangeSet)
        .where(
            VaultChangeSet.id == change_set_id,
            VaultChangeSet.knowledge_base_id == job.knowledge_base_id,
            VaultChangeSet.space_id == job.space_id,
        )
        .with_for_update()
    )
    if change_set is None:
        return
    change_set.retry_count = max(change_set.retry_count, job.attempt_count)
    if terminal:
        change_set.state = VaultChangeSetState.FAILED
        change_set.failure_code = error_code
        change_set.failure_message = None


def _fail_exhausted_stale_jobs(
    session: Session,
    now: datetime,
    kinds: tuple[IngestionJobKind, ...] | None = None,
    logical_kinds: tuple[DurableJobKind, ...] | None = None,
) -> None:
    filters = [
        IngestionJob.state == IngestionJobState.RUNNING,
        IngestionJob.lease_expires_at <= now,
        IngestionJob.attempt_count >= IngestionJob.max_attempts,
    ]
    kind_filter = _job_kind_filter(kinds, logical_kinds)
    if kind_filter is not None:
        filters.append(kind_filter)
    jobs = session.scalars(
        select(IngestionJob)
        .where(*filters)
        .order_by(
            IngestionJob.lease_expires_at,
            IngestionJob.created_at,
            IngestionJob.id,
        )
        .limit(_STALE_FAILURE_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    ).all()
    for job in jobs:
        _terminally_fail_build_target(session, job, now)
        _terminally_fail_parse_target(session, job)
        job.state = IngestionJobState.FAILED
        job.lease_owner = None
        job.lease_expires_at = None
        job.completed_at = now
        job.last_error_code = "worker_lease_exhausted"
        job.last_error_detail = None
        _record_durable_failure(
            session, job, error_code="worker_lease_exhausted", terminal=True
        )
    session.flush()


def claim_next_job(
    session: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_duration: timedelta = timedelta(minutes=5),
    kinds: tuple[IngestionJobKind, ...] | None = None,
    logical_kinds: tuple[DurableJobKind, ...] | None = None,
) -> IngestionJob | None:
    """Atomically lease one runnable job; SQLite is a single-worker test fallback only."""

    if not worker_id or len(worker_id) > 255:
        raise ValueError("worker_id must be between 1 and 255 characters")
    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be positive")
    timestamp = now or datetime.now(UTC)
    _fail_exhausted_stale_jobs(session, timestamp, kinds, logical_kinds)
    job = session.scalar(claim_job_statement(timestamp, kinds, logical_kinds))
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
    if isinstance(error, CandidateValidationError):
        raw = str(error).partition(":")[0]
    else:
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
        _record_candidate_failure(session, job, terminal=False)
    else:
        job.state = IngestionJobState.FAILED
        job.completed_at = timestamp
        _terminally_fail_build_target(session, job, timestamp)
        _terminally_fail_parse_target(session, job)
        _record_candidate_failure(session, job, terminal=True)
    _record_durable_failure(
        session,
        job,
        error_code=job.last_error_code,
        terminal=job.state is IngestionJobState.FAILED,
    )
    session.flush()
    return job


def _parse_uploaded_document(
    data: bytes,
    *,
    content_type: str,
    source_name: str,
    max_vault_files: int,
    max_vault_uncompressed_bytes: int,
) -> ParsedDocument:
    if content_type == "application/pdf":
        return parse_pdf(data, source_name=source_name)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return parse_docx(data, source_name=source_name)
    if content_type == "text/markdown":
        return parse_markdown(data, source_name=source_name)
    if content_type == "image/png":
        return parse_png(data, source_name=source_name)
    if content_type == "image/jpeg":
        return parse_jpeg(data, source_name=source_name)
    if content_type == "application/zip":
        vault = parse_obsidian_vault_zip(
            data,
            max_files=max_vault_files,
            max_uncompressed_bytes=max_vault_uncompressed_bytes,
        )
        return ParsedDocument(
            source_name=source_name,
            media_type=content_type,
            blocks=tuple(block for note in vault.notes for block in note.document.blocks),
            wikilinks=vault.wikilinks,
        )
    raise WorkerPublicError("unsupported_content_type")


def _component_signature_config(component: object) -> dict[str, object]:
    """Expose only deterministic public runtime configuration to pipeline signatures."""

    result: dict[str, object] = {
        "type": f"{type(component).__module__}.{type(component).__qualname__}",
    }
    if is_dataclass(component) and not isinstance(component, type):
        for item in fields(component):
            value = getattr(component, item.name)
            if isinstance(value, (str, int, float, bool)) or value is None:
                result[item.name] = value
    return result


def make_parse_document_handler(
    object_storage: ObjectStorage,
    embedding_adapter: EmbeddingAdapter,
    *,
    ocr_adapter: OCRAdapter | None = None,
    renderer: PDFPageRenderer | None = None,
    ocr_languages: tuple[str, ...] = ("eng", "chi_sim"),
    chunking: ChunkingConfig | None = None,
    max_vault_files: int = 5_000,
    max_vault_uncompressed_bytes: int = 500 * 1024 * 1024,
) -> JobHandler:
    """Create the production PARSE_DOCUMENT handler over shared runtime boundaries."""

    active_ocr = ocr_adapter or DisabledOCRAdapter()
    active_renderer = renderer if renderer is not None else PDFiumPageRenderer()
    active_chunking = chunking or ChunkingConfig()
    parser_signature = make_pipeline_signature(
        "parser",
        "native-upload",
        "2",
        {
            "max_vault_files": max_vault_files,
            "max_vault_uncompressed_bytes": max_vault_uncompressed_bytes,
            "supported_content_types": [
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "text/markdown",
                "image/jpeg",
                "image/png",
                "application/zip",
            ],
        },
    )
    ocr_signature = make_pipeline_signature(
        "ocr",
        active_ocr.backend,
        "2",
        {
            "adapter": _component_signature_config(active_ocr),
            "languages": list(ocr_languages),
            "renderer": _component_signature_config(active_renderer),
        },
    )

    def handle(session: Session, job: IngestionJob) -> None:
        if job.kind is not IngestionJobKind.PARSE_DOCUMENT or job.document_version_id is None:
            raise RuntimeError("parse_job_target_invalid")
        version = session.get(DocumentVersion, job.document_version_id)
        if version is None or version.document_id != job.document_id:
            raise RuntimeError("parse_job_target_invalid")
        document = session.get(Document, version.document_id)
        if document is None:
            raise RuntimeError("parse_job_target_invalid")
        stored = object_storage.get_object(version.object_key)
        if (
            stored.content_type != version.content_type
            or hashlib.sha256(stored.data).hexdigest() != version.content_sha256
        ):
            raise WorkerPublicError("object_content_mismatch")
        version.state = DocumentVersionState.PARSING
        parsed = _parse_uploaded_document(
            stored.data,
            content_type=version.content_type,
            source_name=document.source_key,
            max_vault_files=max_vault_files,
            max_vault_uncompressed_bytes=max_vault_uncompressed_bytes,
        )
        if parsed.needs_ocr:
            ocr_result = apply_selective_ocr(
                parsed,
                stored.data,
                adapter=active_ocr,
                renderer=active_renderer,
                languages=ocr_languages,
            )
            failed_checkpoint = next(
                (
                    checkpoint
                    for checkpoint in ocr_result.checkpoints
                    if checkpoint.status is OCRPageStatus.FAILED
                ),
                None,
            )
            if failed_checkpoint is not None:
                raise OCRError(failed_checkpoint.error_code or OCRErrorCode.PROCESSING_FAILED)
            parsed = ocr_result.document
            if parsed.needs_ocr:
                raise WorkerPublicError("ocr_unavailable")
            if not parsed.blocks:
                raise WorkerPublicError("ocr_empty_result")
        build_job = persist_parsed_document_and_enqueue_build(
            session,
            document_version_id=version.id,
            parsed_document=parsed,
            parser_signature=parser_signature,
            ocr_signature=ocr_signature,
            chunking=active_chunking,
            embedding_adapter=embedding_adapter,
            object_storage=object_storage,
        )
        job.checkpoint["build_job_id"] = str(build_job.id)

    return handle


def make_markdown_draft_handler(
    adapter: MarkdownLlmAdapter,
    *,
    max_chars: int = 60_000,
    max_concurrency: int = 1,
    provider: str = "faro",
    model: str | None = None,
    formula_evidence_provider: FormulaEvidenceProvider | None = None,
) -> JobHandler:
    """Generate review-only knowledge candidates from persisted parsed blocks."""

    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be positive")

    def handle(session: Session, job: IngestionJob) -> None:
        if (
            job.kind is not IngestionJobKind.GENERATE_MARKDOWN
            or job.document_id is None
            or job.document_version_id is None
        ):
            raise WorkerPublicError("candidate_job_target_invalid")
        raw_batch_id = job.checkpoint.get("candidate_batch_id")
        try:
            batch_id = UUID(raw_batch_id)
        except (TypeError, ValueError, AttributeError):
            raise WorkerPublicError("candidate_job_checkpoint_invalid") from None
        batch = session.get(KnowledgeCandidateBatch, batch_id)
        if (
            batch is None
            or batch.space_id != job.space_id
            or batch.knowledge_base_id != job.knowledge_base_id
            or batch.document_id != job.document_id
            or batch.document_version_id != job.document_version_id
        ):
            raise WorkerPublicError("candidate_job_target_invalid")
        if batch.state is CandidateBatchState.NEEDS_REVIEW:
            return
        if batch.state is not CandidateBatchState.PROCESSING:
            raise WorkerPublicError("candidate_batch_not_processing")
        if adapter is None:
            raise WorkerPublicError("llm_provider_unavailable")

        rows = session.execute(
            select(Block, Page.page_number)
            .join(Page, Block.page_id == Page.id)
            .where(
                Page.document_version_id == job.document_version_id,
                Block.text.is_not(None),
            )
            .order_by(Page.page_number, Block.ordinal, Block.id)
        ).all()
        source_blocks = tuple(
            MarkdownSourceBlock(
                source_pointer=block.source_pointer,
                page_number=page_number,
                text=block.text or "",
            )
            for block, page_number in rows
        )
        chunks = split_for_context(source_blocks, max_chars=max_chars)
        if not chunks:
            raise WorkerPublicError("candidate_source_empty")

        structure_prompts = tuple(
            build_structure_candidates_prompt(chunk.source_text) for chunk in chunks
        )
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            structure_completions = tuple(
                executor.map(adapter.complete_markdown, structure_prompts)
            )
        structure_groups = [
            parse_structure_candidates(completion.text) for completion in structure_completions
        ]
        last_request_id = None
        for completion in structure_completions:
            last_request_id = completion.request_id or last_request_id
        structures = merge_structure_candidates(tuple(structure_groups))

        if formula_evidence_provider is None:
            evidence_groups: tuple[tuple[dict[str, str], ...], ...] = tuple(() for _ in chunks)
        else:
            with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
                evidence_groups = tuple(
                    executor.map(
                        formula_evidence_provider.collect,
                        (chunk.source_text for chunk in chunks),
                    )
                )
        candidate_prompts = tuple(
            build_knowledge_candidates_prompt(
                chunk.source_text,
                structures=structures,
                external_formula_evidence=evidence,
            )
            for chunk, evidence in zip(chunks, evidence_groups, strict=True)
        )
        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            candidate_completions = tuple(
                executor.map(adapter.complete_markdown, candidate_prompts)
            )
        candidate_groups = [
            parse_knowledge_candidates(completion.text) for completion in candidate_completions
        ]
        for completion in candidate_completions:
            last_request_id = completion.request_id or last_request_id
        candidates = merge_knowledge_candidates(tuple(candidate_groups))

        session.execute(
            delete(KnowledgeCandidateLink).where(KnowledgeCandidateLink.batch_id == batch.id)
        )
        session.execute(
            delete(KnowledgeCandidateNote).where(KnowledgeCandidateNote.batch_id == batch.id)
        )
        pending = {note.key: note for note in candidates.notes}
        ordered_notes = []
        persisted_keys: set[str] = set()
        while pending:
            ready = [
                note
                for note in pending.values()
                if note.parent_key is None or note.parent_key in persisted_keys
            ]
            if not ready:
                raise WorkerPublicError("candidate_parent_order_invalid")
            for note in ready:
                ordered_notes.append(note)
                persisted_keys.add(note.key)
                pending.pop(note.key)

        for ordinal, note in enumerate(ordered_notes):
            verification = note.formula_verification
            verification_payload = (
                {
                    "status": verification.status.value,
                    "textbook_expression": verification.textbook_expression,
                    "normalized_expression": verification.normalized_expression,
                    "variable_mapping": [
                        {
                            "textbook_symbol": mapping.textbook_symbol,
                            "external_symbol": mapping.external_symbol,
                            "meaning": mapping.meaning,
                            "unit": mapping.unit,
                        }
                        for mapping in verification.variable_mapping
                    ],
                }
                if verification is not None
                else None
            )
            external_source_payload = [
                {
                    "title": source.title,
                    "url": source.url,
                    "source_type": source.source_type,
                    "excerpt": source.excerpt,
                }
                for source in note.external_sources
            ]
            session.add(
                KnowledgeCandidateNote(
                    space_id=batch.space_id,
                    knowledge_base_id=batch.knowledge_base_id,
                    batch_id=batch.id,
                    ordinal=ordinal,
                    candidate_key=note.key,
                    title=note.title,
                    normalized_title=" ".join(note.title.casefold().split()),
                    kind=note.kind,
                    parent_key=note.parent_key,
                    markdown=note.markdown,
                    source_pointers=list(note.source_pointers),
                    formula_verification=verification_payload,
                    external_sources=external_source_payload,
                )
            )
        session.flush()
        for ordinal, link in enumerate(candidates.links):
            session.add(
                KnowledgeCandidateLink(
                    space_id=batch.space_id,
                    knowledge_base_id=batch.knowledge_base_id,
                    batch_id=batch.id,
                    ordinal=ordinal,
                    kind=link.kind,
                    relation=link.relation,
                    source_key=link.source_key,
                    target_key=link.target_key,
                    source_pointer=link.source_pointer,
                    occurrence=link.occurrence,
                    context=link.context,
                )
            )

        batch.state = CandidateBatchState.NEEDS_REVIEW
        batch.generation_provider = provider
        batch.generation_model = model
        batch.generation_request_id = last_request_id
        batch.failure_code = None
        job.checkpoint["candidate_note_count"] = len(candidates.notes)
        job.checkpoint["candidate_link_count"] = len(candidates.links)
        job.checkpoint["structure_count"] = len(structures)
        job.checkpoint["external_formula_source_count"] = sum(
            len(group) for group in evidence_groups
        )

    return handle


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
            if not isinstance(raw_version_ids, list) or not 1 <= len(raw_version_ids) <= 10_000:
                raise ValueError
            version_ids = tuple(UUID(value) for value in raw_version_ids)
            if any(
                not isinstance(value, str) or str(parsed) != value
                for value, parsed in zip(raw_version_ids, version_ids, strict=True)
            ):
                raise ValueError
            chunking = ChunkingConfig(
                max_chars=checkpoint["chunk_max_chars"],
                overlap_chars=checkpoint["chunk_overlap_chars"],
            )
            parser_signature = checkpoint["parser_signature"]
            ocr_signature = checkpoint["ocr_signature"]
            source_snapshot_hash = _optional_checkpoint_sha256(checkpoint, "source_snapshot_hash")
            source_change_set_id = _optional_checkpoint_uuid(checkpoint, "source_change_set_id")
            semantic_plan_id = _optional_checkpoint_uuid(checkpoint, "semantic_plan_id")
        except (KeyError, TypeError, ValueError):
            raise IndexingError("index_job_checkpoint_invalid") from None
        if (
            not isinstance(parser_signature, str)
            or not isinstance(ocr_signature, str)
            or not 1 <= len(parser_signature) <= 255
            or not 1 <= len(ocr_signature) <= 255
        ):
            raise IndexingError("index_job_checkpoint_invalid")
        request = IndexBuildRequest(
            space_id=job.space_id,
            knowledge_base_id=job.knowledge_base_id,
            created_by_user_id=index.created_by_user_id,
            document_version_ids=version_ids,
            parser_signature=parser_signature,
            ocr_signature=ocr_signature,
            chunking=chunking,
            source_snapshot_hash=source_snapshot_hash,
            source_change_set_id=source_change_set_id,
            semantic_plan_id=semantic_plan_id,
        )
        current_target = prepare_index_build(session, request, adapter)
        job_target = session.scalar(
            select(IndexVersion)
            .where(IndexVersion.id == job.index_version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job_target is None:
            raise IndexingError("index_job_target_invalid")
        same_embedding_contract = (
            job_target.embedding_backend == current_target.embedding_backend
            and job_target.embedding_model == current_target.embedding_model
            and job_target.embedding_dimension == current_target.embedding_dimension
            and job_target.embedding_contract_signature
            == current_target.embedding_contract_signature
        )
        if not same_embedding_contract or job_target.id != current_target.id:
            # A BUILD_INDEX job is permanently bound to its original target.  Its
            # unactivated target never received the current adapter's vectors, so
            # FAILED is the stable terminal state used for other unsuccessful builds.
            _terminally_fail_build_target(session, job, _worker_now())
            enqueue_index_build(
                session,
                request=request,
                embedding_adapter=adapter,
                knowledge_base_locked=True,
            )
            return
        result = build_index(session, request, adapter)
        if result.index_version_id != job_target.id:
            raise IndexingError("index_job_signature_mismatch")
        job.checkpoint["chunk_count"] = result.chunk_count
        job.checkpoint["index_version_id"] = str(result.index_version_id)

    return handle


def _durable_job_checkpoint_error(logical_kind: DurableJobKind) -> str:
    return {
        DurableJobKind.VAULT_SCAN: "vault_scan_checkpoint_invalid",
        DurableJobKind.VAULT_PROJECT: "vault_project_checkpoint_invalid",
        DurableJobKind.SEMANTIC_PLAN: "semantic_job_checkpoint_invalid",
    }[logical_kind]


def _existing_durable_job_matches_enqueue(
    existing: IngestionJob,
    *,
    parent: IngestionJob,
    logical_kind: DurableJobKind,
    checkpoint: Mapping[str, object],
) -> bool:
    if (
        existing.space_id != parent.space_id
        or existing.knowledge_base_id != parent.knowledge_base_id
        or existing.index_version_id != parent.index_version_id
        or existing.created_by_user_id != parent.created_by_user_id
        or existing.kind is not _DURABLE_TRANSPORT_KIND[logical_kind]
        or existing.checkpoint.get(_WORKER_JOB_KIND_KEY) != logical_kind.value
    ):
        return False
    return all(
        key in existing.checkpoint and existing.checkpoint[key] == value
        for key, value in checkpoint.items()
    )


def _enqueue_durable_job(
    session: Session,
    *,
    parent: IngestionJob,
    logical_kind: DurableJobKind,
    idempotency_key: str,
    checkpoint: dict[str, object],
) -> IngestionJob:
    existing = session.scalar(
        select(IngestionJob).where(
            IngestionJob.knowledge_base_id == parent.knowledge_base_id,
            IngestionJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if not _existing_durable_job_matches_enqueue(
            existing,
            parent=parent,
            logical_kind=logical_kind,
            checkpoint=checkpoint,
        ):
            raise WorkerPublicError(_durable_job_checkpoint_error(logical_kind))
        return existing
    if parent.index_version_id is None:
        raise WorkerPublicError("worker_job_target_invalid")
    payload = dict(checkpoint)
    payload[_WORKER_JOB_KIND_KEY] = logical_kind.value
    queued = IngestionJob(
        space_id=parent.space_id,
        knowledge_base_id=parent.knowledge_base_id,
        index_version_id=parent.index_version_id,
        kind=_DURABLE_TRANSPORT_KIND[logical_kind],
        state=IngestionJobState.QUEUED,
        idempotency_key=idempotency_key,
        max_attempts=parent.max_attempts,
        available_at=parent.available_at,
        checkpoint=payload,
        created_by_user_id=parent.created_by_user_id,
    )
    session.add(queued)
    session.flush()
    return queued


def _semantic_contract_checkpoint(
    session: Session, job: IngestionJob
) -> dict[str, object] | None:
    keys = (
        "document_version_ids",
        "parser_signature",
        "ocr_signature",
        "chunk_max_chars",
        "chunk_overlap_chars",
    )
    if all(key in job.checkpoint for key in keys):
        return {key: job.checkpoint[key] for key in keys}
    if job.index_version_id is None:
        return None
    index = session.get(IndexVersion, job.index_version_id)
    chunking = ChunkingConfig()
    if index is None or index.chunking_signature != chunking.signature:
        return None
    versions = session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.knowledge_base_id == job.knowledge_base_id,
            DocumentVersion.space_id == job.space_id,
            DocumentVersion.state == DocumentVersionState.READY,
        )
        .order_by(DocumentVersion.document_id, DocumentVersion.version_number.desc())
    )
    latest: dict[UUID, UUID] = {}
    for version in versions:
        latest.setdefault(version.document_id, version.id)
    if not latest:
        return None
    return {
        "document_version_ids": [str(value) for value in sorted(latest.values(), key=str)],
        "parser_signature": index.parser_signature,
        "ocr_signature": index.ocr_signature,
        "chunk_max_chars": chunking.max_chars,
        "chunk_overlap_chars": chunking.overlap_chars,
    }


def _checkpoint_uuid_sequence(
    checkpoint: Mapping[str, object],
    key: str,
    *,
    allow_empty: bool = False,
) -> tuple[UUID, ...]:
    raw = checkpoint.get(key)
    if not isinstance(raw, list) or (not raw and not allow_empty):
        raise ValueError
    values = tuple(UUID(value) for value in raw if isinstance(value, str))
    if (
        len(values) != len(raw)
        or len(set(values)) != len(values)
        or any(str(value) != raw_value for value, raw_value in zip(values, raw, strict=True))
    ):
        raise ValueError
    return values


@dataclass(frozen=True)
class _SemanticJobExpectation:
    job_ids: tuple[UUID, ...]
    vault_file_ids: tuple[UUID, ...]

    @property
    def checkpoint_job_ids(self) -> list[str]:
        return [str(value) for value in self.job_ids]

    @property
    def checkpoint_vault_file_ids(self) -> list[str]:
        return [str(value) for value in self.vault_file_ids]


def _semantic_job_expectation(
    checkpoint: Mapping[str, object], *, allow_empty: bool = False
) -> _SemanticJobExpectation:
    job_ids = _checkpoint_uuid_sequence(
        checkpoint,
        _SEMANTIC_JOB_IDS_KEY,
        allow_empty=allow_empty,
    )
    vault_file_ids = _checkpoint_uuid_sequence(
        checkpoint,
        _SEMANTIC_VAULT_FILE_IDS_KEY,
        allow_empty=allow_empty,
    )
    if len(job_ids) != len(vault_file_ids):
        raise ValueError
    return _SemanticJobExpectation(job_ids=job_ids, vault_file_ids=vault_file_ids)


def _semantic_file_matches_change_entry(
    *,
    vault_file: VaultFile | None,
    entry: VaultChangeEntry,
    owner: IngestionJob,
    change_set: VaultChangeSet,
) -> bool:
    return bool(
        vault_file is not None
        and vault_file.space_id == owner.space_id
        and vault_file.knowledge_base_id == owner.knowledge_base_id
        and vault_file.last_change_set_id == change_set.id
        and vault_file.file_kind is VaultFileKind.MARKDOWN
        and not vault_file.is_tombstoned
        and entry.space_id == owner.space_id
        and entry.knowledge_base_id == owner.knowledge_base_id
        and entry.change_set_id == change_set.id
        and entry.vault_file_id == vault_file.id
        and entry.operation is not VaultChangeOperation.DELETE
        and entry.after_path == vault_file.relative_path
        and entry.after_hash == vault_file.content_hash
    )


def _validated_semantic_jobs(
    session: Session,
    *,
    owner: IngestionJob,
    change_set: VaultChangeSet,
    allow_empty: bool = False,
) -> tuple[IngestionJob, ...]:
    try:
        expectation = _semantic_job_expectation(owner.checkpoint, allow_empty=allow_empty)
    except (TypeError, ValueError):
        raise WorkerPublicError("semantic_job_checkpoint_invalid") from None
    eligible_vault_file_ids = tuple(
        vault_file.id
        for vault_file in _eligible_semantic_files(
            session,
            parent=owner,
            change_set=change_set,
        )
    )
    if expectation.vault_file_ids != eligible_vault_file_ids:
        raise WorkerPublicError("semantic_job_checkpoint_invalid")
    if not expectation.job_ids:
        return ()

    jobs = tuple(
        session.scalars(
            select(IngestionJob).where(
                IngestionJob.id.in_(expectation.job_ids),
                IngestionJob.knowledge_base_id == owner.knowledge_base_id,
                IngestionJob.space_id == owner.space_id,
            )
        )
    )
    jobs_by_id = {expected.id: expected for expected in jobs}
    if set(jobs_by_id) != set(expectation.job_ids):
        raise WorkerPublicError("semantic_job_checkpoint_invalid")

    entries = tuple(
        session.scalars(
            select(VaultChangeEntry).where(
                VaultChangeEntry.change_set_id == change_set.id,
                VaultChangeEntry.vault_file_id.in_(expectation.vault_file_ids),
                VaultChangeEntry.knowledge_base_id == owner.knowledge_base_id,
                VaultChangeEntry.space_id == owner.space_id,
            )
        )
    )
    entries_by_vault_file_id = {entry.vault_file_id: entry for entry in entries}
    if (
        len(entries_by_vault_file_id) != len(entries)
        or set(entries_by_vault_file_id) != set(expectation.vault_file_ids)
    ):
        raise WorkerPublicError("semantic_job_checkpoint_invalid")

    ordered_jobs: list[IngestionJob] = []
    for expected_job_id, expected_vault_file_id in zip(
        expectation.job_ids, expectation.vault_file_ids, strict=True
    ):
        expected = jobs_by_id[expected_job_id]
        try:
            expected_kind = _durable_job_kind(expected)
            child_expectation = _semantic_job_expectation(expected.checkpoint)
            child_vault_file_id = _required_checkpoint_uuid(
                expected.checkpoint, "vault_file_id"
            )
            child_snapshot_hash = _required_checkpoint_sha256(
                expected.checkpoint, "source_snapshot_hash"
            )
        except (AttributeError, TypeError, ValueError, WorkerPublicError):
            raise WorkerPublicError("semantic_job_checkpoint_invalid") from None
        if (
            expected_kind is not DurableJobKind.SEMANTIC_PLAN
            or expected.checkpoint.get("source_change_set_id") != str(change_set.id)
            or child_snapshot_hash != change_set.after_snapshot_hash
            or child_expectation != expectation
            or child_vault_file_id != expected_vault_file_id
        ):
            raise WorkerPublicError("semantic_job_checkpoint_invalid")
        vault_file = session.get(VaultFile, expected_vault_file_id)
        entry = entries_by_vault_file_id[expected_vault_file_id]
        if not _semantic_file_matches_change_entry(
            vault_file=vault_file,
            entry=entry,
            owner=owner,
            change_set=change_set,
        ):
            raise WorkerPublicError("semantic_job_checkpoint_invalid")
        ordered_jobs.append(expected)
    return tuple(ordered_jobs)


def _semantic_jobs_from_checkpoint(
    session: Session,
    *,
    parent: IngestionJob,
    change_set: VaultChangeSet,
) -> tuple[IngestionJob, ...] | None:
    expectation_keys = {_SEMANTIC_JOB_IDS_KEY, _SEMANTIC_VAULT_FILE_IDS_KEY}
    present_keys = expectation_keys.intersection(parent.checkpoint)
    marker_present = _SEMANTIC_EXPECTATION_INITIALIZED_KEY in parent.checkpoint
    if marker_present and parent.checkpoint[_SEMANTIC_EXPECTATION_INITIALIZED_KEY] is not True:
        raise WorkerPublicError("semantic_job_checkpoint_invalid")
    if not present_keys:
        if marker_present:
            raise WorkerPublicError("semantic_job_checkpoint_invalid")
        expected_idempotency_keys = tuple(
            f"semantic-plan:{change_set.id}:{vault_file.id}"
            for vault_file in _eligible_semantic_files(
                session, parent=parent, change_set=change_set
            )
        )
        existing_child_id = None
        if expected_idempotency_keys:
            existing_child_id = session.scalar(
                select(IngestionJob.id)
                .where(
                    IngestionJob.knowledge_base_id == parent.knowledge_base_id,
                    IngestionJob.idempotency_key.in_(expected_idempotency_keys),
                )
                .limit(1)
            )
        if existing_child_id is not None:
            raise WorkerPublicError("semantic_job_checkpoint_invalid")
        return None
    if present_keys != expectation_keys:
        raise WorkerPublicError("semantic_job_checkpoint_invalid")
    jobs = _validated_semantic_jobs(
        session,
        owner=parent,
        change_set=change_set,
        allow_empty=True,
    )
    parent.checkpoint[_SEMANTIC_EXPECTATION_INITIALIZED_KEY] = True
    return jobs


def _eligible_semantic_files(
    session: Session,
    *,
    parent: IngestionJob,
    change_set: VaultChangeSet,
) -> tuple[VaultFile, ...]:
    eligible: list[VaultFile] = []
    entries = session.scalars(
        select(VaultChangeEntry)
        .where(VaultChangeEntry.change_set_id == change_set.id)
        .order_by(VaultChangeEntry.ordinal)
    )
    for entry in entries:
        vault_file = session.get(VaultFile, entry.vault_file_id)
        if _semantic_file_matches_change_entry(
            vault_file=vault_file,
            entry=entry,
            owner=parent,
            change_set=change_set,
        ):
            assert vault_file is not None
            eligible.append(vault_file)
    return tuple(eligible)


def _enqueue_semantic_jobs(
    session: Session,
    *,
    parent: IngestionJob,
    change_set: VaultChangeSet,
) -> tuple[IngestionJob, ...]:
    checkpointed = _semantic_jobs_from_checkpoint(
        session,
        parent=parent,
        change_set=change_set,
    )
    if checkpointed is not None:
        return checkpointed
    if change_set.after_snapshot_hash is None:
        raise WorkerPublicError("semantic_change_set_snapshot_missing")
    vault_files = _eligible_semantic_files(
        session,
        parent=parent,
        change_set=change_set,
    )
    if not vault_files:
        parent.checkpoint[_SEMANTIC_JOB_IDS_KEY] = []
        parent.checkpoint[_SEMANTIC_VAULT_FILE_IDS_KEY] = []
        parent.checkpoint[_SEMANTIC_EXPECTATION_INITIALIZED_KEY] = True
        session.flush()
        return ()
    if len({vault_file.id for vault_file in vault_files}) != len(vault_files):
        raise WorkerPublicError("semantic_job_checkpoint_invalid")
    contract = _semantic_contract_checkpoint(session, parent)
    if contract is None:
        raise WorkerPublicError("semantic_contract_unavailable")
    jobs: list[IngestionJob] = []
    for vault_file in vault_files:
        checkpoint = {
            **contract,
            "vault_file_id": str(vault_file.id),
            "source_change_set_id": str(change_set.id),
            "source_snapshot_hash": change_set.after_snapshot_hash,
        }
        jobs.append(
            _enqueue_durable_job(
                session,
                parent=parent,
                logical_kind=DurableJobKind.SEMANTIC_PLAN,
                idempotency_key=f"semantic-plan:{change_set.id}:{vault_file.id}",
                checkpoint=checkpoint,
            )
        )
    expected_job_ids = [str(job.id) for job in jobs]
    expected_vault_file_ids = [str(vault_file.id) for vault_file in vault_files]
    parent.checkpoint[_SEMANTIC_JOB_IDS_KEY] = expected_job_ids
    parent.checkpoint[_SEMANTIC_VAULT_FILE_IDS_KEY] = expected_vault_file_ids
    parent.checkpoint[_SEMANTIC_EXPECTATION_INITIALIZED_KEY] = True
    for job in jobs:
        job.checkpoint[_SEMANTIC_JOB_IDS_KEY] = expected_job_ids
        job.checkpoint[_SEMANTIC_VAULT_FILE_IDS_KEY] = expected_vault_file_ids
    session.flush()
    return tuple(jobs)


def make_vault_scan_handler(vault_root: Path) -> JobHandler:
    """Create an idempotent full-scan/resume handler for one knowledge base."""

    root = Path(vault_root).resolve()

    def handle(session: Session, job: IngestionJob) -> None:
        service = VaultSyncService(
            session,
            root,
            space_id=job.space_id,
            knowledge_base_id=job.knowledge_base_id,
            actor_user_id=job.created_by_user_id,
        )
        force = job.checkpoint.get("force_full_scan", False)
        if not isinstance(force, bool):
            raise WorkerPublicError("vault_scan_checkpoint_invalid")
        result = service.scan(
            now=_worker_now(), force=force or service.cursor.requires_full_scan
        )
        if result.change_set_id is not None:
            change_set_id = str(result.change_set_id)
            job.checkpoint["change_set_id"] = change_set_id
            project_checkpoint: dict[str, object] = {"change_set_id": change_set_id}
            contract = _semantic_contract_checkpoint(session, job)
            if contract is not None:
                project_checkpoint.update(contract)
            _enqueue_durable_job(
                session,
                parent=job,
                logical_kind=DurableJobKind.VAULT_PROJECT,
                idempotency_key=f"vault-project:{change_set_id}",
                checkpoint=project_checkpoint,
            )
        job.checkpoint["change_count"] = result.change_count
        job.checkpoint["scan_deferred"] = result.deferred
        job.checkpoint["cursor"] = service.cursor_payload()

    return handle


def make_vault_project_handler(vault_root: Path) -> JobHandler:
    """Create an idempotent Vault-to-Markdown projection handler."""

    root = Path(vault_root).resolve()

    def handle(session: Session, job: IngestionJob) -> None:
        try:
            change_set_id = _required_checkpoint_uuid(job.checkpoint, "change_set_id")
        except (AttributeError, TypeError, ValueError):
            raise WorkerPublicError("vault_project_checkpoint_invalid") from None
        service = VaultSyncService(
            session,
            root,
            space_id=job.space_id,
            knowledge_base_id=job.knowledge_base_id,
            actor_user_id=job.created_by_user_id,
        )
        try:
            result = service.project(change_set_id, now=_worker_now())
        except KeyError:
            raise WorkerPublicError("vault_change_set_not_found") from None
        job.checkpoint["projected_change_set_id"] = str(result.change_set_id)
        job.checkpoint["projected_count"] = result.projected_count
        job.checkpoint["cursor"] = service.cursor_payload()
        change_set = session.get(VaultChangeSet, result.change_set_id)
        if change_set is None:
            raise WorkerPublicError("vault_change_set_not_found")
        semantic_jobs = _enqueue_semantic_jobs(session, parent=job, change_set=change_set)
        if not semantic_jobs and change_set.state not in (
            VaultChangeSetState.FAILED,
            VaultChangeSetState.INDEXED,
        ):
            service.mark_indexed(change_set.id, now=_worker_now())

    return handle


def _read_vault_source(service: VaultSyncService, vault_file: VaultFile) -> str:
    relative_path = PurePosixPath(vault_file.relative_path)
    try:
        target = (service.root / Path(*relative_path.parts)).resolve(strict=True)
        if target == service.root or service.root not in target.parents or not target.is_file():
            raise WorkerPublicError("semantic_source_invalid")
        payload = target.read_bytes()
    except OSError:
        raise WorkerPublicError("semantic_source_invalid") from None
    if hashlib.sha256(payload).hexdigest() != vault_file.content_hash:
        raise WorkerPublicError("semantic_source_stale")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        raise WorkerPublicError("semantic_source_invalid") from None



_USABLE_SEMANTIC_CHANGE_SET_STATES = frozenset(
    (
        VaultChangeSetState.COMMITTED,
        VaultChangeSetState.INDEXING,
        VaultChangeSetState.INDEXED,
    )
)


def _validate_semantic_change_set(
    session: Session,
    *,
    job: IngestionJob,
    vault_file: VaultFile,
    change_set_id: UUID,
    source_snapshot_hash: str,
) -> VaultChangeSet:
    change_set = session.get(VaultChangeSet, change_set_id)
    if (
        change_set is None
        or change_set.space_id != job.space_id
        or change_set.knowledge_base_id != job.knowledge_base_id
        or change_set.state not in _USABLE_SEMANTIC_CHANGE_SET_STATES
    ):
        raise WorkerPublicError("semantic_change_set_invalid")
    if change_set.after_snapshot_hash != source_snapshot_hash:
        raise WorkerPublicError("semantic_change_set_snapshot_mismatch")
    entry = session.scalar(
        select(VaultChangeEntry).where(
            VaultChangeEntry.change_set_id == change_set.id,
            VaultChangeEntry.vault_file_id == vault_file.id,
            VaultChangeEntry.space_id == job.space_id,
            VaultChangeEntry.knowledge_base_id == job.knowledge_base_id,
        )
    )
    if (
        entry is None
        or entry.after_path != vault_file.relative_path
        or entry.after_hash != vault_file.content_hash
    ):
        raise WorkerPublicError("semantic_change_set_source_invalid")
    return change_set


def _finalize_semantic_change_set(
    session: Session,
    *,
    service: VaultSyncService,
    job: IngestionJob,
    change_set_id: UUID,
    now: datetime,
) -> None:
    change_set = session.scalar(
        select(VaultChangeSet)
        .where(
            VaultChangeSet.id == change_set_id,
            VaultChangeSet.knowledge_base_id == job.knowledge_base_id,
            VaultChangeSet.space_id == job.space_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if change_set is None:
        raise WorkerPublicError("semantic_change_set_invalid")
    if change_set.state is VaultChangeSetState.FAILED:
        return
    expected_jobs = _validated_semantic_jobs(
        session,
        owner=job,
        change_set=change_set,
    )
    if job.id not in {expected.id for expected in expected_jobs}:
        raise WorkerPublicError("semantic_job_checkpoint_invalid")
    failed = next(
        (
            expected
            for expected in expected_jobs
            if expected.state in (IngestionJobState.FAILED, IngestionJobState.CANCELLED)
        ),
        None,
    )
    if failed is not None:
        change_set.state = VaultChangeSetState.FAILED
        change_set.failure_code = failed.last_error_code or "semantic_job_failed"
        change_set.failure_message = None
        change_set.indexed_at = None
        session.flush()
        return
    all_completed = all(
        expected.state is IngestionJobState.COMPLETED or expected.id == job.id
        for expected in expected_jobs
    )
    if not all_completed:
        change_set.state = VaultChangeSetState.INDEXING
        change_set.indexed_at = None
        session.flush()
        return
    service.mark_indexed(change_set.id, now=now)


def make_semantic_plan_handler(
    adapter: EmbeddingAdapter,
    planner: SemanticPlanner,
    *,
    vault_root: Path,
    sidecar_root: Path,
) -> JobHandler:
    """Create the durable semantic planner/index activation handler."""

    root = Path(vault_root).resolve()
    sidecars = FilesystemRawSidecarWriter(Path(sidecar_root).resolve())

    def handle(session: Session, job: IngestionJob) -> None:
        checkpoint = job.checkpoint
        try:
            vault_file_id = _required_checkpoint_uuid(checkpoint, "vault_file_id")
            document_version_ids = _checkpoint_uuid_tuple(checkpoint, "document_version_ids")
            parser_signature = _required_checkpoint_string(checkpoint, "parser_signature")
            ocr_signature = _required_checkpoint_string(checkpoint, "ocr_signature")
            chunking = ChunkingConfig(
                max_chars=_required_checkpoint_int(checkpoint, "chunk_max_chars"),
                overlap_chars=_required_checkpoint_int(checkpoint, "chunk_overlap_chars"),
            )
            source_snapshot_hash = _required_checkpoint_sha256(checkpoint, "source_snapshot_hash")
            source_change_set_id = _optional_checkpoint_uuid(checkpoint, "source_change_set_id")
        except (AttributeError, TypeError, ValueError):
            raise WorkerPublicError("semantic_job_checkpoint_invalid") from None

        vault_file = session.get(VaultFile, vault_file_id)
        if (
            vault_file is None
            or vault_file.space_id != job.space_id
            or vault_file.knowledge_base_id != job.knowledge_base_id
            or vault_file.is_tombstoned
        ):
            raise WorkerPublicError("semantic_source_invalid")
        if source_change_set_id is None:
            if source_snapshot_hash != vault_file.content_hash:
                raise WorkerPublicError("semantic_source_stale")
        else:
            _validate_semantic_change_set(
                session,
                job=job,
                vault_file=vault_file,
                change_set_id=source_change_set_id,
                source_snapshot_hash=source_snapshot_hash,
            )
        service = VaultSyncService(
            session,
            root,
            space_id=job.space_id,
            knowledge_base_id=job.knowledge_base_id,
            actor_user_id=job.created_by_user_id,
        )
        source_text = _read_vault_source(service, vault_file)
        try:
            request = IndexBuildRequest(
                space_id=job.space_id,
                knowledge_base_id=job.knowledge_base_id,
                created_by_user_id=job.created_by_user_id,
                document_version_ids=document_version_ids,
                parser_signature=parser_signature,
                ocr_signature=ocr_signature,
                chunking=chunking,
                source_snapshot_hash=source_snapshot_hash,
                source_change_set_id=source_change_set_id,
            )
        except ValueError:
            raise WorkerPublicError("semantic_job_checkpoint_invalid") from None
        timestamp = _worker_now()
        result: SemanticIndexJobResult = run_semantic_index_job(
            session,
            request=request,
            adapter=adapter,
            vault_file_id=vault_file.id,
            source_text=source_text,
            planner=planner,
            sidecar_writer=sidecars,
            now=timestamp,
        )
        job.checkpoint["semantic_state"] = result.state.value
        job.checkpoint["semantic_plan_id"] = str(result.semantic_plan_id)
        job.checkpoint["semantic_index_version_id"] = str(result.index_version_id)
        job.checkpoint["semantic_reused_plan"] = result.reused_plan
        if result.state is SemanticJobState.ACTIVE:
            if source_change_set_id is not None:
                _finalize_semantic_change_set(
                    session,
                    service=service,
                    job=job,
                    change_set_id=source_change_set_id,
                    now=timestamp,
                )
            return
        raise WorkerPublicError(result.error_code or "semantic_plan_failed")

    return handle


def run_worker_once(
    session_factory: sessionmaker[Session],
    handlers: WorkerHandlers,
    *,
    config: WorkerConfig,
    now: datetime | None = None,
) -> bool:
    """Claim in one transaction and execute in a fresh worker-owned Session."""

    timestamp = now or datetime.now(UTC)
    direct_kinds = tuple(kind for kind in handlers if isinstance(kind, IngestionJobKind))
    logical_kinds = tuple(kind for kind in handlers if isinstance(kind, DurableJobKind))
    with session_factory.begin() as session:
        claimed = claim_next_job(
            session,
            worker_id=config.worker_id,
            now=timestamp,
            lease_duration=config.lease_duration,
            kinds=direct_kinds or None,
            logical_kinds=logical_kinds or None,
        )
        if claimed is None:
            return False
        job_id = claimed.id
        transport_kind = claimed.kind

    time_token = _WORKER_INVOCATION_TIME.set(timestamp)
    try:
        try:
            with session_factory.begin() as session:
                job = _owned_running_job(session, job_id, config.worker_id)
                handler_kind: WorkerJobKind = _durable_job_kind(job) or job.kind
                handler = handlers.get(handler_kind)
                if handler is None:
                    raise WorkerPublicError("worker_handler_missing")
                handler(session, job)
                complete_job(
                    session,
                    job_id=job_id,
                    worker_id=config.worker_id,
                    now=timestamp,
                )
        except Exception as error:
            print(
                f"[tutor-worker] job {job_id} kind={transport_kind.value} failed "
                f"code={_public_error_code(error)} type={type(error).__name__}",
                file=sys.stderr,
                flush=True,
            )
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
    finally:
        _WORKER_INVOCATION_TIME.reset(time_token)


def run_worker_forever(
    session_factory: sessionmaker[Session],
    handlers: WorkerHandlers,
    *,
    config: WorkerConfig,
    should_stop: Callable[[], bool] | None = None,
    maintenance: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    stop = should_stop or (lambda: False)
    while not stop():
        worked = run_worker_once(session_factory, handlers, config=config)
        if stop():
            break
        maintenance_worked = maintenance() if maintenance is not None else False
        if not worked and not maintenance_worked and not stop():
            sleep(config.idle_sleep_seconds)
