from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tutor_api.question_bank.assessment import (
    GRADING_CONTRACT_VERSION,
    MASTERY_CONTRACT_VERSION,
    REVIEW_POLICY_VERSION,
    AssessmentResult,
    ErrorType,
    QuestionRubric,
    QuestionType,
    ReviewSchedule,
    assess_answer,
    compute_mastery_snapshot,
    normalize_answer,
    schedule_review,
)


def test_normalize_answer_uses_nfc_trim_collapsed_whitespace_and_casefold() -> None:
    assert normalize_answer("  CAFÉ\t\nStraße  ") == "café strasse"
    assert normalize_answer("Cafe\u0301") == "café"


@pytest.mark.parametrize("question_type", (QuestionType.CHOICE, QuestionType.SHORT))
def test_choice_and_short_require_normalized_exact_answer(question_type: QuestionType) -> None:
    rubric = QuestionRubric(question_type=question_type, expected_answer="  Newton's\tFirst Law ")

    result = assess_answer(rubric, "newton's first law")

    assert result.correct is True
    assert result.score_basis_points == 10_000
    assert result.error_type is ErrorType.NONE
    assert result.needs_review is False
    assert result.grading_contract_version == GRADING_CONTRACT_VERSION


@pytest.mark.parametrize("question_type", (QuestionType.CHOICE, QuestionType.SHORT))
def test_nonempty_wrong_exact_answer_is_application_error(question_type: QuestionType) -> None:
    result = assess_answer(
        QuestionRubric(question_type=question_type, expected_answer="B"),
        "A",
    )

    assert result.correct is False
    assert result.score_basis_points == 0
    assert result.error_type is ErrorType.APPLICATION
    assert result.needs_review is True


def test_open_keywords_score_phrase_coverage_and_require_all_for_correctness() -> None:
    rubric = QuestionRubric(
        question_type=QuestionType.OPEN,
        expected_answer="unused fallback",
        expected_keywords=("Kinetic Energy", "mass", "velocity"),
    )

    partial = assess_answer(rubric, "Kinetic\tenergy depends on the mass.")
    complete = assess_answer(
        rubric,
        "The kinetic energy grows with Mass and Velocity.",
    )

    assert partial.correct is False
    assert partial.score_basis_points == 6_666
    assert partial.error_type is ErrorType.APPLICATION
    assert complete.correct is True
    assert complete.score_basis_points == 10_000
    assert complete.error_type is ErrorType.NONE


def test_open_keyword_rubric_normalizes_and_deduplicates_server_keywords() -> None:
    rubric = QuestionRubric(
        question_type=QuestionType.OPEN,
        expected_keywords=("  Force ", "force", "Mass"),
    )

    result = assess_answer(rubric, "force")

    assert rubric.expected_keywords == ("force", "mass")
    assert result.score_basis_points == 5_000
    assert result.correct is False


def test_open_without_keywords_falls_back_to_normalized_exact_answer() -> None:
    rubric = QuestionRubric(
        question_type=QuestionType.OPEN,
        expected_answer="Conservation of Energy",
    )

    result = assess_answer(rubric, " conservation   OF energy ")

    assert result.correct is True
    assert result.score_basis_points == 10_000
    assert result.error_type is ErrorType.NONE


def test_empty_normalized_answer_is_always_metacognitive() -> None:
    result = assess_answer(
        QuestionRubric(question_type=QuestionType.OPEN, expected_keywords=("energy",)),
        " \t\n ",
    )

    assert result.correct is False
    assert result.score_basis_points == 0
    assert result.error_type is ErrorType.METACOGNITIVE
    assert result.needs_review is True


def test_value_objects_are_immutable_and_versions_are_explicit() -> None:
    rubric = QuestionRubric(question_type=QuestionType.SHORT, expected_answer="answer")
    result = assess_answer(rubric, "answer")
    mastery = compute_mastery_snapshot((5_000,), 10_000)
    review = schedule_review(10_000, now=datetime(2026, 8, 20, 12, tzinfo=UTC))

    with pytest.raises(FrozenInstanceError):
        rubric.expected_answer = "replacement"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.score_basis_points = 0  # type: ignore[misc]
    assert mastery.mastery_contract_version == MASTERY_CONTRACT_VERSION
    assert review.review_policy_version == REVIEW_POLICY_VERSION


def test_mastery_uses_only_five_most_recent_prior_scores_then_current_score() -> None:
    snapshot = compute_mastery_snapshot(
        prior_score_basis_points=(0, 1_000, 2_000, 3_000, 4_000, 5_000),
        current_score_basis_points=10_000,
    )

    assert snapshot.evidence_count == 6
    assert snapshot.mastery_basis_points == 4_166
    assert snapshot.mastery_contract_version == MASTERY_CONTRACT_VERSION


def test_mastery_validates_basis_point_range() -> None:
    with pytest.raises(ValueError, match="basis points"):
        compute_mastery_snapshot((), 10_001)


def test_review_schedule_is_deterministic_and_utc_only() -> None:
    now = datetime(2026, 8, 20, 12, 30, 45, tzinfo=UTC)

    perfect = schedule_review(10_000, now=now)
    partial = schedule_review(5_000, now=now)
    incorrect = schedule_review(4_999, now=now)

    assert perfect == type(perfect)(
        review_due_at=now + timedelta(days=7),
        review_interval_days=7,
        needs_review=False,
        review_policy_version=REVIEW_POLICY_VERSION,
    )
    assert partial.review_due_at == now + timedelta(days=3)
    assert partial.review_interval_days == 3
    assert partial.needs_review is True
    assert incorrect.review_due_at == now + timedelta(days=1)
    assert incorrect.review_interval_days == 1
    assert incorrect.needs_review is True


def test_review_schedule_rejects_non_utc_or_naive_time() -> None:
    with pytest.raises(ValueError, match="UTC"):
        schedule_review(10_000, now=datetime(2026, 8, 20, 12, 30, 45))


def test_assessment_module_has_no_runtime_framework_or_learning_imports() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "src"
        / "tutor_api"
        / "question_bank"
        / "assessment.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = _imported_modules(tree)

    assert not any(
        name == "sqlalchemy"
        or name.startswith("sqlalchemy.")
        or name == "fastapi"
        or name.startswith("fastapi.")
        or name == "tutor_api.learning"
        or name.startswith("tutor_api.learning.")
        for name in imported
    )

@pytest.mark.parametrize(
    ("score_basis_points", "error_type"),
    (
        (10_000, ErrorType.APPLICATION),
        (1, ErrorType.METACOGNITIVE),
    ),
)
def test_assessment_result_rejects_contradictory_direct_construction(
    score_basis_points: int, error_type: ErrorType
) -> None:
    with pytest.raises(ValueError):
        AssessmentResult(
            correct=False,
            score_basis_points=score_basis_points,
            error_type=error_type,
            needs_review=True,
        )


def test_review_schedule_rejects_contradictory_direct_construction() -> None:
    due_at = datetime(2026, 8, 20, 12, tzinfo=UTC)

    for interval_days, needs_review in ((2, True), (7, True), (3, False), (1, False)):
        with pytest.raises(ValueError):
            ReviewSchedule(
                review_due_at=due_at,
                review_interval_days=interval_days,
                needs_review=needs_review,
            )


def test_mastery_uses_bounded_window_for_a_large_one_shot_history() -> None:
    def one_shot_history():
        yield -1
        yield from (1_000 for _ in range(10_000))
        yield from (1_000, 2_000, 3_000, 4_000, 5_000)

    snapshot = compute_mastery_snapshot(one_shot_history(), 10_000)

    assert snapshot.evidence_count == 6
    assert snapshot.mastery_basis_points == 4_166


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_dependency_import_helper_detects_from_learning_imports() -> None:
    imported = _imported_modules(
        ast.parse("from tutor_api.learning.grading import GradeResult")
    )

    assert "tutor_api.learning.grading" in imported


def test_open_keywords_match_inside_chinese_sentences_without_word_boundaries() -> None:
    rubric = QuestionRubric(
        question_type=QuestionType.OPEN,
        expected_keywords=("摩擦力", "正压力"),
    )

    result = assess_answer(rubric, "答案是摩擦力很大，且正压力保持不变。")

    assert result.correct is True
    assert result.score_basis_points == 10_000


def test_ascii_word_keywords_still_require_word_boundaries() -> None:
    rubric = QuestionRubric(
        question_type=QuestionType.OPEN,
        expected_keywords=("loss",),
    )

    assert assess_answer(rubric, "pathloss").score_basis_points == 0
    assert assess_answer(rubric, "the path loss model").score_basis_points == 10_000