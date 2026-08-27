from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from tutor_api.learning.models import CourseObjective, PendingInteraction, ReviewCandidate, is_aware


class NextStepKind(StrEnum):
    PENDING = "pending"
    REVIEW = "review"
    OBJECTIVE = "objective"
    COMPLETED = "completed"


@dataclass(frozen=True)
class NextStep:
    kind: NextStepKind
    target_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NextStepKind):
            raise ValueError("kind is unsupported")
        if self.kind is NextStepKind.COMPLETED:
            if self.target_id is not None:
                raise ValueError("completed steps cannot have a target")
        elif not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError("active steps require a target")


def next_learning_step(
    pending: PendingInteraction | None,
    reviews: Iterable[ReviewCandidate],
    objectives: Iterable[CourseObjective],
    *,
    now: datetime,
) -> NextStep:
    if not is_aware(now):
        raise ValueError("now must be timezone-aware")
    if pending is not None:
        return NextStep(NextStepKind.PENDING, pending.id)
    due_reviews = [review for review in reviews if review.due_at <= now]
    if due_reviews:
        selected_review = min(due_reviews, key=lambda review: (review.due_at, review.id))
        return NextStep(NextStepKind.REVIEW, selected_review.id)
    unmastered = [objective for objective in objectives if objective.mastery_score < objective.gate]
    if unmastered:
        selected_objective = min(unmastered, key=lambda objective: (objective.order, objective.id))
        return NextStep(NextStepKind.OBJECTIVE, selected_objective.id)
    return NextStep(NextStepKind.COMPLETED, None)
