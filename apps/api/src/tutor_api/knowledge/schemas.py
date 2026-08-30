from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tutor_api.knowledge.retrieval import MAX_RESULTS, normalize_search_query


class CreateKnowledgeBaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not 1 <= len(normalized) <= 120:
            raise ValueError("知识库名称长度必须为 1 到 120 个字符")
        return normalized


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    space_id: UUID
    name: str
    state: str
    created_at: datetime
    updated_at: datetime


class KnowledgeUploadResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    source_name: str
    created_at: datetime


class KnowledgeDocumentStatusResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    processing_state: Literal["processing", "searchable", "failed"]


class KnowledgeDocumentResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    source_name: str
    processing_state: Literal["processing", "searchable", "failed"]
    created_at: datetime


class KnowledgeGraphNodeResponse(BaseModel):
    id: UUID
    note_id: UUID | None
    title: str
    kind: str
    source_pointers: list[str]


class KnowledgeGraphEdgeResponse(BaseModel):
    id: UUID
    source_id: UUID
    target_id: UUID
    kind: str
    relation: str
    source_pointer: str


class KnowledgeGraphResponse(BaseModel):
    knowledge_base_id: UUID
    nodes: list[KnowledgeGraphNodeResponse]
    edges: list[KnowledgeGraphEdgeResponse]

class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    limit: int = Field(default=10, ge=1, le=MAX_RESULTS)
    # full=true 时返回完整分块原文（上限约 1200 字/块）而非 500 字检索摘要。
    full: bool = False

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return normalize_search_query(value)


class KnowledgeCitationResponse(BaseModel):
    id: str
    source_name: str
    page_number: int | None


class KnowledgeSearchResultResponse(BaseModel):
    excerpt: str
    citation: KnowledgeCitationResponse


class KnowledgeSearchResponse(BaseModel):
    results: list[KnowledgeSearchResultResponse]


class KnowledgeDocumentChunkResponse(BaseModel):
    ordinal: int
    content: str
    page_number: int | None


class CreateKnowledgeCandidateBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_version_id: UUID


class ConfirmKnowledgeCandidateBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_note_ids: list[UUID]
    accepted_link_ids: list[UUID]


class KnowledgeCandidateNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ordinal: int
    candidate_key: str
    title: str
    kind: str
    parent_key: str | None
    markdown: str
    source_pointers: list[str]
    formula_verification: dict[str, object] | None
    external_sources: list[dict[str, str]]
    review_state: str


class KnowledgeCandidateLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ordinal: int
    kind: str
    relation: str
    source_key: str
    target_key: str
    source_pointer: str
    occurrence: str | None
    context: str
    review_state: str


class KnowledgeCandidateBatchResponse(BaseModel):
    id: UUID
    document_id: UUID
    document_version_id: UUID
    generation_number: int
    state: str
    failure_code: str | None
    notes: list[KnowledgeCandidateNoteResponse]
    links: list[KnowledgeCandidateLinkResponse]
    created_at: datetime
    updated_at: datetime

class KnowledgeWorkspaceDocumentResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    source_name: str
    content_type: str
    processing_state: Literal["processing", "searchable", "failed"]
    created_at: datetime
    updated_at: datetime


class KnowledgeNoteSummaryResponse(BaseModel):
    id: UUID
    title: str
    kind: str
    parent_id: UUID | None
    source_document_id: UUID | None
    updated_at: datetime


class KnowledgeWorkspaceResponse(BaseModel):
    knowledge_base_id: UUID
    documents: list[KnowledgeWorkspaceDocumentResponse]
    candidate_batch: KnowledgeCandidateBatchResponse | None
    notes: list[KnowledgeNoteSummaryResponse]


class KnowledgeNoteReferenceResponse(BaseModel):
    id: UUID
    title: str


class KnowledgeNoteDetailResponse(BaseModel):
    id: UUID
    title: str
    kind: str
    markdown: str
    source_markers: list[str]
    source_document_id: UUID | None
    source_name: str | None
    parent: KnowledgeNoteReferenceResponse | None
    children: list[KnowledgeNoteReferenceResponse]
    updated_at: datetime
