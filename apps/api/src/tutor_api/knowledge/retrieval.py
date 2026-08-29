"""Bounded, deterministic hybrid knowledge retrieval and cited previews."""

from __future__ import annotations

import base64
import heapq
import hmac
import math
import re
import unicodedata
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_readable_knowledge_base
from tutor_api.knowledge.embeddings import EmbeddingAdapter
from tutor_api.knowledge.indexing import _embedding_contract_signature, normalize_lexical_terms
from tutor_api.knowledge.models import (
    Chunk,
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    IndexVersion,
    IndexVersionState,
    KnowledgeBase,
    KnowledgeBaseState,
    Page,
)
from tutor_api.knowledge.storage import (
    ObjectNotFoundError,
    ObjectRangeNotSatisfiableError,
    ObjectSizeLimitError,
    ObjectStorage,
    StoredObjectRange,
)

MAX_QUERY_CHARACTERS = 500
MAX_RESULTS = 20
MAX_EXCERPT_CHARACTERS = 500
MAX_RETRIEVAL_CANDIDATES = 1_000
# Chunks whose query cosine similarity falls below this floor are excluded from
# the vector ranking. RRF only compares ranks, so without a floor even a chunk
# that is nearly orthogonal to the query would appear as a top hit and produce
# a confident-looking but irrelevant answer excerpt.
MIN_VECTOR_SIMILARITY = 0.2
MAX_PREVIEW_BYTES = 256 * 1024
DEFAULT_PREVIEW_BYTES = 64 * 1024
MAX_PREVIEW_START = 100 * 1024 * 1024
RRF_RANK_CONSTANT = 60
_CITATION_ID = re.compile(r"^cite_([A-Za-z0-9_-]{38})$")
_NON_PAGINATED_CONTENT_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "text/markdown",
        "text/plain",
    }
)


@dataclass(frozen=True, slots=True)
class SearchCitation:
    id: str
    source_name: str
    page_number: int | None


@dataclass(frozen=True, slots=True)
class SearchHit:
    excerpt: str
    citation: SearchCitation


@dataclass(frozen=True, slots=True)
class SourcePreview:
    data: bytes
    content_type: str
    start: int
    total_size: int


@dataclass(frozen=True, slots=True)
class _Candidate:
    chunk: Chunk
    source_name: str
    page_number: int | None


@dataclass(frozen=True, slots=True)
class _BoundedCandidate:
    """Reverse rank ordering so a heap keeps its worst candidate at the root."""

    rank_key: tuple[float, int, str]
    candidate: _Candidate

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, _BoundedCandidate):
            return NotImplemented
        return self.rank_key > other.rank_key


def normalize_search_query(value: str) -> str:
    """Normalize an API query to a small deterministic search string."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split())
    if not normalized:
        raise ValueError("检索词不能为空")
    if len(normalized) > MAX_QUERY_CHARACTERS:
        raise ValueError("检索词过长")
    return normalized


def _citation_mask(secret: str, knowledge_base_id: UUID) -> bytes:
    return hmac.digest(
        secret.encode("utf-8"),
        b"knowledge-citation:v1:mask:" + knowledge_base_id.bytes,
        "sha256",
    )[:16]


def _citation_tag(secret: str, knowledge_base_id: UUID, encrypted_chunk_id: bytes) -> bytes:
    return hmac.digest(
        secret.encode("utf-8"),
        b"knowledge-citation:v1:tag:" + knowledge_base_id.bytes + encrypted_chunk_id,
        "sha256",
    )[:12]


def citation_id_for_chunk(chunk_id: UUID, knowledge_base_id: UUID, secret: str) -> str:
    """Return a scoped opaque, integrity-protected citation token for one chunk."""

    mask = _citation_mask(secret, knowledge_base_id)
    masked = bytes(
        left ^ right for left, right in zip(chunk_id.bytes, mask, strict=True)
    )
    encoded = base64.urlsafe_b64encode(masked + _citation_tag(secret, knowledge_base_id, masked))
    return f"cite_{encoded.decode('ascii').rstrip('=')}"


def chunk_id_from_citation(
    citation_id: str, knowledge_base_id: UUID, secret: str
) -> UUID | None:
    match = _CITATION_ID.fullmatch(citation_id)
    if match is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(match.group(1) + "==")
    except (ValueError, UnicodeEncodeError):
        return None
    if len(raw) != 28:
        return None
    encrypted_chunk_id, supplied_tag = raw[:16], raw[16:]
    expected_tag = _citation_tag(secret, knowledge_base_id, encrypted_chunk_id)
    if not hmac.compare_digest(supplied_tag, expected_tag):
        return None
    mask = _citation_mask(secret, knowledge_base_id)
    return UUID(
        bytes=bytes(
            left ^ right
            for left, right in zip(encrypted_chunk_id, mask, strict=True)
        )
    )


def reciprocal_rank_fusion(
    rankings: Iterable[Sequence[Hashable]], *, rank_constant: int = RRF_RANK_CONSTANT
) -> list[Hashable]:
    """Fuse ranked lists using RRF with reproducible ordering for equal scores."""

    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    scores: dict[Hashable, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (rank_constant + rank)
    return sorted(scores, key=lambda item: (-scores[item], str(item)))


def _casefold_alignments(text: str) -> tuple[list[int], str]:
    """Map casefolded positions back to original-string offsets.

    ``str.casefold`` can expand one character into several (``ß`` -> ``ss``,
    ``ﬁ`` -> ``fi``), so folding the whole string first and reusing the folded
    offset to slice the original string misplaces every excerpt window built
    from it. This returns, for each casefolded character index, the offset of
    the original character that produced it, plus the folded string itself.
    """

    folded_chars: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(text):
        expanded = char.casefold()
        folded_chars.append(expanded)
        offsets.extend([index] * len(expanded))
    return offsets, "".join(folded_chars)


def bounded_excerpt(content: str, query_terms: Sequence[str]) -> str:
    """Produce a bounded, stable excerpt centered on the earliest lexical hit."""

    normalized = " ".join(content.split())
    if len(normalized) <= MAX_EXCERPT_CHARACTERS:
        return normalized
    offsets, folded = _casefold_alignments(normalized)
    # A folded character index n maps to offsets[n]; the fold length of the
    # original character at offset i is offsets.count(i), which bounds how far
    # a term starting at offset i can reach into the folded string.
    hits = [
        offsets[position]
        for term in query_terms
        if (position := folded.find(term.casefold())) >= 0
    ]
    if not hits:
        return normalized
    start = min(hits)
    left = max(0, start - MAX_EXCERPT_CHARACTERS // 3)
    right = min(len(normalized), left + MAX_EXCERPT_CHARACTERS)
    left = max(0, right - MAX_EXCERPT_CHARACTERS)
    excerpt = normalized[left:right]
    if left:
        excerpt = "…" + excerpt[1:]
    if right < len(normalized):
        excerpt = excerpt[:-1] + "…"
    return excerpt


def parse_preview_range(value: str | None) -> tuple[int, int]:
    """Parse one bounded HTTP byte range, rejecting ambiguous or suffix ranges."""

    if value is None:
        return 0, DEFAULT_PREVIEW_BYTES
    match = re.fullmatch(r"bytes=(\d+)-(\d*)", value.strip())
    if match is None:
        raise ValueError("invalid range")
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start + DEFAULT_PREVIEW_BYTES - 1
    if start > end:
        raise ValueError("invalid range")
    return _validate_preview_range(start, end - start + 1)


def _validate_preview_range(offset: int, length: int) -> tuple[int, int]:
    if (
        isinstance(offset, bool)
        or isinstance(length, bool)
        or not isinstance(offset, int)
        or not isinstance(length, int)
        or offset < 0
        or offset > MAX_PREVIEW_START
        or not 1 <= length <= MAX_PREVIEW_BYTES
    ):
        raise ValueError("invalid preview range")
    return offset, length


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")


def _unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="检索服务暂不可用")


def _active_knowledge_base(
    session: Session, user: User, knowledge_base_id: UUID
) -> KnowledgeBase:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    if knowledge_base.state is not KnowledgeBaseState.ACTIVE:
        raise _not_found()
    return knowledge_base


def _active_index(session: Session, knowledge_base: KnowledgeBase) -> IndexVersion | None:
    return session.scalar(
        select(IndexVersion).where(
            IndexVersion.knowledge_base_id == knowledge_base.id,
            IndexVersion.space_id == knowledge_base.space_id,
            IndexVersion.state == IndexVersionState.ACTIVE,
        )
    )


def _citation_page_number(content_type: str, page_number: int | None) -> int | None:
    if content_type.casefold().split(";", 1)[0].strip() in _NON_PAGINATED_CONTENT_TYPES:
        return None
    return page_number


def _active_candidate_rows(
    session: Session, knowledge_base: KnowledgeBase, active_index: IndexVersion
) -> Iterable[_Candidate]:
    statement = (
        select(
            Chunk, Document.source_key, DocumentVersion.content_type, Page.page_number
        )
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .outerjoin(Page, Page.id == Chunk.page_id)
        .where(
            Chunk.knowledge_base_id == knowledge_base.id,
            Chunk.space_id == knowledge_base.space_id,
            Chunk.index_version_id == active_index.id,
            DocumentVersion.space_id == knowledge_base.space_id,
            DocumentVersion.state == DocumentVersionState.READY,
            Document.state == DocumentState.ACTIVE,
        )
        .execution_options(stream_results=True)
    )
    rows = session.execute(statement).yield_per(MAX_RETRIEVAL_CANDIDATES)
    try:
        for chunk, source_name, content_type, page_number in rows:
            yield _Candidate(
                chunk=chunk,
                source_name=source_name,
                page_number=_citation_page_number(content_type, page_number),
            )
    finally:
        rows.close()


def _embedding_contract_matches(index: IndexVersion, adapter: EmbeddingAdapter) -> bool:
    try:
        return (
            index.embedding_backend == adapter.backend
            and index.embedding_model == adapter.model
            and index.embedding_dimension == adapter.dimension
            and index.embedding_contract_signature == _embedding_contract_signature(adapter)
        )
    except Exception:
        return False


def _add_bounded_candidate(
    heap: list[_BoundedCandidate], candidate: _Candidate, rank_key: tuple[float, int, str]
) -> None:
    ranked = _BoundedCandidate(rank_key=rank_key, candidate=candidate)
    if len(heap) < MAX_RETRIEVAL_CANDIDATES:
        heapq.heappush(heap, ranked)
    elif rank_key < heap[0].rank_key:
        heapq.heapreplace(heap, ranked)


def _ordered_candidates(heap: list[_BoundedCandidate]) -> list[_Candidate]:
    return [ranked.candidate for ranked in sorted(heap, key=lambda ranked: ranked.rank_key)]

def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(component * component for component in left))
    right_norm = math.sqrt(sum(component * component for component in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return -1.0
    return numerator / (left_norm * right_norm)


def _embedded_query(adapter: EmbeddingAdapter, query: str) -> list[float]:
    try:
        embedding = adapter.embed(query)
    except Exception:
        raise _unavailable() from None
    if not isinstance(embedding, list) or len(embedding) != adapter.dimension:
        raise _unavailable()
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in embedding):
        raise _unavailable()
    values = [float(value) for value in embedding]
    if any(not math.isfinite(value) for value in values):
        raise _unavailable()
    return values


def search_knowledge(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    *,
    query: str,
    limit: int,
    embedding_adapter: EmbeddingAdapter,
    citation_secret: str,
) -> list[SearchHit]:
    """Search only one readable knowledge base's active immutable index."""

    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError("result limit is out of bounds")
    normalized_query = normalize_search_query(query)
    knowledge_base = _active_knowledge_base(session, user, knowledge_base_id)
    active_index = _active_index(session, knowledge_base)
    if active_index is None:
        return []

    query_terms = normalize_lexical_terms(normalized_query)
    term_set = set(query_terms)
    query_embedding = (
        _embedded_query(embedding_adapter, normalized_query)
        if _embedding_contract_matches(active_index, embedding_adapter)
        else None
    )
    lexical_heap: list[_BoundedCandidate] = []
    vector_heap: list[_BoundedCandidate] = []
    for candidate in _active_candidate_rows(session, knowledge_base, active_index):
        lexical_score = len(term_set.intersection(candidate.chunk.lexical_terms))
        if lexical_score:
            _add_bounded_candidate(
                lexical_heap,
                candidate,
                (-float(lexical_score), candidate.chunk.ordinal, str(candidate.chunk.id)),
            )
        if (
            query_embedding is not None
            and candidate.chunk.embedding_dimension == len(query_embedding)
        ):
            similarity = _cosine_similarity(query_embedding, candidate.chunk.embedding)
            if similarity >= MIN_VECTOR_SIMILARITY:
                _add_bounded_candidate(
                    vector_heap,
                    candidate,
                    (-similarity, candidate.chunk.ordinal, str(candidate.chunk.id)),
                )

    lexical = _ordered_candidates(lexical_heap)
    vector = _ordered_candidates(vector_heap)
    candidates_by_id = {
        candidate.chunk.id: candidate for candidate in (*lexical, *vector)
    }
    ordered_ids = reciprocal_rank_fusion(
        (
            [candidate.chunk.id for candidate in lexical],
            [candidate.chunk.id for candidate in vector],
        )
    )
    return [
        SearchHit(
            excerpt=bounded_excerpt(candidate.chunk.content, query_terms),
            citation=SearchCitation(
                id=citation_id_for_chunk(candidate.chunk.id, knowledge_base.id, citation_secret),
                source_name=candidate.source_name,
                page_number=candidate.page_number,
            ),
        )
        for chunk_id in ordered_ids[:limit]
        if (candidate := candidates_by_id[chunk_id])
    ]


def _load_cited_target(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    citation_id: str,
    citation_secret: str,
) -> tuple[DocumentVersion, Page | None]:
    knowledge_base = _active_knowledge_base(session, user, knowledge_base_id)
    chunk_id = chunk_id_from_citation(citation_id, knowledge_base.id, citation_secret)
    if chunk_id is None:
        raise _not_found()
    row = session.execute(
        select(DocumentVersion, Page)
        .select_from(Chunk)
        .join(IndexVersion, IndexVersion.id == Chunk.index_version_id)
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .outerjoin(Page, Page.id == Chunk.page_id)
        .where(
            Chunk.id == chunk_id,
            Chunk.knowledge_base_id == knowledge_base.id,
            Chunk.space_id == knowledge_base.space_id,
            IndexVersion.knowledge_base_id == knowledge_base.id,
            IndexVersion.space_id == knowledge_base.space_id,
            IndexVersion.state == IndexVersionState.ACTIVE,
            DocumentVersion.space_id == knowledge_base.space_id,
            DocumentVersion.state == DocumentVersionState.READY,
            Document.state == DocumentState.ACTIVE,
        )
    ).one_or_none()
    if row is None:
        raise _not_found()
    return row


def _read_preview(
    storage: ObjectStorage,
    object_key: str,
    *,
    offset: int,
    length: int,
) -> SourcePreview:
    try:
        stored: StoredObjectRange = storage.get_object_range(
            object_key, start=offset, length=length
        )
    except ObjectRangeNotSatisfiableError:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            detail="请求范围无效",
        ) from None
    except (ObjectNotFoundError, ObjectSizeLimitError):
        raise _not_found() from None
    except Exception:
        raise _unavailable() from None
    return SourcePreview(
        data=stored.data,
        content_type=stored.content_type,
        start=stored.start,
        total_size=stored.total_size,
    )


def read_cited_source_preview(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    citation_id: str,
    *,
    offset: int,
    length: int,
    storage: ObjectStorage,
    citation_secret: str,
) -> SourcePreview:
    """Authorize and resolve a citation before reading its immutable source object."""

    offset, length = _validate_preview_range(offset, length)
    version, _ = _load_cited_target(
        session, user, knowledge_base_id, citation_id, citation_secret
    )
    return _read_preview(storage, version.object_key, offset=offset, length=length)


def read_cited_page_preview(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    citation_id: str,
    *,
    offset: int,
    length: int,
    storage: ObjectStorage,
    citation_secret: str,
) -> SourcePreview:
    """Authorize and resolve a cited page before reading its page-preview object."""

    offset, length = _validate_preview_range(offset, length)
    _, page = _load_cited_target(session, user, knowledge_base_id, citation_id, citation_secret)
    if page is None or (object_key := page.image_object_key or page.text_object_key) is None:
        raise _not_found()
    return _read_preview(storage, object_key, offset=offset, length=length)
