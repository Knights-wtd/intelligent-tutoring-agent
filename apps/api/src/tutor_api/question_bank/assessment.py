"""Native, deterministic Question Bank assessment primitives.

This module deliberately has no persistence, HTTP, model-provider, or learning-runtime
integration. It freezes the v1 scoring, mastery, and review contracts so they can later
be persisted unchanged as immutable assessment evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

BASIS_POINTS_MAX = 10_000
MAX_PRIOR_MASTERY_EVIDENCE = 5

GRADING_CONTRACT_VERSION = "question-bank-grading-v1"
MASTERY_CONTRACT_VERSION = "question-bank-mastery-v1"
REVIEW_POLICY_VERSION = "question-bank-review-v1"


class QuestionType(StrEnum):
    """Question types supported by the native v1 grading contract."""

    CHOICE = "choice"
    SHORT = "short"
    OPEN = "open"


class ErrorType(StrEnum):
    """Safe, deterministic error classification for one assessment."""

    NONE = "none"
    METACOGNITIVE = "metacognitive"
    APPLICATION = "application"


@dataclass(frozen=True, slots=True)
class QuestionRubric:
    """Server-only immutable rubric consumed by :func:`assess_answer`.

    ``expected_keywords`` are normalized and de-duplicated at construction time, making
    keyword coverage deterministic even if a caller supplies equivalent raw strings.
    """

    question_type: QuestionType
    expected_answer: str | None = None
    expected_keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.question_type, QuestionType):
            raise ValueError("question_type is unsupported")

        normalized_answer = _normalize_optional(self.expected_answer, "expected_answer")
        normalized_keywords = _normalize_keywords(self.expected_keywords)

        if self.question_type in (QuestionType.CHOICE, QuestionType.SHORT):
            if not normalized_answer:
                raise ValueError("choice and short rubrics require an expected_answer")
        elif not normalized_keywords and not normalized_answer:
            raise ValueError("open rubrics require expected_answer or expected_keywords")

        object.__setattr__(self, "expected_answer", normalized_answer)
        object.__setattr__(self, "expected_keywords", normalized_keywords)


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    """Immutable outcome of deterministic grading, safe to persist as evidence."""

    correct: bool
    score_basis_points: int
    error_type: ErrorType
    needs_review: bool
    grading_contract_version: str = GRADING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _validate_basis_points(self.score_basis_points)
        if not isinstance(self.correct, bool):
            raise ValueError("correct must be a bool")
        if not isinstance(self.error_type, ErrorType):
            raise ValueError("error_type is unsupported")
        if not isinstance(self.needs_review, bool):
            raise ValueError("needs_review must be a bool")
        if self.needs_review is self.correct:
            raise ValueError("needs_review must be the inverse of correct")
        if self.correct and (
            self.score_basis_points != BASIS_POINTS_MAX
            or self.error_type is not ErrorType.NONE
        ):
            raise ValueError("correct assessments must be complete and error-free")
        if not self.correct and self.score_basis_points == BASIS_POINTS_MAX:
            raise ValueError("incorrect assessments cannot receive full credit")
        if self.error_type is ErrorType.METACOGNITIVE and self.score_basis_points != 0:
            raise ValueError("metacognitive assessments must have zero score")
        if not self.correct and self.error_type is ErrorType.NONE:
            raise ValueError("incorrect assessments require an error_type")
        if self.grading_contract_version != GRADING_CONTRACT_VERSION:
            raise ValueError("grading_contract_version is unsupported")


@dataclass(frozen=True, slots=True)
class MasterySnapshot:
    """Bounded per-user/per-question-version mastery calculation result."""

    mastery_basis_points: int
    evidence_count: int
    mastery_contract_version: str = MASTERY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _validate_basis_points(self.mastery_basis_points)
        if (
            isinstance(self.evidence_count, bool)
            or not isinstance(self.evidence_count, int)
            or not 1 <= self.evidence_count <= MAX_PRIOR_MASTERY_EVIDENCE + 1
        ):
            raise ValueError("evidence_count is outside the supported bounded window")
        if self.mastery_contract_version != MASTERY_CONTRACT_VERSION:
            raise ValueError("mastery_contract_version is unsupported")


@dataclass(frozen=True, slots=True)
class ReviewSchedule:
    """Immutable UTC review evidence derived only from the assessment score."""

    review_due_at: datetime
    review_interval_days: int
    needs_review: bool
    review_policy_version: str = REVIEW_POLICY_VERSION

    def __post_init__(self) -> None:
        _require_utc(self.review_due_at)
        if (
            isinstance(self.review_interval_days, bool)
            or not isinstance(self.review_interval_days, int)
            or self.review_interval_days <= 0
        ):
            raise ValueError("review_interval_days must be a positive integer")
        if not isinstance(self.needs_review, bool):
            raise ValueError("needs_review must be a bool")
        if self.review_interval_days not in (1, 3, 7):
            raise ValueError("review_interval_days must be one of 1, 3, or 7")
        if self.needs_review and self.review_interval_days not in (1, 3):
            raise ValueError("needs_review schedules must use a 1 or 3 day interval")
        if not self.needs_review and self.review_interval_days != 7:
            raise ValueError("completed schedules must use a 7 day interval")
        if self.review_policy_version != REVIEW_POLICY_VERSION:
            raise ValueError("review_policy_version is unsupported")


def normalize_answer(value: str) -> str:
    """Normalize an answer with the frozen v1 comparison contract."""
    if not isinstance(value, str):
        raise ValueError("answer must be a string")
    return " ".join(unicodedata.normalize("NFC", value).strip().split()).casefold()


def assess_answer(rubric: QuestionRubric, answer: str) -> AssessmentResult:
    """Grade one answer using only the supplied server-side immutable rubric."""
    if not isinstance(rubric, QuestionRubric):
        raise ValueError("rubric must be a QuestionRubric")

    normalized_answer = normalize_answer(answer)
    if not normalized_answer:
        return _result(
            correct=False,
            score_basis_points=0,
            error_type=ErrorType.METACOGNITIVE,
        )

    if rubric.question_type is QuestionType.OPEN and rubric.expected_keywords:
        matched_keywords = sum(
            _contains_normalized_phrase(normalized_answer, keyword)
            for keyword in rubric.expected_keywords
        )
        keyword_count = len(rubric.expected_keywords)
        score_basis_points = matched_keywords * BASIS_POINTS_MAX // keyword_count
        return _result(
            correct=matched_keywords == keyword_count,
            score_basis_points=score_basis_points,
            error_type=ErrorType.NONE
            if matched_keywords == keyword_count
            else ErrorType.APPLICATION,
        )

    correct = normalized_answer == rubric.expected_answer
    return _result(
        correct=correct,
        score_basis_points=BASIS_POINTS_MAX if correct else 0,
        error_type=ErrorType.NONE if correct else ErrorType.APPLICATION,
    )


def compute_mastery_snapshot(
    prior_score_basis_points: Iterable[int],
    current_score_basis_points: int,
) -> MasterySnapshot:
    """Return the integer mean of the five most recent prior scores plus current.

    ``prior_score_basis_points`` must be supplied in chronological order from oldest to
    newest. Earlier items beyond the last five are intentionally ignored.
    """
    recent_prior_scores: deque[int] = deque(maxlen=MAX_PRIOR_MASTERY_EVIDENCE)
    recent_prior_scores.extend(prior_score_basis_points)
    for score in recent_prior_scores:
        _validate_basis_points(score)
    _validate_basis_points(current_score_basis_points)

    evidence = (*recent_prior_scores, current_score_basis_points)
    return MasterySnapshot(
        mastery_basis_points=sum(evidence) // len(evidence),
        evidence_count=len(evidence),
    )


def schedule_review(score_basis_points: int, *, now: datetime) -> ReviewSchedule:
    """Return the frozen v1 UTC review schedule for one score."""
    _validate_basis_points(score_basis_points)
    _require_utc(now)

    if score_basis_points == BASIS_POINTS_MAX:
        interval_days = 7
    elif score_basis_points >= BASIS_POINTS_MAX // 2:
        interval_days = 3
    else:
        interval_days = 1

    return ReviewSchedule(
        review_due_at=now + timedelta(days=interval_days),
        review_interval_days=interval_days,
        needs_review=score_basis_points != BASIS_POINTS_MAX,
    )


def _result(
    *, correct: bool, score_basis_points: int, error_type: ErrorType
) -> AssessmentResult:
    return AssessmentResult(
        correct=correct,
        score_basis_points=score_basis_points,
        error_type=error_type,
        needs_review=not correct,
    )


def _normalize_optional(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string or None")
    return normalize_answer(value)


def _normalize_keywords(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("expected_keywords must be an iterable of strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("expected_keywords must contain only strings")
        keyword = normalize_answer(value)
        if keyword and keyword not in seen:
            seen.add(keyword)
            normalized.append(keyword)
    return tuple(normalized)


_WORD_KEYWORD = re.compile(r"^[A-Za-z0-9_]+$")


def _contains_normalized_phrase(answer: str, phrase: str) -> bool:
    """Match a normalized phrase without treating a substring of a word as present.

    ``\\w`` also matches CJK characters, so boundary assertions around a Chinese
    keyword would almost never hold inside a natural sentence. Boundaries apply
    only to pure ASCII-word keywords; every other keyword falls back to a
    substring match.
    """
    if _WORD_KEYWORD.fullmatch(phrase):
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", answer) is not None
    return phrase in answer


def _validate_basis_points(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= BASIS_POINTS_MAX
    ):
        raise ValueError(f"basis points must be an integer from 0 to {BASIS_POINTS_MAX}")


def _require_utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is not UTC:
        raise ValueError("datetime must be UTC-aware")
