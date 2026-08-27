# Question Bank Assessment Task 3B Review

**Date:** 2026-08-20  
**Scope:** assessment persistence schema only:

- `apps/api/src/tutor_api/question_bank/models.py`
- `apps/api/migrations/versions/0010_question_attempt_assessment.py`
- `apps/api/tests/test_question_bank_schema.py`

## Verification

- Controller focused schema verification: `35 passed`.
- Targeted Ruff: passed.
- Targeted diff check: passed.
- The only test warning is the pre-existing Alembic `path_separator` configuration deprecation warning. No actual Alembic migration, Docker, Compose, coverage gate, full suite, or Git mutation was run.

## Review sequence

### Specification review

**PASS.** The additive `0010` migration and ORM agree on a tenant/user/version/attempt composite identity. The `question_attempts` composite uniqueness is referenced by the assessment composite foreign key, and `question_attempt_id` is unique. Checks cover assessment score, mastery, evidence window, streaks, error type, review policy, and contract labels. The ledger does not currently store answer, rubric, keyword, request-hash, or provenance snapshot data.

### Quality/security review and one targeted correction

The first quality/security review identified P2: the test-only privacy/minimal-storage guard used an incomplete denylist. A one-time targeted correction changed it to an exact 20-column ORM allowlist, so unapproved ORM metadata columns—including source snapshot fields—now fail the focused schema test.

### Quality/security re-review

**FAIL — residual P2.** The exact allowlist reads SQLAlchemy ORM metadata, but the offline migration test does not perform an equivalent exact column-set assertion against the physical table created by `0010`. A future migration-only extra sensitive column could therefore evade the ORM allowlist while appearing in the deployed database. The current migration matches the current ORM and contains none of the prohibited fields.

## Final Task 3B disposition

- **SPEC:** PASS.
- **Focused functional checks:** PASS.
- **QUALITY/SECURITY:** FAIL (P2 migration-to-physical-schema privacy regression gate remains incomplete).
- **Current data exposure:** none found in the implemented schema.
- **Stop rule:** the same P2 privacy/minimal-storage acceptance rule has already received its one permitted targeted correction. Do **not** attempt a third Task 3B fix.

A future separately approved hardening task can add an independent migration-output column-set gate. This Task 3B review neither waives nor misreports the limitation.

## Boundaries

No Task 10 protected file, `tutor_api.learning`, or existing learning test was changed. Trigger-level append-only enforcement remains intentionally deferred; this schema only supplies immutable-by-API policy plus DB identity/uniqueness/check constraints.
