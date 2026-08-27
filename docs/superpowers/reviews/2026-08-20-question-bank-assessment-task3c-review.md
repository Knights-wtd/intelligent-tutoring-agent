# Question Bank Assessment Task 3C Review

**Date:** 2026-08-20  
**Scope:** atomic Question Bank attempt submission and immutable assessment persistence only:

- `apps/api/src/tutor_api/question_bank/service.py`
- `apps/api/src/tutor_api/question_bank/schemas.py`
- `apps/api/src/tutor_api/question_bank/router.py`
- `apps/api/tests/test_question_bank.py`

## Verification

- Controller focused verification: `15 passed`.
- Targeted Ruff: passed.
- Targeted diff check for the four Task 3C files: passed.
- The only observed warning is the pre-existing `StarletteDeprecationWarning` from the FastAPI/Starlette TestClient dependency.
- No Docker, Compose, Alembic upgrade/downgrade, full test suite, coverage gate, or Git mutation was run.

## Specification review

**PASS.** The endpoint atomically creates a private attempt and exactly one immutable assessment on first submission. Server-side rubric data is read only inside the service; the response is a safe owner-only DTO. Same-key replay returns the already persisted result without recalculating, changing the stored answer, or adding an assessment. Legacy attempts without an assessment return `409` rather than being silently backfilled. Readable outsider and unknown-version paths remain hidden `404` paths with zero writes. Client-supplied assessment, mastery, review, or error fields are rejected.

## Quality/security review and targeted P1 correction

The initial quality/security review found P1: concurrent submissions using different idempotency keys for the same user and question version could each derive mastery and streak from the same stale evidence window.

The one permitted targeted correction adds a PostgreSQL transaction-scoped advisory lock keyed deterministically by `(user_id, question_version_id)`. The lock is acquired after the existing readable-KB and hidden-version authorization checks, but before replay lookup, historical assessment reads, mastery/streak derivation, and writes. It is obtained through the request's existing SQLAlchemy `Session`, inside the outer `session_scope()` transaction, so `pg_advisory_xact_lock` remains held until the outer transaction commits or rolls back. SQLite explicitly skips PostgreSQL-only SQL.

Focused regression coverage verifies the deterministic scoped lock key, PostgreSQL lock-call ordering before replay/history reads, and SQLite compatibility. Same-key replay remains inside the serialized section and retains its no-recompute/no-write behavior.

## Quality/security re-review

**PASS.** No P0/P1/P2 findings remain in this Task 3C scope. The reviewer confirmed lock timing, scope, transaction lifetime, retry/savepoint compatibility, response privacy, hidden authorization failures, rollback atomicity, and input rejection.

## Verification boundary

A real PostgreSQL concurrent end-to-end test was not run because Docker/Compose and live PostgreSQL verification were outside the granted scope. The PostgreSQL concurrency conclusion is therefore supported by source review plus dialect-mocked ordering tests, not a production-database load test.

## Final Task 3C disposition

- **Functional / focused verification:** PASS.
- **SPEC:** PASS.
- **QUALITY/SECURITY:** PASS after its one targeted P1 correction.
- **Scope boundary:** this does not alter the separately documented Task 3A and Task 3B P2 stop-rule outcomes, and it does not make blocked Task 10 pass.