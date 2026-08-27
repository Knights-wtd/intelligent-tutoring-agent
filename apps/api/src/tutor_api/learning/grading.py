from __future__ import annotations

import re
import unicodedata

from tutor_api.learning.models import ErrorType, GradeResult, QuestionSpec, QuestionType

_CHOICE_LABEL = re.compile(r"^[A-Za-z]$")
_WORD_KEYWORD = re.compile(r"^[A-Za-z0-9_]+$")


def grade_answer(question: QuestionSpec, user_answer: str) -> GradeResult:
    """Grade one answer using only the server-owned question contract."""
    if not isinstance(user_answer, str):
        raise ValueError("user_answer must be a string")
    answer = _normalize(user_answer)
    if not answer:
        return GradeResult(False, 0.0, ErrorType.METACOGNITIVE, False)
    if question.question_type is QuestionType.CHOICE:
        return _grade_choice(question, answer)
    if question.question_type is QuestionType.SHORT:
        return _grade_short(question, answer)
    return _grade_open(question, answer)


def _grade_choice(question: QuestionSpec, answer: str) -> GradeResult:
    expected = _normalize(question.expected_answer or "")
    correct = bool(_CHOICE_LABEL.fullmatch(answer)) and answer.casefold() == expected.casefold()
    return GradeResult(
        correct,
        1.0 if correct else 0.0,
        ErrorType.NONE if correct else ErrorType.APPLICATION,
        False,
    )


def _grade_short(question: QuestionSpec, answer: str) -> GradeResult:
    expected = _normalize(question.expected_answer or "")
    correct = answer == expected
    return GradeResult(
        correct,
        1.0 if correct else 0.0,
        ErrorType.NONE if correct else ErrorType.APPLICATION,
        False,
    )


def _grade_open(question: QuestionSpec, answer: str) -> GradeResult:
    normalized_answer = answer.casefold()
    matches = sum(
        _contains_keyword(normalized_answer, _normalize(keyword).casefold())
        for keyword in question.expected_keywords
    )
    score = matches / len(question.expected_keywords)
    correct = matches == len(question.expected_keywords)
    return GradeResult(
        correct,
        score,
        ErrorType.NONE if correct else ErrorType.APPLICATION,
        not correct,
    )


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split())


def _contains_keyword(answer: str, keyword: str) -> bool:
    if _WORD_KEYWORD.fullmatch(keyword):
        return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", answer) is not None
    return keyword in answer
