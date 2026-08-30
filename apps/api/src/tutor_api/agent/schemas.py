from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

AGENT_PROVIDER: Final = "faro"
AGENT_MODEL: Final = "gemini-3.7-flash-tiered"
AGENT_CONTEXT_WINDOW: Final = 32_000


class RuntimeStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    turn_id: UUID
    input: list[dict[str, Any]]
    workspace_roots: list[str]
    provider: str
    model: str
    permission_mode: Literal["bypassPermissions"] = "bypassPermissions"
    capability: str
    callback_url: AnyHttpUrl
    idempotency_key: str = Field(min_length=1, max_length=512)


class RuntimeStartResponse(BaseModel):
    execution_id: str
    native_session_id: str
    accepted_sequence: int = 0


class RuntimeForkResponse(BaseModel):
    native_session_id: str


class RuntimeHealth(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    protocol_version: str
    upstream_commit: str


class RuntimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    sequence: int = Field(gt=0)
    event_id: UUID
    event_type: str = Field(min_length=1, max_length=100)
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=512)
    turn_id: UUID | None = None
    tool_call_id: str | None = None
    subagent_id: str | None = None
    completed: bool = False
    sidecar_reference: str | None = None


class EventAck(BaseModel):
    persisted: bool = True
    accepted_sequence: int
    duplicate: bool = False


class SessionCreateRequest(BaseModel):
    knowledge_base_id: UUID
    provider: Literal["faro"] = AGENT_PROVIDER
    model: Literal["gemini-3.7-flash-tiered"] = AGENT_MODEL
    context_window: Literal[32_000] = AGENT_CONTEXT_WINDOW


class AgentLinkedContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_id: UUID | None = None
    vault_file_id: UUID | None = None
    label: str | None = Field(default=None, max_length=500)
    source_name: str | None = Field(default=None, max_length=500)
    path: str | None = Field(default=None, max_length=2048)
    heading: str | None = Field(default=None, max_length=500)
    selection: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_authorizable_resource(self) -> AgentLinkedContext:
        if self.knowledge_base_id is None and self.vault_file_id is None:
            raise ValueError("linked context requires a knowledge base or vault file")
        return self


class TurnCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    input: list[dict[str, Any]] | None = None
    linked_contexts: list[AgentLinkedContext] = Field(default_factory=list, max_length=8)
    idempotency_key: str | None = None


class RewindRequest(BaseModel):
    checkpoint_id: str = Field(min_length=1)


class AgentWorkspaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["faro"] = AGENT_PROVIDER
    model: Literal["gemini-3.7-flash-tiered"] = AGENT_MODEL
    context_window: Literal[32_000] = AGENT_CONTEXT_WINDOW
    permission_mode: Literal["bypassPermissions", "normal", "plan"]
    workspace_roots: list[str]
    mcp_enabled: bool
    skills_enabled: bool
    subagents_enabled: bool
    web_enabled: bool


class AgentSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    knowledge_base_id: UUID
    space_id: UUID
    provider: str
    model: str
    permission_mode: str
    native_session_id: str | None
    state: str
    parent_session_id: UUID | None
    last_event_sequence: int
    created_at: datetime
    updated_at: datetime
    legacy: bool = False


class SidecarDescriptor(BaseModel):
    id: UUID | str
    media_type: str = "application/json"
    size_bytes: int | None = None
    sha256: str | None = None
