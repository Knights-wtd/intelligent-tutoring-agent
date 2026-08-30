from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TutorStatusResponse(BaseModel):
    configured: bool
    model: str


class TutorCitationResponse(BaseModel):
    id: str
    source_name: str
    page_number: int | None


class TutorMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    kind: str
    content: str
    citations: list[TutorCitationResponse]
    created_at: datetime


class TutorConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_base_id: UUID
    title: str
    messages: list[TutorMessageResponse]
    created_at: datetime
    updated_at: datetime


class TutorSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
