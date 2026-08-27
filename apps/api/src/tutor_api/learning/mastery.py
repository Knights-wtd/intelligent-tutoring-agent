from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from tutor_api.learning.models import AttemptOutcome, MasteryResult, is_aware

_MAX_EVIDENCE = 5


def compute_mastery(
    attempts: Iterable[AttemptOutcome], *, now: datetime | None = None
) -> MasteryResult:
    """Return a bounded, recency-weighted mastery estimate from durable attempts."""
    if now is not None and not is_aware(now):
        raise ValueError("now must be timezone-aware")
    ordered = sorted(attempts, key=lambda attempt: attempt.occurred_at)
    for attempt in ordered:
        if not is_aware(attempt.occurred_at):
            raise ValueError("occurred_at must be timezone-aware")
        if now is not None and attempt.occurred_at > now:
            raise ValueError("occurred_at must not be in the future")
    recent = ordered[-_MAX_EVIDENCE:]
    if not recent:
        return MasteryResult(0.0, 0)
    weights = tuple(range(1, len(recent) + 1))
    weighted_score = sum(
        weight for weight, attempt in zip(weights, recent, strict=True) if attempt.correct
    ) / sum(weights)
    evidence_cap = 0.6 if len(recent) == 1 else 0.8 if len(recent) == 2 else 1.0
    return MasteryResult(min(weighted_score, evidence_cap), len(recent))
