from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from tutor_api.learning.models import KnowledgeType, ReviewSchedule, is_aware


@dataclass(frozen=True)
class ReviewPolicy:
    memory_intervals: tuple[int, ...] = (1, 3, 7)
    concept_intervals: tuple[int, ...] = (1, 3, 7, 14)
    procedure_intervals: tuple[int, ...] = (1, 2, 5, 10)
    design_intervals: tuple[int, ...] = (2, 7, 14, 30)

    def __post_init__(self) -> None:
        names = (
            "memory_intervals",
            "concept_intervals",
            "procedure_intervals",
            "design_intervals",
        )
        for name in names:
            intervals = getattr(self, name)
            if not isinstance(intervals, (tuple, list)):
                raise ValueError("review intervals must be tuple or list")
            normalized = tuple(intervals)
            if not normalized or any(
                isinstance(day, bool) or not isinstance(day, int) or day <= 0
                for day in normalized
            ):
                raise ValueError("review intervals must be non-empty positive day counts")
            object.__setattr__(self, name, normalized)

    def intervals_for(self, knowledge_type: KnowledgeType) -> tuple[int, ...]:
        if knowledge_type is KnowledgeType.MEMORY:
            return self.memory_intervals
        if knowledge_type is KnowledgeType.CONCEPT:
            return self.concept_intervals
        if knowledge_type is KnowledgeType.PROCEDURE:
            return self.procedure_intervals
        if knowledge_type is KnowledgeType.DESIGN:
            return self.design_intervals
        raise ValueError("knowledge_type is unsupported")


def schedule_review(
    knowledge_type: KnowledgeType,
    prior_correct_streak: int,
    outcome_correct: bool,
    *,
    now: datetime,
    policy: ReviewPolicy | None = None,
) -> ReviewSchedule:
    if not is_aware(now):
        raise ValueError("now must be timezone-aware")
    if (
        isinstance(prior_correct_streak, bool)
        or not isinstance(prior_correct_streak, int)
        or prior_correct_streak < 0
    ):
        raise ValueError("prior_correct_streak must be a non-negative integer")
    if not isinstance(outcome_correct, bool):
        raise ValueError("outcome_correct must be a bool")
    if not isinstance(knowledge_type, KnowledgeType):
        raise ValueError("knowledge_type is unsupported")
    if policy is not None and not isinstance(policy, ReviewPolicy):
        raise ValueError("policy must be a ReviewPolicy")
    active_policy = policy or ReviewPolicy()
    intervals = active_policy.intervals_for(knowledge_type)
    next_streak = prior_correct_streak + 1 if outcome_correct else 0
    interval_index = min(next_streak - 1, len(intervals) - 1) if outcome_correct else 0
    interval_days = intervals[interval_index]
    return ReviewSchedule(now + timedelta(days=interval_days), next_streak, interval_days)
