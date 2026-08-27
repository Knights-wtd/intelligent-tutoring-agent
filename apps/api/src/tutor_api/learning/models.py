from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final


class QuestionType(StrEnum):
    CHOICE = "choice"
    SHORT = "short"
    OPEN = "open"


class KnowledgeType(StrEnum):
    MEMORY = "memory"
    CONCEPT = "concept"
    PROCEDURE = "procedure"
    DESIGN = "design"


class ErrorType(StrEnum):
    NONE = "none"
    METACOGNITIVE = "metacognitive"
    APPLICATION = "application"


_MIN_SCORE: Final = 0.0
_MAX_SCORE: Final = 1.0
_CHOICE_LABEL = re.compile(r"^[A-Za-z]$")


def _require_id(value: str, *, field_name: str = "id") -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_bool(value: bool, *, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a bool")


def _require_non_negative_int(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _require_positive_int(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_score(value: float, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be between 0 and 1")
    if not _MIN_SCORE <= float(value) <= _MAX_SCORE:
        raise ValueError(f"{field_name} must be between 0 and 1")


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split())


def is_aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


@dataclass(frozen=True)
class QuestionSpec:
    id: str
    question_type: QuestionType
    expected_answer: str | None = None
    expected_keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id(self.id)
        if not isinstance(self.question_type, QuestionType):
            raise ValueError("question_type is unsupported")
        if not isinstance(self.expected_keywords, (tuple, list)):
            raise ValueError("expected_keywords must be a tuple or list")
        normalized_keywords = tuple(
            _normalize_text(keyword) if isinstance(keyword, str) else ""
            for keyword in self.expected_keywords
        )
        if any(not keyword for keyword in normalized_keywords):
            raise ValueError("expected_keywords must contain non-empty values")
        object.__setattr__(self, "expected_keywords", normalized_keywords)
        if self.question_type in {QuestionType.CHOICE, QuestionType.SHORT}:
            if not isinstance(self.expected_answer, str):
                raise ValueError("expected_answer must be non-empty")
            normalized_answer = _normalize_text(self.expected_answer)
            if not normalized_answer:
                raise ValueError("expected_answer must be non-empty")
            if self.question_type is QuestionType.CHOICE and not _CHOICE_LABEL.fullmatch(
                normalized_answer
            ):
                raise ValueError("choice expected_answer must be one ASCII letter")
            if normalized_keywords:
                raise ValueError("expected_keywords are only allowed for open questions")
            object.__setattr__(self, "expected_answer", normalized_answer)
        elif not normalized_keywords:
            raise ValueError("expected_keywords must contain non-empty values")


@dataclass(frozen=True)
class GradeResult:
    correct: bool
    score: float
    error_type: ErrorType
    needs_review: bool

    def __post_init__(self) -> None:
        _require_bool(self.correct, field_name="correct")
        _require_score(self.score, field_name="score")
        if not isinstance(self.error_type, ErrorType):
            raise ValueError("error_type is unsupported")
        _require_bool(self.needs_review, field_name="needs_review")


@dataclass(frozen=True)
class AttemptOutcome:
    occurred_at: datetime
    correct: bool

    def __post_init__(self) -> None:
        if not isinstance(self.occurred_at, datetime):
            raise ValueError("occurred_at must be a datetime")
        _require_bool(self.correct, field_name="correct")


@dataclass(frozen=True)
class MasteryResult:
    score: float
    evidence_count: int

    def __post_init__(self) -> None:
        _require_score(self.score, field_name="score")
        _require_non_negative_int(self.evidence_count, field_name="evidence_count")


@dataclass(frozen=True)
class ReviewSchedule:
    due_at: datetime
    next_correct_streak: int
    interval_days: int

    def __post_init__(self) -> None:
        if not is_aware(self.due_at):
            raise ValueError("due_at must be timezone-aware")
        _require_non_negative_int(
            self.next_correct_streak,
            field_name="next_correct_streak",
        )
        _require_positive_int(self.interval_days, field_name="interval_days")


@dataclass(frozen=True)
class PendingInteraction:
    id: str

    def __post_init__(self) -> None:
        _require_id(self.id)


@dataclass(frozen=True)
class ReviewCandidate:
    id: str
    due_at: datetime

    def __post_init__(self) -> None:
        _require_id(self.id)
        if not is_aware(self.due_at):
            raise ValueError("due_at must be timezone-aware")


@dataclass(frozen=True)
class CourseObjective:
    id: str
    order: int
    mastery_score: float
    gate: float

    def __post_init__(self) -> None:
        _require_id(self.id)
        _require_non_negative_int(self.order, field_name="order")
        _require_score(self.mastery_score, field_name="mastery_score")
        _require_score(self.gate, field_name="gate")