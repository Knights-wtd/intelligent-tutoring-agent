# Question Bank Foundation Plan

**Goal:** Add the smallest native, multi-tenant question-bank persistence foundation for Phase 5 without depending on the unapproved `tutor_api.learning` runtime, LLM/Agent integrations, or the blocked Task 10 ingestion path.

**Scope decision:** One immutable source anchor per question version; v1 creation only; server-owned answers; durable attempt recording only. Grading, `ErrorRecord`, mastery writes, review tasks, teacher analytics, question editing/v2, multi-anchor questions, and LLM generation are deliberately deferred.

**Defaults adopted:**

- Question authors use existing knowledge-base write permission (personal owner; class owner/teacher).
- Readable members may view public question data and submit only their own attempts.
- Attempt submission requires an idempotency key.
- A question version stores a real FK to its immutable `DocumentVersion`, but only a *snapshot* of derived chunk provenance. It must not have a foreign key to `chunks.id`, because indexing workers can remove/rebuild chunks.
- No public response exposes answer keys, keyword rubrics, request-key hashes, source hash/signature, or private answers.

**Protected files:** Do not modify the existing uncommitted Task 10 files (`knowledge/indexing.py`, `ocr.py`, `storage.py`, and related `test_knowledge_*` files) or `.env.example`. Do not use Docker, Compose, full tests, or coverage gates unless the user later requests them.

**Stop rule:** For each acceptance rule, implement once and allow at most one targeted correction. If it still fails after that correction, record the actual failure and move to the next item.

## Task 1 — Tenant-aware immutable schema

**Files:**

- Create `apps/api/src/tutor_api/question_bank/__init__.py`
- Create `apps/api/src/tutor_api/question_bank/models.py`
- Create `apps/api/migrations/versions/0009_question_bank_foundation.py`
- Modify `apps/api/migrations/env.py` only to import question-bank metadata
- Test `apps/api/tests/test_question_bank_schema.py`

- [ ] Write focused RED schema tests for:
  - question and version must remain in the knowledge base's space;
  - `(question_id, version_number)` uniqueness;
  - version anchor DocumentVersion must belong to the same knowledge base and space;
  - attempts use a tenant-aware version FK and `(user_id, question_version_id, request_key_hash)` idempotency uniqueness;
  - no FK from source chunk snapshot to `chunks`.
- [ ] Run only `tests/test_question_bank_schema.py` and confirm expected missing-module/import failure.
- [ ] Implement only ORM models/enums/constraints, and the standalone 0009 migration from `0008_embedding_contract`.
- [ ] Run the focused schema tests, targeted Ruff, and `git diff --check`.
- [ ] Independent spec review, then quality/security review. Do not start Task 2 until both pass or a stop-rule result is documented.

## Task 2 — Safe author/read/attempt APIs

**Files:**

- Create `apps/api/src/tutor_api/question_bank/schemas.py`
- Create `apps/api/src/tutor_api/question_bank/service.py`
- Create `apps/api/src/tutor_api/question_bank/router.py`
- Modify `apps/api/src/tutor_api/main.py` only to include the new router
- Test `apps/api/tests/test_question_bank.py`

- [ ] Use existing `get_writable_knowledge_base()` / `get_readable_knowledge_base()` permissions.
- [ ] Resolve and validate a signed citation server-side, then persist the provenance snapshot.
- [ ] Create v1 question versions only; use explicit public response models that omit answer/rubric/private provenance fields.
- [ ] Record own attempts idempotently; do not score or create ErrorRecord.
- [ ] Run only question-bank tests, targeted Ruff, and diff check; then independent spec and quality/security review.

## Task 3 — Deferred server-side grading transaction

**Not started in this plan.** It requires a separately quality-approved learning-domain contract. It may later call deterministic grading server-side and append immutable error records, mastery evidence, and review tasks in one transactional service flow.

## Acceptance boundaries

- The task does not make Task 10 pass and cannot be described as completing Phase 5.
- The task does not expose or accept client-authored error classifications.
- The task does not introduce a second permissions system or a direct chunk FK.
- New tests are isolated; pre-existing protected Task 10 tests remain unchanged.