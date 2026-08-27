"""Database-leased ingestion worker primitives."""

from __future__ import annotations

import hashlib
import re
import sys
import time
import traceback
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

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
from tutor_api.knowledge.service import (
    enqueue_index_build,
    persist_parsed_document_and_enqueue_build,
)
from tutor_api.knowledge.storage import ObjectStorage
from tutor_api.llm.ports import MarkdownLlmAdapter

JobHandler = Callable[[Session, IngestionJob], None]
_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


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


def claim_job_statement(now: datetime, kinds: tuple[IngestionJobKind, ...] | None = None):
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
    if kinds is not None:
        filters.append(IngestionJob.kind.in_(kinds))
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


def _terminally_fail_build_target(session: Session, job: IngestionJob, now: datetime) -> None:
    if job.kind is not IngestionJobKind.BUILD_INDEX or job.index_version_id is None:
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


def _fail_exhausted_stale_jobs(
    session: Session,
    now: datetime,
    kinds: tuple[IngestionJobKind, ...] | None = None,
) -> None:
    filters = [
        IngestionJob.state == IngestionJobState.RUNNING,
        IngestionJob.lease_expires_at <= now,
        IngestionJob.attempt_count >= IngestionJob.max_attempts,
    ]
    if kinds is not None:
        filters.append(IngestionJob.kind.in_(kinds))
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
    session.flush()


def claim_next_job(
    session: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_duration: timedelta = timedelta(minutes=5),
    kinds: tuple[IngestionJobKind, ...] | None = None,
) -> IngestionJob | None:
    """Atomically lease one runnable job; SQLite is a single-worker test fallback only."""

    if not worker_id or len(worker_id) > 255:
        raise ValueError("worker_id must be between 1 and 255 characters")
    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be positive")
    timestamp = now or datetime.now(UTC)
    _fail_exhausted_stale_jobs(session, timestamp, kinds)
    job = session.scalar(claim_job_statement(timestamp, kinds))
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
        _record_candidate_failure(session, job, terminal=False)
    else:
        job.state = IngestionJobState.FAILED
        job.completed_at = timestamp
        _terminally_fail_build_target(session, job, timestamp)
        _terminally_fail_parse_target(session, job)
        _record_candidate_failure(session, job, terminal=True)
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
            _terminally_fail_build_target(session, job, datetime.now(UTC))
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
            kinds=tuple(handlers),
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
                now=datetime.now(UTC),
            )
    except Exception as error:
        # The database keeps only sanitized public error codes; the full cause is
        # surfaced here so operators can recover it from container logs.
        print(
            f"[tutor-worker] job {job_id} kind={kind.value} failed: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        with session_factory.begin() as session:
            try:
                fail_job(
                    session,
                    job_id=job_id,
                    worker_id=config.worker_id,
                    error=error,
                    retry_delay=config.retry_delay,
                    now=datetime.now(UTC),
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
