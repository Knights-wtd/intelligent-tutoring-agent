# Question Bank Task 5 — Owner Attempt History Plan

## Goal

Expose a bounded, owner-only read view of the current user's immutable question assessment history. This complements the current `review-items` view: review items show only the latest actionable assessment, while history shows prior assessments for one question version without exposing answer keys or provenance.

## Scope and non-goals

- Add only:
  `GET /api/v1/knowledge-bases/{knowledge_base_id}/question-versions/{question_version_id}/attempt-history`
- Reuse the existing readable knowledge-base authorization and require the requested question version to belong to the requested knowledge base and space.
- Return only assessments whose `user_id` is the current user.
- Return newest assessment first using `(attempted_at DESC, assessment.id DESC)`.
- Use bounded keyset pagination with `limit=1..50`, default `20`, and a server-validated cursor of `(attempted_at, assessment_id)`; fetch at most `limit + 1`.
- No migration, no writes, no LLM grading, no teacher analytics, no cross-user view, and no unbounded export or total count.

## Safe response contract

Envelope:

```text
items: list[AttemptHistoryItemResponse]
next_cursor: string | null
```

Item fields exactly:

```text
question_id
question_version_id
question_type
prompt
attempted_at
correct
score_basis_points
error_type
needs_review
mastery_basis_points
mastery_evidence_count
review_due_at
review_interval_days
grading_contract_version
mastery_contract_version
review_policy_version
```

The endpoint must not return or load `answer`, `expected_answer`, `expected_keywords`, source/provenance fields, `document_version_id`, `user_id`, `space_id`, request hashes, attempt/assessment identifiers except the opaque internal assessment ID used inside the cursor, streak fields, or idempotency headers.

## Authorization and query rules

1. Call `get_readable_knowledge_base()` first; inaccessible knowledge bases remain hidden `404`.
2. Join `QuestionAttemptAssessment` to `QuestionVersion` and `Question` with matching knowledge-base and space predicates.
3. Require `QuestionAttemptAssessment.user_id == current_user.id` and `QuestionAttemptAssessment.question_version_id == requested version`.
4. Select only the safe columns with `load_only(...)`; use `attempted_at` from the related attempt, not assessment creation time, as the public history timestamp.
5. Order by `QuestionAttempt.created_at DESC, QuestionAttemptAssessment.id DESC`; cursor predicate must match the order exactly.
6. Return `404` if the requested question version is not in the readable knowledge base, regardless of whether another tenant has that ID.

## Focused acceptance checks

1. Owner sees their own assessment history newest-first with the exact safe field set.
2. Private answer/key/rubric/provenance/user/request-hash sentinels are absent and private ORM columns are deferred.
3. A different readable user sees no other user's history; inaccessible or cross-KB version is hidden `404`; GET performs no writes.
4. Multiple attempts for one version are all returned, including older correct and newer incorrect evidence; no latest-only collapse is applied.
5. Keyset pagination is stable and bounded with no duplicates/skips; invalid scope is not applicable, invalid limit/cursor returns `422`, and cursors over 256 characters are rejected.
6. Focused tests, targeted Ruff, and a changed-file `git diff --check` pass before independent SPEC and QUALITY/SECURITY review.

## Allowed files

```text
apps/api/src/tutor_api/question_bank/service.py
apps/api/src/tutor_api/question_bank/schemas.py
apps/api/src/tutor_api/question_bank/router.py
apps/api/tests/test_question_bank.py
```

Do not modify models, migrations, assessment.py, `tutor_api.learning`, Task 10 files/tests, `.env.example`, or root Git state. Do not run Docker, Compose, Alembic, full suite, coverage, or real PostgreSQL performance tests.

## Stop rule

Initial implementation plus at most one targeted correction for each concrete acceptance rule. If the same rule fails again after that correction, record the failure and stop; do not chase arbitrary coverage or polish.