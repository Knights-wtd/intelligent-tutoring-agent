from datetime import UTC, datetime, timedelta

import pytest

from tutor_api.learning.models import CourseObjective, PendingInteraction, ReviewCandidate
from tutor_api.learning.policy import NextStepKind, next_learning_step


def now() -> datetime:
    return datetime(2026, 8, 20, 12, tzinfo=UTC)


def test_pending_interaction_has_highest_priority() -> None:
    step = next_learning_step(
        PendingInteraction("pending-1"),
        (ReviewCandidate("review-1", now() - timedelta(days=1)),),
        (CourseObjective("objective-1", 0, 0.0, 0.8),),
        now=now(),
    )

    assert step.kind is NextStepKind.PENDING
    assert step.target_id == "pending-1"


def test_due_review_beats_unmastered_objective_and_is_stably_ordered() -> None:
    step = next_learning_step(
        None,
        (
            ReviewCandidate("later", now() - timedelta(hours=1)),
            ReviewCandidate("earlier", now() - timedelta(days=1)),
        ),
        (CourseObjective("objective-1", 0, 0.0, 0.8),),
        now=now(),
    )

    assert step.kind is NextStepKind.REVIEW
    assert step.target_id == "earlier"


def test_first_unmastered_objective_wins_by_order_then_id() -> None:
    step = next_learning_step(
        None,
        (),
        (
            CourseObjective("z", 1, 0.0, 0.8),
            CourseObjective("b", 0, 0.0, 0.8),
            CourseObjective("a", 0, 0.0, 0.8),
            CourseObjective("done", 0, 0.8, 0.8),
        ),
        now=now(),
    )

    assert step.kind is NextStepKind.OBJECTIVE
    assert step.target_id == "a"


def test_completed_has_no_target_and_no_answer_data() -> None:
    step = next_learning_step(None, (), (CourseObjective("done", 0, 1.0, 0.8),), now=now())

    assert step.kind is NextStepKind.COMPLETED
    assert step.target_id is None
    assert "answer" not in repr(step).lower()


def test_policy_models_reject_invalid_values_or_naive_time() -> None:
    with pytest.raises(ValueError):
        CourseObjective("", 0, 0.0, 0.8)
    with pytest.raises(ValueError):
        CourseObjective("id", -1, 0.0, 0.8)
    with pytest.raises(ValueError):
        CourseObjective("id", 0, 1.1, 0.8)
    with pytest.raises(ValueError):
        ReviewCandidate("id", datetime(2026, 8, 20))
    with pytest.raises(ValueError):
        next_learning_step(None, (), (), now=datetime(2026, 8, 20))
