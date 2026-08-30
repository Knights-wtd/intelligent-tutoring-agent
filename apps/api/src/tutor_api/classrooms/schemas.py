from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from tutor_api.spaces.schemas import SpaceResponse


class CreateClassroomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ClassroomMemberResponse(BaseModel):
    user_id: UUID
    role: str


class ClassroomResponse(BaseModel):
    id: UUID
    name: str
    space: SpaceResponse
    membership: ClassroomMemberResponse


class CreatedClassroomResponse(ClassroomResponse):
    invite_code: str


class JoinClassroomRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class MemberUpdateRequest(BaseModel):
    role: str | None = None
    remove: bool = False

    @model_validator(mode="after")
    def validate_action(self) -> "MemberUpdateRequest":
        if self.remove == (self.role is not None):
            raise ValueError("请提供角色变更或移除操作")
        if self.role is not None and self.role not in {"teacher", "student"}:
            raise ValueError("角色必须是 teacher 或 student")
        return self


class CreateInviteRequest(BaseModel):
    expires_in_hours: int = Field(ge=1, le=24 * 30)
    max_uses: int = Field(ge=1, le=100)


class InviteResponse(BaseModel):
    code: str
    expires_at: datetime
    max_uses: int
