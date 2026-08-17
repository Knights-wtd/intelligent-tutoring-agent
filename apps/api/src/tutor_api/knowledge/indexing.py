"""Deterministic immutable knowledge-index construction."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from tutor_api.knowledge.models import (
    Block,
    BlockKind,
    Chunk,
    DocumentVersion,
    DocumentVersionState,
    IndexVersion,
    IndexVersionState,
    KnowledgeBase,
    Page,
)

_MAX_CHUNK_CHARS = 100_000
_TERM = re.compile(r"[^\W_]+", re.UNICODE)


class EmbeddingAdapter(Protocol):
    @property
    def backend(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def signature(self) -> str: ...

    def embed(self, text: str) -> list[float]: ...


class IndexingError(RuntimeError):
    """Stable public indexing failure without provider details."""

    def __init__(self, code: str = "index_build_failed") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    max_chars: int = 1_200
    overlap_chars: int = 120

    def __post_init__(self) -> None:
        if isinstance(self.max_chars, bool) or not isinstance(self.max_chars, int):
            raise ValueError("max_chars must be a positive bounded integer")
        if not 1 <= self.max_chars <= _MAX_CHUNK_CHARS:
            raise ValueError("max_chars must be a positive bounded integer")
        if isinstance(self.overlap_chars, bool) or not isinstance(self.overlap_chars, int):
            raise ValueError("overlap_chars must be a non-negative integer")
        if not 0 <= self.overlap_chars < self.max_chars:
            raise ValueError("overlap_chars must be smaller than max_chars")

    @property
    def signature(self) -> str:
        return make_pipeline_signature(
            "chunking", "heading-window", "1", self.max_chars, self.overlap_chars
        )


@dataclass(frozen=True, slots=True)
class SourceChunk:
    page_number: int
    block_ordinal: int
    content: str
    source_pointer: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class IndexBuildRequest:
    space_id: UUID
    knowledge_base_id: UUID
    created_by_user_id: UUID
    document_version_ids: tuple[UUID, ...]
    parser_signature: str
    ocr_signature: str
    chunking: ChunkingConfig

    def __post_init__(self) -> None:
        if not self.document_version_ids:
            raise ValueError("document_version_ids must not be empty")
        if len(set(self.document_version_ids)) != len(self.document_version_ids):
            raise ValueError("document_version_ids must be unique")
        if not self.parser_signature or not self.ocr_signature:
            raise ValueError("pipeline signatures must not be blank")


@dataclass(frozen=True, slots=True)
class IndexBuildResult:
    index_version_id: UUID
    chunk_count: int
    reused: bool


def content_sha256(content: str | bytes) -> str:
    payload = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    return hashlib.sha256(payload).hexdigest()


def _canonical_signature(domain: str, payload: object) -> str:
    if not domain or not re.fullmatch(r"[a-z][a-z0-9_-]*", domain):
        raise ValueError("signature domain is invalid")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return f"tutor:{domain}:v1:{hashlib.sha256(encoded).hexdigest()}"


def make_pipeline_signature(domain: str, name: str, version: str, *parameters: object) -> str:
    return _canonical_signature(
        domain,
        {"name": name, "parameters": list(parameters), "signature_version": 1, "version": version},
    )


def _embedding_contract_signature(adapter: EmbeddingAdapter) -> str:
    return _canonical_signature(
        "embedding",
        {
            "adapter_signature": adapter.signature,
            "backend": adapter.backend,
            "dimension": adapter.dimension,
            "model": adapter.model,
            "signature_version": 1,
        },
    )


def make_index_signature(
    *,
    knowledge_base_id: UUID,
    document_sources: Iterable[tuple[UUID, str]],
    parser_signature: str,
    ocr_signature: str,
    chunking_signature: str,
    embedding_signature: str,
) -> str:
    sources = sorted((str(version_id), sha256) for version_id, sha256 in document_sources)
    if not sources or any(not re.fullmatch(r"[0-9a-f]{64}", sha256) for _, sha256 in sources):
        raise ValueError("document sources must contain lowercase SHA-256 values")
    if len({version_id for version_id, _ in sources}) != len(sources):
        raise ValueError("document source identities must be unique")
    return _canonical_signature(
        "index",
        {
            "chunking": chunking_signature,
            "documents": sources,
            "embedding": embedding_signature,
            "knowledge_base_id": str(knowledge_base_id),
            "ocr": ocr_signature,
            "parser": parser_signature,
            "signature_version": 1,
        },
    )


def normalize_lexical_terms(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return sorted(set(_TERM.findall(normalized)))


def _normalize_content(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line for raw in normalized.splitlines() if (line := " ".join(raw.split())))


def _bounded_heading(heading: str, maximum: int) -> str:
    if len(heading) + 1 < maximum:
        return heading
    return heading[: max(1, maximum // 3)].rstrip()


def chunk_source_blocks(
    blocks: Iterable[tuple[int, int, str, str, str]], config: ChunkingConfig
) -> tuple[SourceChunk, ...]:
    """Chunk ordered source blocks while carrying the current heading into body chunks."""

    result: list[SourceChunk] = []
    heading = ""
    pending_heading: tuple[int, int, str] | None = None
    for page_number, block_ordinal, raw_kind, raw_text, source_pointer in blocks:
        text = _normalize_content(raw_text)
        if not text:
            continue
        kind = raw_kind.value if isinstance(raw_kind, BlockKind) else str(raw_kind).casefold()
        if kind in {"heading", BlockKind.TITLE.value}:
            if pending_heading is not None:
                page, ordinal, pointer = pending_heading
                result.append(SourceChunk(page, ordinal, heading, pointer, len(result)))
            heading = _bounded_heading(text, config.max_chars)
            pending_heading = (page_number, block_ordinal, source_pointer)
            continue

        pending_heading = None
        prefix = f"{heading}\n" if heading else ""
        body_limit = config.max_chars - len(prefix)
        if body_limit <= 0:
            prefix = ""
            body_limit = config.max_chars
        start = 0
        part = 0
        while start < len(text):
            end = min(len(text), start + body_limit)
            body = text[start:end]
            if not body:
                raise ValueError("chunking made no progress")
            pointer = (
                source_pointer if len(text) <= body_limit else f"{source_pointer}#chunk={part}"
            )
            result.append(
                SourceChunk(
                    page_number=page_number,
                    block_ordinal=block_ordinal,
                    content=prefix + body,
                    source_pointer=pointer,
                    ordinal=len(result),
                )
            )
            if end == len(text):
                break
            next_start = end - min(config.overlap_chars, len(body) - 1)
            if next_start <= start:
                raise ValueError("chunking made no progress")
            start = next_start
            part += 1
    if pending_heading is not None:
        page, ordinal, pointer = pending_heading
        result.append(SourceChunk(page, ordinal, heading, pointer, len(result)))
    if not result:
        raise ValueError("index source produced no chunks")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class _LoadedBlock:
    document_version_id: UUID
    page_id: UUID
    block_id: UUID
    page_number: int
    block_ordinal: int
    kind: BlockKind
    text: str
    source_pointer: str


@dataclass(frozen=True, slots=True)
class _PreparedChunk:
    source: _LoadedBlock
    chunk: SourceChunk
    sha256: str
    lexical_terms: list[str]
    embedding: list[float]


def _load_versions(session: Session, request: IndexBuildRequest) -> list[DocumentVersion]:
    versions = list(
        session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.id.in_(request.document_version_ids))
            .order_by(DocumentVersion.id)
        )
    )
    if len(versions) != len(request.document_version_ids):
        raise IndexingError("index_source_contract_invalid")
    if any(
        version.space_id != request.space_id
        or version.knowledge_base_id != request.knowledge_base_id
        or version.state is not DocumentVersionState.READY
        for version in versions
    ):
        raise IndexingError("index_source_contract_invalid")
    return versions


def _namespaced_source_pointer(document_version_id: UUID, raw_pointer: str) -> str:
    prefix = f"document-version:{document_version_id}:"
    maximum_base_length = 980
    candidate = prefix + raw_pointer
    if len(candidate) <= maximum_base_length:
        return candidate
    return prefix + "sha256:" + content_sha256(raw_pointer)


def _load_blocks(session: Session, request: IndexBuildRequest) -> list[_LoadedBlock]:
    rows = session.execute(
        select(Block, Page)
        .join(Page, Block.page_id == Page.id)
        .where(Page.document_version_id.in_(request.document_version_ids))
        .order_by(Page.document_version_id, Page.page_number, Block.ordinal, Block.id)
    ).all()
    loaded = [
        _LoadedBlock(
            document_version_id=page.document_version_id,
            page_id=page.id,
            block_id=block.id,
            page_number=page.page_number,
            block_ordinal=block.ordinal,
            kind=block.kind,
            text=block.text or "",
            source_pointer=_namespaced_source_pointer(
                page.document_version_id, block.source_pointer
            ),
        )
        for block, page in rows
    ]
    if not loaded:
        raise IndexingError("index_source_empty")
    return loaded


def _validate_embedding(vector: object, dimension: int) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimension:
        raise IndexingError("embedding_contract_invalid")
    result: list[float] = []
    for component in vector:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise IndexingError("embedding_contract_invalid")
        value = float(component)
        if not math.isfinite(value):
            raise IndexingError("embedding_contract_invalid")
        result.append(value)
    return result


def _find_reusable_embedding(
    session: Session, *, sha256: str, request: IndexBuildRequest, adapter: EmbeddingAdapter
) -> list[float] | None:
    row = session.execute(
        select(Chunk.embedding)
        .join(IndexVersion, Chunk.index_version_id == IndexVersion.id)
        .where(
            Chunk.knowledge_base_id == request.knowledge_base_id,
            Chunk.content_sha256 == sha256,
            IndexVersion.parser_signature == request.parser_signature,
            IndexVersion.ocr_signature == request.ocr_signature,
            IndexVersion.chunking_signature == request.chunking.signature,
            IndexVersion.embedding_backend == adapter.backend,
            IndexVersion.embedding_model == adapter.model,
            IndexVersion.embedding_dimension == adapter.dimension,
            IndexVersion.embedding_contract_signature == _embedding_contract_signature(adapter),
            IndexVersion.state.in_((IndexVersionState.ACTIVE, IndexVersionState.RETIRED)),
        )
        .limit(1)
    ).scalar_one_or_none()
    return None if row is None else _validate_embedding(row, adapter.dimension)


def _prepare_chunks(
    session: Session,
    request: IndexBuildRequest,
    blocks: list[_LoadedBlock],
    adapter: EmbeddingAdapter,
) -> list[_PreparedChunk]:
    source_by_pointer = {block.source_pointer: block for block in blocks}
    cache: dict[str, list[float]] = {}
    prepared: list[_PreparedChunk] = []
    version_ids = dict.fromkeys(block.document_version_id for block in blocks)
    for version_id in version_ids:
        version_blocks = [block for block in blocks if block.document_version_id == version_id]
        source_chunks = chunk_source_blocks(
            (
                (
                    block.page_number,
                    block.block_ordinal,
                    block.kind,
                    block.text,
                    block.source_pointer,
                )
                for block in version_blocks
            ),
            request.chunking,
        )
        for source_chunk in source_chunks:
            base_pointer = source_chunk.source_pointer.split("#chunk=", 1)[0]
            source = source_by_pointer.get(base_pointer)
            if source is None:
                raise IndexingError("index_pointer_contract_invalid")
            sha256 = content_sha256(source_chunk.content)
            vector = cache.get(sha256)
            if vector is None:
                vector = _find_reusable_embedding(
                    session, sha256=sha256, request=request, adapter=adapter
                )
            if vector is None:
                vector = _validate_embedding(adapter.embed(source_chunk.content), adapter.dimension)
            cache[sha256] = vector
            prepared.append(
                _PreparedChunk(
                    source=source,
                    chunk=SourceChunk(
                        page_number=source_chunk.page_number,
                        block_ordinal=source_chunk.block_ordinal,
                        content=source_chunk.content,
                        source_pointer=source_chunk.source_pointer,
                        ordinal=len(prepared),
                    ),
                    sha256=sha256,
                    lexical_terms=normalize_lexical_terms(source_chunk.content),
                    embedding=list(vector),
                )
            )
    return prepared


def _validate_persisted_index(
    session: Session, index: IndexVersion, expected: list[_PreparedChunk]
) -> None:
    chunks = list(
        session.scalars(
            select(Chunk).where(Chunk.index_version_id == index.id).order_by(Chunk.ordinal)
        )
    )
    if len(chunks) != len(expected) or not chunks:
        raise IndexingError("index_validation_failed")
    for ordinal, (chunk, prepared) in enumerate(zip(chunks, expected, strict=True)):
        if (
            chunk.ordinal != ordinal
            or chunk.space_id != index.space_id
            or chunk.knowledge_base_id != index.knowledge_base_id
            or chunk.document_version_id != prepared.source.document_version_id
            or chunk.page_id != prepared.source.page_id
            or chunk.block_id != prepared.source.block_id
            or chunk.source_pointer != prepared.chunk.source_pointer
            or chunk.content != prepared.chunk.content
            or chunk.content_sha256 != prepared.sha256
            or chunk.content_sha256 != content_sha256(chunk.content)
            or chunk.lexical_terms != prepared.lexical_terms
            or chunk.embedding_dimension != index.embedding_dimension
            or chunk.index_signature != index.index_signature
            or _validate_embedding(chunk.embedding, index.embedding_dimension) != prepared.embedding
        ):
            raise IndexingError("index_validation_failed")


def _lock_knowledge_base(session: Session, knowledge_base_id: UUID) -> None:
    """Serialize index target creation and activation within one knowledge base."""

    knowledge_base = session.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id).with_for_update()
    )
    if knowledge_base is None:
        raise IndexingError("index_source_contract_invalid")


def _activate_building_index(session: Session, index: IndexVersion, now: datetime) -> None:
    _lock_knowledge_base(session, index.knowledge_base_id)
    session.refresh(index)
    newer_active = session.scalar(
        select(IndexVersion.id)
        .where(
            IndexVersion.knowledge_base_id == index.knowledge_base_id,
            IndexVersion.state == IndexVersionState.ACTIVE,
            IndexVersion.version_number > index.version_number,
        )
        .limit(1)
    )
    if newer_active is not None:
        index.state = IndexVersionState.RETIRED
        index.completed_at = now
        index.activated_at = None
        session.flush()
        return
    session.execute(
        update(IndexVersion)
        .where(
            IndexVersion.knowledge_base_id == index.knowledge_base_id,
            IndexVersion.state == IndexVersionState.ACTIVE,
            IndexVersion.id != index.id,
        )
        .values(state=IndexVersionState.RETIRED)
    )
    session.flush()
    index.state = IndexVersionState.ACTIVE
    index.completed_at = now
    index.activated_at = now
    session.flush()


def prepare_index_build(
    session: Session,
    request: IndexBuildRequest,
    adapter: EmbeddingAdapter,
) -> IndexVersion:
    """Create or return the unique immutable target for one complete build contract."""

    versions = _load_versions(session, request)
    _lock_knowledge_base(session, request.knowledge_base_id)
    embedding_contract_signature = _embedding_contract_signature(adapter)
    signature = make_index_signature(
        knowledge_base_id=request.knowledge_base_id,
        document_sources=((version.id, version.content_sha256) for version in versions),
        parser_signature=request.parser_signature,
        ocr_signature=request.ocr_signature,
        chunking_signature=request.chunking.signature,
        embedding_signature=embedding_contract_signature,
    )
    existing = session.scalar(
        select(IndexVersion).where(
            IndexVersion.knowledge_base_id == request.knowledge_base_id,
            IndexVersion.index_signature == signature,
        )
    )
    if existing is not None:
        return existing
    version_number = (
        session.scalar(
            select(func.max(IndexVersion.version_number)).where(
                IndexVersion.knowledge_base_id == request.knowledge_base_id
            )
        )
        or 0
    ) + 1
    index = IndexVersion(
        space_id=request.space_id,
        knowledge_base_id=request.knowledge_base_id,
        version_number=version_number,
        state=IndexVersionState.BUILDING,
        parser_signature=request.parser_signature,
        ocr_signature=request.ocr_signature,
        chunking_signature=request.chunking.signature,
        embedding_backend=adapter.backend,
        embedding_model=adapter.model,
        embedding_dimension=adapter.dimension,
        embedding_contract_signature=embedding_contract_signature,
        index_signature=signature,
        created_by_user_id=request.created_by_user_id,
    )
    session.add(index)
    session.flush()
    return index


def build_index(
    session: Session,
    request: IndexBuildRequest,
    adapter: EmbeddingAdapter,
    *,
    now: datetime | None = None,
) -> IndexBuildResult:
    """Build all chunks under one version, then validate and atomically activate it."""

    timestamp = now or datetime.now(UTC)
    index = prepare_index_build(session, request, adapter)
    signature = index.index_signature
    if index.state in (IndexVersionState.ACTIVE, IndexVersionState.RETIRED):
        count = (
            session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.index_version_id == index.id)
            )
            or 0
        )
        return IndexBuildResult(index.id, count, True)

    index.state = IndexVersionState.BUILDING
    index.completed_at = None
    index.activated_at = None
    session.flush()
    try:
        blocks = _load_blocks(session, request)
        prepared = _prepare_chunks(session, request, blocks, adapter)
        with session.begin_nested():
            session.execute(delete(Chunk).where(Chunk.index_version_id == index.id))
            session.add_all(
                [
                    Chunk(
                        space_id=request.space_id,
                        knowledge_base_id=request.knowledge_base_id,
                        index_version_id=index.id,
                        document_version_id=item.source.document_version_id,
                        page_id=item.source.page_id,
                        block_id=item.source.block_id,
                        ordinal=item.chunk.ordinal,
                        source_pointer=item.chunk.source_pointer,
                        content_sha256=item.sha256,
                        content=item.chunk.content,
                        lexical_terms=item.lexical_terms,
                        embedding_dimension=adapter.dimension,
                        index_signature=signature,
                        embedding=item.embedding,
                    )
                    for item in prepared
                ]
            )
            session.flush()
            _validate_persisted_index(session, index, prepared)
            _activate_building_index(session, index, timestamp)
    except Exception as error:
        session.expire_all()
        failed = session.get(IndexVersion, index.id)
        if failed is not None:
            session.execute(delete(Chunk).where(Chunk.index_version_id == failed.id))
            failed.state = IndexVersionState.FAILED
            failed.completed_at = timestamp
            failed.activated_at = None
            session.flush()
        if isinstance(error, IndexingError):
            raise
        raise IndexingError() from None

    return IndexBuildResult(index.id, len(prepared), False)
