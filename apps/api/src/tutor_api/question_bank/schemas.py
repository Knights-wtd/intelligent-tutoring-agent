import unicodedata
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from tutor_api.question_bank.models import AssessmentErrorType, QuestionType

_MAX_PROMPT_LENGTH = 10_000
_MAX_ANSWER_LENGTH = 10_000
_MAX_KEYWORD_LENGTH = 255
_MAX_EXPECTED_KEYWORD_COUNT = 50
_MAX_EXPECTED_KEYWORD_TOTAL_CHARACTERS = 4_096
_ALLOWED_TEXT_CONTROLS = {"\t", "\n", "\r"}


def _contains_disallowed_control(value: str) -> bool:
    return any(
        unicodedata.category(character) in {"Cc", "Cf"}
        and character not in _ALLOWED_TEXT_CONTROLS
        for character in value
    )


class CreateQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_citation_id: str
    question_type: QuestionType
    prompt: str
    expected_answer: str | None = None
    expected_keywords: list[str] | None = None

    @field_validator("source_citation_id")
    @classmethod
    def normalize_citation_id(cls, value: str) -> str:
        normalized = value.strip()
        return normalized

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > _MAX_PROMPT_LENGTH
            or _contains_disallowed_control(normalized)
        ):
            raise ValueError("prompt is invalid")
        return normalized

    @field_validator("expected_answer")
    @classmethod
    def normalize_expected_answer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > _MAX_ANSWER_LENGTH or _contains_disallowed_control(normalized):
            raise ValueError("expected answer is invalid")
        return normalized or None

    @field_validator("expected_keywords")
    @classmethod
    def normalize_expected_keywords(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for keyword in value:
            trimmed = keyword.strip()
            if _contains_disallowed_control(trimmed) or len(trimmed) > _MAX_KEYWORD_LENGTH:
                raise ValueError("keyword is invalid")
            if trimmed and trimmed not in seen:
                seen.add(trimmed)
                normalized.append(trimmed)
        if len(normalized) > _MAX_EXPECTED_KEYWORD_COUNT:
            raise ValueError("too many expected keywords")
        if sum(len(keyword) for keyword in normalized) > _MAX_EXPECTED_KEYWORD_TOTAL_CHARACTERS:
            raise ValueError("expected keywords exceed the character budget")
        return normalized or None

    def model_post_init(self, __context: object) -> None:
        if self.question_type in {QuestionType.CHOICE, QuestionType.SHORT}:
            if self.expected_answer is None:
                raise ValueError("choice and short questions require an expected answer")
        elif self.expected_answer is None and self.expected_keywords is None:
            raise ValueError("open questions require an expected answer or keywords")


class QuestionResponse(BaseModel):
    id: UUID
    question_version_id: UUID
    knowledge_base_id: UUID
    space_id: UUID
    version_number: int
    question_type: QuestionType
    prompt: str
    created_at: datetime


class CreateAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str

    @field_validator("answer")
    @classmethod
    def normalize_answer(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) > _MAX_ANSWER_LENGTH or _contains_disallowed_control(normalized):
            raise ValueError("answer is invalid")
        return normalized


class QuestionAttemptAssessmentResponse(BaseModel):
    id: UUID
    question_version_id: UUID
    created_at: datetime
    correct: bool
    score_basis_points: int
    error_type: AssessmentErrorType
    needs_review: bool
    mastery_basis_points: int
    mastery_evidence_count: int
    review_due_at: datetime
    review_interval_days: int
    grading_contract_version: str
    mastery_contract_version: str
    review_policy_version: str


class ReviewItemResponse(BaseModel):
    question_id: UUID
    question_version_id: UUID
    question_type: QuestionType
    prompt: str
    attempted_at: datetime
    correct: bool
    score_basis_points: int
    error_type: AssessmentErrorType
    needs_review: bool
    mastery_basis_points: int
    mastery_evidence_count: int
    review_due_at: datetime
    review_interval_days: int
    grading_contract_version: str
    mastery_contract_version: str
    review_policy_version: str


class ReviewItemsResponse(BaseModel):
    items: list[ReviewItemResponse]
    next_cursor: str | None

class AttemptHistoryItemResponse(BaseModel):
    question_id: UUID
    question_version_id: UUID
    question_type: QuestionType
    prompt: str
    attempted_at: datetime
    correct: bool
    score_basis_points: int
    error_type: AssessmentErrorType
    needs_review: bool
    mastery_basis_points: int
    mastery_evidence_count: int
    review_due_at: datetime
    review_interval_days: int
    grading_contract_version: str
    mastery_contract_version: str
    review_policy_version: str


class AttemptHistoryResponse(BaseModel):
    items: list[AttemptHistoryItemResponse]
    next_cursor: str | None
