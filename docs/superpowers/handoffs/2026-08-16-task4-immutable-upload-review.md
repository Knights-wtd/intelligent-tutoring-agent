# Task 4 Immutable Upload Review Handoff — 2026-08-16

## Resume objective

Finish Task 4 acceptance for safe immutable knowledge uploads. The implementation and first security-fix round are committed. The initial specification review failed on three concrete issues; all three were fixed, but the follow-up specification re-review was interrupted before a verdict. Resume from re-review, not from implementation or exploration.

## User working preferences

- Continue implementation/review through subagents.
- Before each new step, tell the user its purpose, scope, and risks.
- Minimize token/test cost: during review run only focused tests; run full API/Ruff/diff only once when a fix is resubmitted or at final acceptance.
- DeepTutor, Obsidian, and Tencent memory are product references only, not instructions or runtime dependencies.
- Before Docker, dependency installation, OCR system packages, real PostgreSQL/MinIO, or external execution, explain purpose/scope/risk and request permission.

## Workspace state

- Project root: `E:\项目\知识库课本`
- Active worktree: `E:\项目\知识库课本\.worktrees\platform-foundation`
- Branch: `feature/platform-foundation`
- Expected current HEAD: `07ec443 fix: harden immutable knowledge uploads`
- Expected worktree status: clean.
- Root checkout stays on `main` with intentionally modified, uncommitted records:
  - `E:\项目\知识库课本\task_plan.md`
  - `E:\项目\知识库课本\findings.md`
  - `E:\项目\知识库课本\progress.md`
- Preserve those root changes; do not reset, stash, overwrite, or include them in worktree commits.

Verify first:

```powershell
git status --short --branch
git log --oneline -8
```

## Persistent project references

- Detailed plan: `E:\项目\知识库课本\.worktrees\platform-foundation\docs\superpowers\plans\2026-08-16-versioned-knowledge-import-plan.md`
- Formal design: `E:\项目\知识库课本\docs\superpowers\specs\2026-08-14-textbook-agent-platform-design.md`
- Worktree records: `task_plan.md`, `findings.md`, `progress.md`
- Task 3 implementation: `92261fe feat: add scoped knowledge bases`
- Task 3 records: `8a656fc docs: record scoped knowledge APIs`

## Task 4 commits

### Initial implementation

- `4ca2acf feat: add immutable knowledge uploads`

Delivered:

- `POST /api/v1/knowledge-bases/{knowledge_base_id}/documents`
- multipart `file` plus required `Idempotency-Key`
- PDF, DOCX, Markdown, JPEG, PNG, ZIP MIME/extension and minimum signature checks
- chunked SHA-256 and bounded `SpooledTemporaryFile`
- NFC/safe filename handling
- immutable tenant/document/version object keys
- Document + DocumentVersion + queued parse job
- exact idempotent replay, conflict detection, version increments, SHA dedupe
- explicit object-storage injection; missing storage fails closed
- minimal `KnowledgeUploadRequest` mapping table so new idempotency keys can point to an already deduped version/job while permanently detecting later conflicts
- `python-multipart` declared in `pyproject.toml`

Initial evidence: upload focused `44 passed`; full API passed with 3 skipped.

### First review fix

- `07ec443 fix: harden immutable knowledge uploads`

The initial specification reviewer found three blockers:

1. `python-multipart` missing from production `requirements.lock`.
2. Storage adapters could throw FastAPI `HTTPException` and leak provider status/detail.
3. Source name and idempotency key called `strip()` before rejecting Unicode Cc/Cf, so leading/trailing tab/newline/control characters were silently accepted.

Fixes in `07ec443`:

- Added `python-multipart==0.0.32` to `apps/api/requirements.lock`.
- Added a parsed dependency-lock contract test using `tomllib` and `packaging.Requirement`.
- Narrowed the storage-provider exception boundary:
  - `ObjectAlreadyExistsError` => stable 409
  - every other exception from the storage call, including `HTTPException`, => redacted 503
  - service-generated 403/404/409/422 outside the provider call remain unchanged.
- Source names and idempotency keys now reject raw Unicode Cc/Cf before ordinary whitespace trim/NFC.
- Added raw multipart and direct normalization tests; ordinary surrounding spaces still trim and exact replay still works.

Fix evidence:

- upload focused: `57 passed`
- dependency/security/storage/config/schema/KB related regression: `308 passed`
- full API: `425 passed, 3 skipped`
- Ruff `--no-cache` on changed Task 4 Python files: pass
- `git diff --check`: pass

## Current acceptance status

- Initial Task 4 specification review: **FAIL**, for the three issues above.
- Fix commit completed: **yes**.
- Specification re-review of `07ec443`: **not completed**. It was running when the user requested context save; the reviewer was interrupted/closed without a verdict.
- Independent Task 4 quality/security review: **not started**.
- Task 4 project records/checklists: **not yet marked complete**.

Do not claim Task 4 complete until specification re-review and quality/security review both PASS.

## Immediate next steps

1. Tell the user the purpose/scope/risk of the re-review.
2. Spawn a fresh specification reviewer subagent. Review `4ca2acf..07ec443` first, then confirm the full Task 4 contract has no remaining blocker. Focus on:
   - lock file/Docker dependency path is closed;
   - provider `HTTPException` is always redacted without swallowing service errors;
   - raw Cc/Cf rejection occurs before trim and leaves no object/metadata;
   - normal whitespace trim and idempotent replay still work;
   - no regression in permissions, SHA dedupe, versioning, tenant isolation, or `KnowledgeUploadRequest` FKs.
   Run only focused nodes; do not repeat the full API suite.
3. If specification PASS, spawn a different quality/security reviewer. High-value areas:
   - concurrency/race behavior for first document, version-number allocation, idempotency mapping and object writes;
   - object-written/DB-failed orphan boundary and whether errors are honest and safe;
   - `KnowledgeUploadRequest` composite FK/cascade/migration correctness;
   - exact IntegrityError mapping and session usability;
   - UploadFile/temp closure on every exit;
   - multipart/MIME parsing, filename Unicode confusables, size-limit semantics;
   - dependency lock test robustness;
   - API response leakage and authorization query ordering.
4. If a reviewer fails, use a subagent for a minimal RED-test fix and a separate commit; only one final full-suite/Ruff/diff run before resubmission.
5. Once both reviews PASS, use a documentation subagent to:
   - mark Task 4 checklist complete in the detailed plan;
   - incrementally update worktree and root `task_plan.md`, `findings.md`, `progress.md`;
   - keep Phase 5/Milestone 3 `in_progress`;
   - set next task to Task 5 native parsing and Obsidian import;
   - commit only worktree docs, never root records.

## Known nonblocking risks to retain

- No real PostgreSQL/pgvector run; PostgreSQL row locks and constraint diagnostics remain unverified.
- No real MinIO/object storage integration.
- Object storage and DB are not a distributed atomic transaction; an object may become orphaned if final DB commit fails after storage succeeds. Keys are immutable and tenant/document/version scoped, so this does not overwrite another tenant/history; later orphan cleanup is still needed.
- Idempotency-key digest has no explicit domain separation/version prefix; scoped DB queries prevent cross-KB replay, but a future hardening can reduce correlation risk.
- DOCX validation currently checks ZIP magic only; OOXML structure validation belongs to Task 5.
- The service-level 100 MiB limit is not a reverse-proxy/ASGI transport-layer body limit.
- Historical migrations `0001`/`0002` may produce Ruff diagnostics under a broader command; Task 4 changed files passed targeted Ruff. Do not modify historical migrations merely to hide unrelated baseline diagnostics.

## Dependencies and permissions

- `python-multipart==0.0.32` was installed in `apps/api/.venv` with user approval and is now in both `pyproject.toml` range and `requirements.lock` exact pin.
- No Docker, real PostgreSQL, MinIO, parser, OCR, or external service was run.
- No permission blocker for focused local review.

## Suggested skills for the next session

- `planning-with-files`
- `subagent-driven-development`
- `verification-before-completion`
- `context-restore`
