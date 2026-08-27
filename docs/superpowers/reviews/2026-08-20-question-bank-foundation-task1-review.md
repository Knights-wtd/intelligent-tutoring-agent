# Question Bank Foundation Task 1 Review Record — 2026-08-20

## Scope

Reviewed only the new tenant-aware Question Bank ORM/migration schema. The task intentionally excludes API routes, service logic, grading, ErrorRecord, LLM/Agent work, teacher analytics, Docker/Compose, migration execution, the full test suite, and coverage checks.

## Delivered files

- pps/api/src/tutor_api/question_bank/__init__.py
- pps/api/src/tutor_api/question_bank/models.py
- pps/api/migrations/versions/0009_question_bank_foundation.py
- pps/api/migrations/env.py (one explicit model import)
- pps/api/tests/test_question_bank_schema.py

## Contract evidence

- questions has a tenant-aware (knowledge_base_id, space_id) composite FK and a unique (id, knowledge_base_id, space_id) identity target.
- question_versions links to Question and immutable DocumentVersion through KB/space-aware composite FKs, with positive and per-question-unique version numbers.
- question_attempts links to QuestionVersion via id/KB/space and has unique (user_id, question_version_id, request_key_hash) idempotency.
- Version source provenance persists a scalar chunk snapshot (ID, ordinal, pointer, content hash, index signature) with **no** FK or ORM relationship to rebuildable chunks.
- Question type values are limited to choice, short, and open; source/request hashes require lower-case 64-hex values.
- ORM and migration use the same JSON-on-SQLite / JSONB-on-PostgreSQL type variant for expected keyword data.

## Verification

Initial RED test: ModuleNotFoundError: No module named 'tutor_api.question_bank'.

Final focused commands in pps/api:

`powershell
.\.venv\Scripts\python.exe -m pytest tests/test_question_bank_schema.py -p no:cacheprovider -q
.\.venv\Scripts\python.exe -m ruff check --no-cache migrations/versions/0009_question_bank_foundation.py src/tutor_api/question_bank tests/test_question_bank_schema.py
`

Result: **11 passed**; Ruff passed. Targeted diff checks found no whitespace errors. Existing worktree cache/line-ending notices were not changed or bypassed.

## Independent review outcome

1. Initial SPEC review found migration line-length violations. One formatting-only correction was applied; SPEC re-review: **PASS**.
2. Initial QUALITY/SECURITY review found one P1: the model used plain JSON while migration used PostgreSQL JSONB. One targeted correction aligned the model to the migration and added a dialect-resolution regression test.
3. QUALITY/SECURITY re-review: **PASS**, no P0/P1/P2 findings.

## Status

- **SPEC:** PASS
- **QUALITY/SECURITY:** PASS
- **Task 1:** complete
- **Task 10:** unchanged, blocked/abandoned
- **Phase 5:** still in progress

No files were staged, committed, reset, stashed, or discarded. Protected uncommitted Task 10 and Learning files were not modified.
