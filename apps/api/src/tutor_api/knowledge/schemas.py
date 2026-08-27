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


class KnowledgeGraphNodeResponse(BaseModel):
    id: UUID
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
