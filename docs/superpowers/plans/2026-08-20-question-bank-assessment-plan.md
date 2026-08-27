# Question Bank Assessment Transaction Plan

**Goal:** Extend Question Bank v1 with a small, native, deterministic assessment ledger. A successful first attempt must atomically persist its answer and one immutable assessment evidence record. This plan does **not** import or depend on `tutor_api.learning`, LLMs, Agent features, or the blocked Task 10 ingestion path.

## Approved v1 decisions

1. **Scoring is deterministic and server-side only.** It must never trust a client-provided score, correctness, error type, mastery value, review date, or rubric.
2. **Answer normalization:** Unicode NFC, trim, collapse whitespace, and casefold. No fuzzy matching and no LLM.
3. **Question scoring:**
   - `choice` and `short`: normalized exact match against server-only `expected_answer`.
   - `open` with keywords: normalized phrase-presence match per distinct server-only keyword; score is integer matched-ratio basis points; correct only when all keywords match.
   - `open` without keywords: normalized exact match against server-only `expected_answer`.
   - empty normalized answer: score zero and `metacognitive`; any other incorrect result is `application`.
4. **Evidence scope is per user + question version only.** There is no course-level mastery claim, objective mapping, teacher analytics, or multi-question knowledge graph.
5. **Mastery snapshot:** evaluate at most the five most recent already-assessed attempts for the same user and question version, then append the current score. Store the resulting integer `0..10000` snapshot and evidence count. The formula and contract versions are frozen in the assessment record.
6. **Review evidence:** store a deterministic next due time in UTC and a positive interval. v1 policy: score `10000` -> 7 days; score `5000..9999` -> 3 days; score `<5000` -> 1 day. `needs_review` is true unless the score is `10000`.
7. **No historical backfill is silently performed.** This work is not yet released. If a future deployed database contains an attempt without an assessment, that rollout must use a separately reviewed migration/backfill policy rather than changing a retry into an implicit rewrite.
8. **Immutability strength:** v1 has no API update/delete path and uses unique/FK/check constraints. Database-trigger-level append-only enforcement is deliberately deferred as a separately scoped hardening task.

## Protected boundaries

- Do not modify `.env.example`, Task 10 knowledge files/tests, `tutor_api.learning`, or `test_learning_*`.
- Do not run Docker, Compose, Alembic upgrades/downgrades, the full test suite, coverage gates, `git add`, commit, reset, stash, or checkout.
- Do not expose expected answers, keywords, attempt answers, source snapshots, idempotency hashes, or other users' assessment data.
- Reuse the existing Question Bank router and the existing readable knowledge-base authorization. Do not create a second access system.

## Task 3A — Deterministic assessment contract (pure Python)

**Files:**

- Create `apps/api/src/tutor_api/question_bank/assessment.py`
- Create `apps/api/tests/test_question_bank_assessment.py`

- [ ] Write RED tests for normalization, choice/short exact match, open keyword partial/full match, open exact-answer fallback, empty-answer error classification, bounded history/mastery, and deterministic UTC review schedule.
- [ ] Implement immutable value objects/enums and pure functions only. No SQLAlchemy session, route, FastAPI, LLM, or `tutor_api.learning` imports.
- [ ] Run only this new focused test, targeted Ruff, and targeted diff check.
- [x] Independent SPEC review: PASS.
- [!] Independent QUALITY/SECURITY review: stopped with the documented residual P2 import-isolation regression-test gap after the one permitted targeted correction; see `docs/superpowers/reviews/2026-08-20-question-bank-assessment-task3a-review.md`. Do not attempt a third Task 3A fix.

## Task 3B — Immutable assessment schema

**Files:**

- Modify `apps/api/src/tutor_api/question_bank/models.py`
- Create `apps/api/migrations/versions/0010_question_attempt_assessment.py`
- Modify `apps/api/tests/test_question_bank_schema.py`

- [x] Added `question_attempt_assessments` with the v1 one-to-one evidence contract and the narrow composite uniqueness on `question_attempts` needed for its composite FK.
- [x] Added score/mastery/evidence/streak/review/version constraints in additive `0010`; migration was not executed.
- [x] Focused schema tests, Ruff, and diff check passed; independent SPEC PASS.
- [!] Independent QUALITY/SECURITY review stopped at residual P2: the exact ORM column allowlist has no matching migration-physical-column allowlist gate. Current schema has no prohibited fields. The P2 used its one permitted targeted correction; do not attempt a third Task 3B fix. Evidence: `docs/superpowers/reviews/2026-08-20-question-bank-assessment-task3b-review.md`.

## Task 3C — Atomic submit-and-assess API

**Files:**

- Modify `apps/api/src/tutor_api/question_bank/service.py`
- Modify `apps/api/src/tutor_api/question_bank/schemas.py`
- Modify `apps/api/src/tutor_api/question_bank/router.py`
- Modify `apps/api/tests/test_question_bank.py`

- [x] First submission atomically creates attempt + assessment; same-key retry returns the original safe persisted assessment without recalculation or answer replacement.
- [x] Private rubric is loaded only inside the service and the response is a safe DTO owned by the submitting user.
- [x] Covered tenant isolation, first/replay behavior, client assessment injection rejection, answer/rubric non-disclosure, partial/open scoring, rollback on assessment failure, and cross-KB/unknown-version hidden 404 with zero writes.
- [x] Focused Question Bank tests, targeted Ruff, diff check, independent SPEC review, and final QUALITY/SECURITY re-review passed. One P1 concurrency correction added PostgreSQL transaction-scoped per-user/per-question-version advisory serialization; no live PostgreSQL concurrency E2E was run. Evidence: `docs/superpowers/reviews/2026-08-20-question-bank-assessment-task3c-review.md`.

## Stop rule

For each concrete acceptance rule: initial implementation plus at most one targeted correction. If it still fails after that correction, record the evidence and move on. Security, authorization, data-isolation, private-answer leakage, and transaction-integrity problems are not waived merely to meet velocity targets.


