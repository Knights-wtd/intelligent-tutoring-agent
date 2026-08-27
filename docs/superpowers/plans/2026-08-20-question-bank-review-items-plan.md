# Question Bank Task 4 — Owner Review Queue Plan

**Goal:** Expose the smallest usable wrong-question / spaced-review view from the existing immutable Question Bank assessment ledger. The API is a strictly owner-only, read-only current view. It does not add grading, new persistence, LLMs, Agent orchestration, teacher analytics, or Task 10 ingestion work.

## Scope and non-goals

- Add only `GET /api/v1/knowledge-bases/{knowledge_base_id}/review-items`.
- Reuse `get_readable_knowledge_base()` only to establish access to the knowledge base, then additionally require `QuestionAttemptAssessment.user_id == current_user.id` on every result.
- Return exactly one record per question version: its latest assessment for the current user, only if that latest assessment has `needs_review=true`.
- A later correct submission removes the version from this current view; a later incorrect submission makes it return again. No record is updated or deleted.
- This is not a teacher view, cross-user view, permanent historical-error archive, review-completion workflow, answer-explanation feature, or task scheduler.
- No migration is needed: the existing question, version, assessment, and attempt tables already carry all required relationships and public assessment evidence.

## Request contract

```http
GET /api/v1/knowledge-bases/{knowledge_base_id}/review-items?scope=all|due&limit=1..50&cursor=<optional>
```

- `scope` defaults to `all`.
  - `all`: latest owner assessments where `needs_review=true`.
  - `due`: the same items restricted to `review_due_at <= request UTC now`.
- `limit` defaults to 20 and is bounded to 1..50.
- `cursor` is optional, max 256 characters, and is a server-validated continuation for the stable tuple `(review_due_at, assessment.created_at, assessment.id)`. It carries no user, knowledge-base, answer, rubric, source, or request-key information. Invalid/overlong cursors return 422.
- No offset, count total, unbounded export, or cross-request snapshot guarantee. Records may move between pages if a user submits a new answer between requests.

## Ordering and query semantics

1. Authorize the knowledge base with the existing hidden-404 readable access helper.
2. Select only owner-scoped assessment evidence in the knowledge base and space.
3. Select the latest assessment for each `(user_id, question_version_id)` using the stable newest ordering `assessment.created_at DESC, assessment.id DESC`.
4. Keep only latest rows whose `needs_review` is true; optionally apply due filtering.
5. Order resulting review items ascending by `review_due_at`, then `assessment.created_at`, then `assessment.id`; fetch at most `limit + 1` and return `next_cursor` only if more data exists.
6. Use `load_only(...)` for all three ORM models so private answer/rubric/provenance/identity columns are not fetched merely to be omitted from serialization.

## Safe response contract

Each item may contain only:

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

The envelope contains `items` and `next_cursor` only. It must not return or load as public projection:

```text
answer, expected_answer, expected_keywords,
source_chunk_id, source_chunk_ordinal, source_pointer,
source_content_sha256, source_index_signature, document_version_id,
provenance/citation, user_id, space_id, owner_user_id, created_by_user_id,
request_key_hash, Idempotency-Key, attempt_id, assessment_id,
prior_correct_streak, next_correct_streak
```

## Allowed files

```text
apps/api/src/tutor_api/question_bank/service.py
apps/api/src/tutor_api/question_bank/schemas.py
apps/api/src/tutor_api/question_bank/router.py
apps/api/tests/test_question_bank.py
```

Do not edit models, migrations, assessment.py, `tutor_api.learning`, learning tests, Task 10 protected files/tests, `.env.example`, root Git state, or prior Task 3A/3B stop-rule tests.

## TDD acceptance checks

1. Owner gets the exact safe projection for an incorrect/latest assessment; field set is exact.
2. Private unique sentinel values in attempt answer, rubric, source metadata, IDs, and idempotency hash are absent from response and the query projection avoids their public loading.
3. A different readable user cannot see the owner's review item; no-access KB remains hidden 404; GET writes neither attempts nor assessments.
4. Earlier wrong then latest correct is excluded; a newer wrong answer returns the newest evidence.
5. `all` includes future-due owner items while `due` excludes them; past-due appears in both.
6. Keyset pagination has stable `(review_due_at, created_at, id)` ordering with no duplicates/skips for a static fixture; malformed/overlong cursor and invalid limit return 422.
7. Focused test module, targeted Ruff, and four-file diff check pass; then independent SPEC review followed by independent QUALITY/SECURITY review.

## Stop rule and verification boundary

Initial implementation plus at most one targeted correction per concrete acceptance rule. If the same rule still fails, record it and do not make a third repair. No Docker, Compose, Alembic upgrade/downgrade, full suite, coverage, Git mutation, or real PostgreSQL performance/load validation is authorized for this slice. Task 10 remains blocked/abandoned; Task 3A and Task 3B retain their independently documented P2 stop-rule limitations.