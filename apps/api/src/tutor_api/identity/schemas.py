import re
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


class RegistrationRequest(BaseModel):
    email: str
    username: str
    password: str = Field(min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("请输入有效邮箱地址")
        return normalized

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip()
        if not _USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError("用户名只能包含字母、数字、下划线或连字符")
        return normalized.casefold()


class LoginRequest(BaseModel):
    identifier: str = Field(validation_alias=AliasChoices("identifier", "email"))
    password: str

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if "@" in normalized:
            normalized = normalized.casefold()
            if not _EMAIL_PATTERN.fullmatch(normalized):
                raise ValueError("请输入有效邮箱地址")
            return normalized
        if not _USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError("请输入有效邮箱或用户名")
        return normalized.casefold()


class UserSummary(BaseModel):
    id: UUID
    email: str
    username: str


class SpaceSummary(BaseModel):
    id: UUID
    kind: str
    name: str


class RegistrationResponse(BaseModel):
    user: UserSummary
    personal_space: SpaceSummary


class LoginResponse(BaseModel):
    user: UserSummary


class CurrentUserResponse(LoginResponse):
    personal_space: SpaceSummary
