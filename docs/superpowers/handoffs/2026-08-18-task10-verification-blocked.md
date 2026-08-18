# Task 10 Handoff — Verification blocked before end-to-end acceptance

**Date:** 2026-08-18
**Worktree:** `E:\项目\知识库课本\.worktrees\platform-foundation`
**Branch:** `feature/platform-foundation`
**Status:** Task 10 is incomplete. Milestone 3 / Phase 5 remains `in_progress`.

## Scope honored

This pass made no product-code changes and did not touch the root worktree's intentionally uncommitted planning files. It only recorded Task 10 verification/configuration evidence in the feature worktree. No reset, stash, or root commit was used.

## Verification performed

| Check | Exact result |
|---|---|
| `pnpm test:web` | PASS — 7 files / 34 tests. Vite emitted its existing native-config deprecation warning. |
| `pnpm lint:web` | PASS. |
| `pnpm build:web` | PASS — optimized production compile, TypeScript, and static-page generation. A first sandboxed attempt failed only because it could not open `apps/web/.next/trace`; the allowed non-sandboxed rerun passed. |
| `python -m ruff check src tests` | Initial invocation could not create an existing, non-writable `.ruff_cache` temp file. `python -m ruff check --no-cache src tests` PASS. |
| `python -m pytest --cov=tutor_api --cov-report=term-missing --cov-fail-under=90` | Executed with `COVERAGE_FILE` redirected to `%TEMP%` and `-p no:cacheprovider`: **590 passed, 3 skipped, 2 failed**, total coverage **88.08%**, so the required 90% gate failed. |
| `python -m pytest tests/test_knowledge_ocr.py -p no:cacheprovider -vv` | PASS — 49 tests. This does not erase the full-suite coverage failure. |
| `python -m alembic -c alembic.ini heads` | PASS — `0008_embedding_contract (head)`. It only confirms the revision graph, not a database migration round-trip. |

The two API failures were `test_tesseract_timeout_kills_descendant_holding_pipes` and `test_tesseract_timeout_kills_descendant_inheriting_only_stdin`. Under the full coverage run, each expected Windows helper process failed to create its PID file within the test's one-second wait. No source change was made to hide or weaken these failures.

## Format coverage and effective limits

Accepted upload suffixes are `.pdf`, `.docx`, `.md`, `.jpg`, `.jpeg`, `.png`, and `.zip` (Obsidian Vault). The parser test suite deterministically constructs valid PDF, DOCX, Markdown, JPEG, PNG, and ZIP samples; upload tests explicitly parameterize all accepted suffixes, including both `.jpg` and `.jpeg`. There are no checked-in binary fixture files.

Effective application defaults are:

- knowledge upload: 100 MiB (`104857600` bytes);
- Vault members: 5,000;
- Vault uncompressed content: 500 MiB (`524288000` bytes);
- OCR: `disabled` only; `OCR_LANGUAGES` defaults to `eng,chi_sim`, and the runtime helper accepts only those identifiers;
- embeddings: deterministic `hash / feature-hash-v1 / 384`, with dimension validation from 8 through 4096.

No remote OCR, embedding, or real model provider is configured. `compose.yaml` currently relies on these defaults and does not forward arbitrary knowledge-override variables into both API and worker containers. DeepTutor remains research-only; no external source was copied.

## Environment gate / blocker

On 2026-08-18, `docker` was not on `PATH`; Docker Desktop and its common executable paths were absent. `psql`, `pg_isready`, and `initdb` were also unavailable. Therefore neither required live gate was attempted or fabricated:

1. isolated real PostgreSQL/pgvector migration upgrade/downgrade round-trip;
2. Compose vertical slice: register, create KB, upload deterministic Markdown and PDF, wait for readiness, search, and open cited page.

## Completion decision and next action

The deterministic format-test evidence exists, but the Docker vertical slice did not pass because no runtime exists. The API full coverage gate also fails at 88.08% with two observed Windows timing failures. **Do not mark Task 10, Milestone 3, or Phase 5 complete, and do not create `docs: record versioned knowledge delivery`.**

Next session needs a usable Docker Desktop/Compose runtime (or explicitly provisioned isolated PostgreSQL/pgvector), followed by the real migration and vertical-slice procedures. It also needs the two full-suite OCR failures and the configured 90% coverage gate resolved before a final delivery record can be committed.