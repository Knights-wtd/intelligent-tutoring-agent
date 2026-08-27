from datetime import UTC, datetime, timedelta

import pytest

from tutor_api.learning.mastery import compute_mastery
from tutor_api.learning.models import AttemptOutcome, KnowledgeType
from tutor_api.learning.scheduler import ReviewPolicy, schedule_review


def at(day: int) -> datetime:
    return datetime(2026, 8, day, tzinfo=UTC)


def test_empty_history_has_zero_mastery() -> None:
    result = compute_mastery((), now=at(10))

    assert result.score == 0.0
    assert result.evidence_count == 0


def test_recent_outcomes_receive_more_weight() -> None:
    result = compute_mastery(
        (AttemptOutcome(at(1), True), AttemptOutcome(at(9), False)), now=at(10)
    )

    assert 0.0 < result.score < 0.5


def test_one_and_two_correct_attempts_cannot_report_full_mastery() -> None:
    one = compute_mastery((AttemptOutcome(at(9), True),), now=at(10))
    two = compute_mastery((AttemptOutcome(at(8), True), AttemptOutcome(at(9), True)), now=at(10))

    assert one.score <= 0.6
    assert two.score <= 0.8
    assert one.score < two.score < 1.0


def test_three_recent_correct_attempts_can_reach_full_mastery() -> None:
    result = compute_mastery(
        (AttemptOutcome(at(7), True), AttemptOutcome(at(8), True), AttemptOutcome(at(9), True)),
        now=at(10),
    )

    assert result.score == 1.0
    assert result.evidence_count == 3


def test_mastery_uses_only_five_most_recent_attempts() -> None:
    attempts = tuple(AttemptOutcome(at(day), False) for day in range(1, 5)) + tuple(
        AttemptOutcome(at(day), True) for day in range(5, 10)
    )

    result = compute_mastery(attempts, now=at(10))

    assert result.score == 1.0
    assert result.evidence_count == 5


@pytest.mark.parametrize("correct", ("false", 1, None))
def test_attempt_outcome_rejects_non_boolean_correctness(correct: object) -> None:
    with pytest.raises(ValueError):
        AttemptOutcome(at(9), correct)


def test_mastery_rejects_naive_or_future_timestamps() -> None:
    with pytest.raises(ValueError):
        compute_mastery((AttemptOutcome(datetime(2026, 8, 9), True),), now=at(10))
    with pytest.raises(ValueError):
        compute_mastery((AttemptOutcome(at(11), True),), now=at(10))
    with pytest.raises(ValueError):
        compute_mastery((), now=datetime(2026, 8, 10))


def test_review_schedule_advances_and_resets_after_error() -> None:
    policy = ReviewPolicy()

    advanced = schedule_review(KnowledgeType.CONCEPT, 1, True, now=at(10), policy=policy)
    reset = schedule_review(KnowledgeType.CONCEPT, 3, False, now=at(10), policy=policy)

    assert advanced.next_correct_streak == 2
    assert advanced.interval_days == 3
    assert advanced.due_at == at(10) + timedelta(days=3)
    assert reset.next_correct_streak == 0
    assert reset.interval_days == 1
    assert reset.due_at == at(10) + timedelta(days=1)


def test_review_schedule_rejects_invalid_policy_and_time() -> None:
    with pytest.raises(ValueError):
        schedule_review(KnowledgeType.MEMORY, -1, True, now=at(10))
    with pytest.raises(ValueError):
        schedule_review(KnowledgeType.MEMORY, 1.5, True, now=at(10))
    with pytest.raises(ValueError):
        schedule_review(KnowledgeType.MEMORY, 1, "false", now=at(10))
    with pytest.raises(ValueError):
        schedule_review(KnowledgeType.MEMORY, 0, True, now=datetime(2026, 8, 10))
    with pytest.raises(ValueError):
        schedule_review(KnowledgeType.MEMORY, 0, True, now="2026-08-20")
    with pytest.raises(ValueError):
        ReviewPolicy(memory_intervals=())
    with pytest.raises(ValueError):
        ReviewPolicy(memory_intervals=(0,))


def test_review_policy_snapshots_mutable_intervals() -> None:
    intervals = [1, 3]
    policy = ReviewPolicy(memory_intervals=intervals)

    intervals.clear()

    assert policy.memory_intervals == (1, 3)
