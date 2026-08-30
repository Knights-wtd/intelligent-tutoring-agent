from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl


class TutorCitationResponse(BaseModel):
    id: str
    kind: Literal["knowledge", "web"] = "knowledge"
    source_name: str
    page_number: int | None
    knowledge_base_id: UUID | None = None
    knowledge_base_name: str | None = None
    space_id: UUID | None = None
    url: HttpUrl | None = None


class TutorMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
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
