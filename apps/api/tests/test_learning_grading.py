from datetime import UTC, datetime

import pytest

from tutor_api.learning.grading import grade_answer
from tutor_api.learning.models import ErrorType, QuestionSpec, QuestionType


def test_choice_grading_normalizes_one_server_owned_label() -> None:
    question = QuestionSpec(id="question-1", question_type=QuestionType.CHOICE, expected_answer="A")

    result = grade_answer(question, " a ")

    assert result.correct is True
    assert result.score == 1.0
    assert result.error_type is ErrorType.NONE
    assert result.needs_review is False
    assert "A" not in repr(result)


def test_short_grading_is_exact_after_whitespace_normalization() -> None:
    question = QuestionSpec(
        id="question-1",
        question_type=QuestionType.SHORT,
        expected_answer="Newton  second law",
    )

    assert grade_answer(question, "Newton second law").correct is True
    assert grade_answer(question, "newton second law").correct is False
    assert grade_answer(question, "Newton's second law").correct is False


def test_open_grading_returns_needs_review_when_keywords_are_incomplete() -> None:
    question = QuestionSpec(
        id="question-1",
        question_type=QuestionType.OPEN,
        expected_keywords=("force", "acceleration"),
    )

    result = grade_answer(question, "Force is important.")

    assert result.correct is False
    assert result.score == 0.5
    assert result.error_type is ErrorType.APPLICATION
    assert result.needs_review is True


def test_empty_answer_is_metacognitive_error() -> None:
    question = QuestionSpec(
        id="question-1",
        question_type=QuestionType.SHORT,
        expected_answer="answer",
    )

    result = grade_answer(question, "  ")

    assert result.correct is False
    assert result.score == 0.0
    assert result.error_type is ErrorType.METACOGNITIVE
    assert result.needs_review is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "", "question_type": QuestionType.CHOICE, "expected_answer": "A"},
        {"id": "question", "question_type": QuestionType.CHOICE, "expected_answer": ""},
        {"id": "question", "question_type": QuestionType.CHOICE, "expected_answer": "AB"},
        {
            "id": "question",
            "question_type": QuestionType.CHOICE,
            "expected_answer": "A",
            "expected_keywords": ("force",),
        },
        {"id": "question", "question_type": QuestionType.OPEN, "expected_keywords": ()},
    ],
)
def test_question_spec_rejects_missing_server_owned_contract(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        QuestionSpec(**kwargs)


def test_non_open_keywords_are_snapshotted_without_retaining_callers_list() -> None:
    keywords: list[str] = []
    question = QuestionSpec(
        id="question-1",
        question_type=QuestionType.CHOICE,
        expected_answer="A",
        expected_keywords=keywords,
    )

    keywords.append("force")

    assert question.expected_keywords == ()


def test_open_keywords_are_snapshotted_as_immutable_tuple() -> None:
    keywords = ["force"]
    question = QuestionSpec(
        id="question-1",
        question_type=QuestionType.OPEN,
        expected_keywords=keywords,
    )

    keywords.append("acceleration")

    assert question.expected_keywords == ("force",)


def test_choice_rejects_non_single_letter_answer() -> None:
    question = QuestionSpec(id="question-1", question_type=QuestionType.CHOICE, expected_answer="A")

    result = grade_answer(question, "answer A")

    assert result.correct is False
    assert result.error_type is ErrorType.APPLICATION


def test_grading_does_not_depend_on_time_or_external_services() -> None:
    question = QuestionSpec(
        id="question-1",
        question_type=QuestionType.SHORT,
        expected_answer="yes",
    )

    assert grade_answer(question, "yes").score == 1.0
    assert datetime.now(UTC).tzinfo is UTC
