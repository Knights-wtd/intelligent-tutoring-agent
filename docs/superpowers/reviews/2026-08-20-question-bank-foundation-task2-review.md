# Question Bank Foundation — Task 2 Review

**Date:** 2026-08-20

## Scope

Implemented the minimal Question Bank v1 API only:

- `POST /api/v1/knowledge-bases/{knowledge_base_id}/questions`
- `GET /api/v1/knowledge-bases/{knowledge_base_id}/questions`
- `GET /api/v1/knowledge-bases/{knowledge_base_id}/questions/{question_id}`
- `POST /api/v1/knowledge-bases/{knowledge_base_id}/question-versions/{question_version_id}/attempts`

No grading, `ErrorRecord`, mastery, review-task, LLM/Agent, `tutor_api.learning` runtime, Docker, Alembic execution, full suite, coverage gate, staging, commit, reset, stash, or checkout was performed.

## Final status

```text
SPEC: PASS
QUALITY/SECURITY: PASS
```

## Delivered contract

- Uses existing writable/readable knowledge-base authorization only.
- Validates opaque signed citations server-side against the scoped chunk, active index, READY document version, and ACTIVE document.
- Creates a single Question + QuestionVersion v1 with server-owned identity/provenance fields.
- Exposes explicit public DTOs only; no answers, rubrics, private source snapshot, owner/creator IDs, request-key hash, or attempt answer/user ID is returned.
- Records own attempts with normalized SHA-256 idempotency keys. Replays return the original safe attempt response without changing the original answer.
- Bounds normalized expected keywords to 50 entries and 4,096 total characters. Public list/detail queries defer private answer/rubric/provenance ORM fields.

## Review and correction record

1. Initial independent specification review failed because an overlong malformed citation was rejected by request validation with 422, while the contract requires invalid citations to be hidden as 404. One targeted correction removed that citation-length rejection and added direct outsider-attempt coverage.
2. Post-fix independent specification review: PASS.
3. Initial independent quality/security review found one P1: expected keyword arrays had no aggregate bounds and public reads loaded private ORM columns. One targeted correction added aggregate bounds, public-query `load_only(...)`, and regression coverage.
4. Post-fix independent quality/security review: PASS with no P0/P1/P2 findings.

## Focused verification

From `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_question_bank_schema.py tests/test_question_bank.py -p no:cacheprovider -q
# 20 passed

.\.venv\Scripts\python.exe -m ruff check --cache-dir "$env:TEMP\question-bank-api-ruff-cache" src\tutor_api\question_bank tests\test_question_bank_schema.py tests\test_question_bank.py src\tutor_api\main.py
# All checks passed!

git -C E:\项目\知识库课本\.worktrees\platform-foundation diff --check -- apps/api/src/tutor_api/question_bank apps/api/src/tutor_api/main.py apps/api/tests/test_question_bank.py
# passed
```

Only the pre-existing FastAPI/Starlette TestClient deprecation warning was emitted.

## Remaining boundary

Task 3 (server-side grading transaction) has not started. Per the Question Bank plan it requires a separately quality-approved learning-domain contract; it must not simply import or depend on the existing stopped `tutor_api.learning` runtime slice.
