# Phase 5 / Task 10 Context Handoff — 2026-08-19

## Resume objective

Continue Phase 5 from the documented blocked state. Do not restart from project exploration or repeat the completed float32 review chain. The immediate unresolved issue is the real Docker ingestion/indexing path: uploaded Markdown/PDF documents create failed index versions and remain unsearchable.

## Current phase status

- Phase 5: **in_progress**, not complete.
- Task 10: **blocked/abandoned at the user's stop line**.
- Phase 5 has four broad deliverables in the root plan:
  1. PDF/DOCX/Markdown/image/Obsidian import — substantial foundation exists, real Docker indexing acceptance is not closed.
  2. Parsing/OCR/embedding/retrieval/citation/page preview — local/unit paths exist, real PostgreSQL/pgvector vertical path is not closed.
  3. Self-growing notes, knowledge graph, wrong-question set and question bank — not formally implemented.
  4. Unified Agent Loop, full/step-by-step guidance and L0-L3 memory — not formally implemented.
- Phase 6 is separate and must not be treated as part of the remaining Phase 5 estimate.

## What was verified

- Migration downgrade/upgrade round trip `0005_reversal_audit_group -> head -> 0005 -> head` passed.
- Alembic current during the final Docker attempt: `0008_embedding_contract (head)`.
- External provider keys are **not required** for the current local deterministic path. Compose uses `PROVIDER_PROFILES_JSON=[]`; embedding is local deterministic hash; no real LLM/OCR/embedding provider key was configured.
- The original production defect was real PostgreSQL/pgvector `VECTOR` float4 round-trip precision conflicting with exact Python list comparison.
- Final minimal code behavior in `apps/api/src/tutor_api/knowledge/indexing.py` accepts either:
  - `persisted == expected` for SQLite test storage;
  - `persisted == float32(expected)` for PostgreSQL/pgvector storage;
  and does not use broad `math.isclose`.
- The cross-binade regression uses real float32 values and rejects the two-step candidate:
  - expected `1.9999998807907104` (`0x3fffffff`)
  - persisted `2.000000238418579` (`0x40000001`)
- Focused indexing test file: `35 passed`.
- Targeted Ruff: passed.
- Targeted `git diff --check`: passed.
- Independent SPEC review: PASS.
- Quality/security review found no reachable production bypass, but noted that SQLite unit tests are not a substitute for real pgvector integration evidence.

## Final Docker evidence

- API/worker images were rebuilt from the current feature worktree and became healthy.
- The existing vertical script was run once after rebuild.
- Result: failure after 150 seconds with `status=200, results=0` for the Markdown search; PDF search was never reached.
- Recent database `index_versions` for the new acceptance knowledge base were `state=failed`.
- Worker logs were empty at the queried tail; API logs only showed repeated successful search HTTP 200 responses.
- The disposable Compose project and volumes were then destroyed; the temporary `.env` and `task10_vertical_slice.py` were deleted.
- Do not claim real ingestion, pgvector indexing, retrieval, or citation page acceptance passed.

## Workspace state to preserve

Root intentionally modified planning records (do not reset, stash, stage, commit, overwrite or discard):

- `E:\项目\知识库课本\task_plan.md`
- `E:\项目\知识库课本\findings.md`
- `E:\项目\知识库课本\progress.md`

Feature worktree: `E:\项目\知识库课本\.worktrees\platform-foundation`

Branch: `feature/platform-foundation`
HEAD at handoff: `5a242dc docs: prepare Task 10 environment handoff`

Existing uncommitted feature changes must all be preserved, including:

- `apps/api/src/tutor_api/knowledge/indexing.py`
- `apps/api/src/tutor_api/knowledge/ocr.py`
- `apps/api/src/tutor_api/knowledge/storage.py`
- `apps/api/tests/test_knowledge_adapters.py`
- `apps/api/tests/test_knowledge_indexing.py`
- `apps/api/tests/test_knowledge_ocr.py`
- `apps/api/tests/test_knowledge_retrieval.py`
- `apps/api/tests/test_knowledge_worker.py`
- deleted `.env.example` as currently present in the worktree

No reset, stash, stage, commit, or broad test suite was performed for this handoff.

## Next-window execution order

1. Restore context by reading this handoff plus root `task_plan.md`, `findings.md`, and `progress.md`; inspect `git status` before touching anything.
2. Do not re-open the already settled float32 debate. Treat the current helper/tests as the final repair attempt unless new evidence directly disproves them.
3. Decide whether to continue Task 10 with one narrowly scoped diagnostic implementation/review cycle or leave it blocked. If continuing, first inspect the worker/index failure path and add no speculative changes.
4. If a new Docker run is authorized, use a fresh isolated Compose project and a fresh random user/knowledge base. Do not reuse stale failed records. Capture redacted failure evidence before any cleanup.
5. If the real vertical slice still fails, stop rather than repeatedly tuning tolerance; document the exact failure layer and proceed only if the user explicitly chooses to treat the Docker path as a deferred product limitation.
6. Only after the knowledge-base foundation decision, plan the not-yet-built Phase 5 modules: self-growing notes/graph/question bank, then Agent Loop and L0-L3 memory. These are larger feature tasks and should be handled in a new context with a fresh plan.
7. Do not mark Phase 5 complete unless all four top-level deliverables are actually implemented and the critical import/index/retrieval/citation path is accepted.

## User decision already recorded

The user accepts the remaining `89.41%` API coverage exception and does not want low-value effort spent chasing the final `0.59` percentage points. This exception does not waive the failed Docker vertical slice.
