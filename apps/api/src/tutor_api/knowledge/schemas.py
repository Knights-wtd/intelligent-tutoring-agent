from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


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
    ingestion_job_id: UUID
    space_id: UUID
    knowledge_base_id: UUID
    source_name: str
    version_number: int
    content_sha256: str
    content_type: str
    document_state: str
    version_state: str
    job_state: str
    created_at: datetime
