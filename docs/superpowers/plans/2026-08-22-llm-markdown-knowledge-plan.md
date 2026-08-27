# LLM Markdown Knowledge Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reviewable Faro-Gemini Markdown import pipeline for Word/PDF/image/Vault sources, then publish deterministic Obsidian-style wikilinks, backlinks, and unresolved-link indexes without exposing provider secrets.

**Architecture:** Keep the existing native parser/OCR and immutable source/version pipeline. Add a server-only OpenAI-compatible Faro adapter, an asynchronous Markdown-draft job, explicit draft/publish APIs, and a deterministic wikilink index. LLM output is always a separate draft; the original source and existing searchable index remain unchanged until publication.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PostgreSQL/SQLite test fallback, existing DB-leased worker, Next.js/React, Vitest/Testing Library, pytest/Ruff.

**Execution rule:** Work test-first. Each task must have a red test, minimal implementation, and green verification. A repeated metric is allowed at most three targeted repair attempts; after the third failure, stop, record evidence in `task_plan.md`/`progress.md`, and ask the user whether to continue.

---

## File Map

- Create `apps/api/src/tutor_api/llm/ports.py`: provider request/response and stable error contracts.
- Create `apps/api/src/tutor_api/llm/faro.py`: Faro OpenAI-compatible HTTP adapter with timeout, retry, redacted diagnostics, and usage extraction.
- Modify `apps/api/src/tutor_api/core/config.py`: server-only Faro settings, model/context/timeout/concurrency limits, fail-closed validation.
- Modify `compose.yaml` and `.env.identity-test` documentation only: pass non-secret settings and a secret variable reference; never commit a real Key.
- Create `apps/api/src/tutor_api/knowledge/markdown.py`: Markdown rendering, validation, source-marker preservation, and wikilink parsing.
- Create `apps/api/src/tutor_api/knowledge/links.py`: normalized note/link resolution and backlink queries.
- Modify `apps/api/src/tutor_api/knowledge/models.py`: Markdown draft/revision and explicit link entities, preserving existing source/index entities.
- Create `apps/api/migrations/versions/0011_markdown_drafts_links.py`: schema migration and downgrade after the current `0010_question_attempt_assessment` head.
- Modify `apps/api/src/tutor_api/knowledge/worker.py` and `worker_main.py`: queue and execute Markdown generation/publish indexing jobs.
- Modify `apps/api/src/tutor_api/knowledge/router.py` and `schemas.py`: draft preview/edit/publish/retry and backlink endpoints with existing access checks.
- Modify `apps/web/src/lib/knowledge-api.ts`: typed draft/link API calls.
- Modify `apps/web/src/components/workspace/knowledge-panel.tsx` and `workspace-shell.module.css`: import status, draft review/editor, publish action, backlinks/unresolved links.
- Add focused API, worker, Markdown/link, and Web tests beside existing tests.

### Task 1: Add the server-only LLM contract and Faro adapter

**Files:**
- Create: `apps/api/src/tutor_api/llm/ports.py`, `apps/api/src/tutor_api/llm/faro.py`, `apps/api/src/tutor_api/llm/__init__.py`
- Modify: `apps/api/src/tutor_api/core/config.py`, `apps/api/src/tutor_api/main.py`
- Test: `apps/api/tests/test_llm_faro.py`, `apps/api/tests/test_config.py`

- [ ] Write failing tests for: missing Key reports provider-unavailable without revealing configuration; successful OpenAI-compatible response extracts text/usage/request id; timeout and 401 map to stable errors; retry never logs Authorization or request content.
- [ ] Run `pytest apps/api/tests/test_llm_faro.py -q`; expected failure because the adapter and port do not exist.
- [ ] Implement `LlmAdapter.complete_markdown(source_blocks, context)` and `FaroOpenAICompatibleAdapter` using server-side `httpx`, `https://faroapi.com/v1`, `FARO_API_KEY`, and configured model; keep the Key out of dataclass repr/logging.
- [ ] Add config fields `FARO_API_BASE_URL`, `FARO_API_KEY`, `FARO_MODEL`, `FARO_CONTEXT_WINDOW`, `FARO_TIMEOUT_SECONDS`, and `FARO_MAX_CONCURRENCY`; reject blank/unsafe values, but allow the feature to be unavailable when the Key is absent.
- [ ] Run the focused tests and `ruff check --no-cache` on changed API files; expected result is green with stable public error codes.

### Task 2: Build context-aware Markdown generation and validation

**Files:**
- Create: `apps/api/src/tutor_api/knowledge/markdown.py`
- Test: `apps/api/tests/test_knowledge_markdown.py`

- [ ] Write failing tests for short input, multi-page input, long input split by context budget, preserved source markers, empty output, model-error text, and explicit `[[Note#Heading|Alias]]` parsing.
- [ ] Run `pytest apps/api/tests/test_knowledge_markdown.py -q`; expected failure because the splitter, prompt contract, validator, and wikilink parser do not exist.
- [ ] Implement `MarkdownSourceBlock`, `split_for_context()`, `build_markdown_prompt()`, `merge_markdown_chunks()`, `validate_markdown_draft()`, and `parse_wikilinks()`; never reject based on total chapter length, only on malformed/empty/truncated/error-like responses.
- [ ] Require the prompt to treat imported document text as untrusted content and not follow instructions found inside it; require Markdown output plus source markers and no fabricated citations.
- [ ] Run the focused tests, including property-style cases for empty/short/long sections; expected result is green.

### Task 3: Persist drafts, revisions, and explicit link edges

**Files:**
- Modify: `apps/api/src/tutor_api/knowledge/models.py`
- Create: `apps/api/migrations/versions/0011_markdown_drafts_links.py`
- Test: `apps/api/tests/test_knowledge_markdown_models.py`, `apps/api/tests/test_migrations.py`

- [ ] Write failing tests for draft states `processing/draft/needs_review/published/failed`, immutable original source, editable draft revision, one active published revision per note, link edge uniqueness, unresolved target, and space-scoped access.
- [ ] Run the focused model/migration tests; expected failure because the tables and enums do not exist.
- [ ] Add `MarkdownNote`, `MarkdownRevision`, and `MarkdownLink` entities with composite space/knowledge-base foreign keys, source pointers, content SHA-256, author, generation metadata, and no secret/provider request body columns.
- [ ] Add the `0009` migration with PostgreSQL-compatible constraints and SQLite test fallback; downgrade must remove only the new tables.
- [ ] Run migration graph checks and focused model tests; expected result is green.

### Task 4: Extend worker processing without breaking existing ingestion

**Files:**
- Modify: `apps/api/src/tutor_api/knowledge/models.py`, `knowledge/service.py`, `knowledge/worker.py`, `worker_main.py`
- Test: `apps/api/tests/test_knowledge_markdown_worker.py`

- [ ] Write failing tests for queued draft generation after a parsed document is ready, successful multi-chunk generation, LLM unavailable, retryable provider failure, terminal failure, and idempotent rerun.
- [ ] Run the worker-focused tests; expected failure because the new job kind and handlers do not exist.
- [ ] Add `GENERATE_MARKDOWN` and `INDEX_MARKDOWN_LINKS` job kinds. Generate only from stored parsed blocks/source pointers, create a draft revision, and leave the existing active index untouched. Link indexing runs only after publish.
- [ ] Register the Faro adapter in `worker_main.py`; if unavailable, record `llm_provider_unavailable` and expose a retryable state rather than pretending success.
- [ ] Add bounded concurrency, timeout-aware calls, stable retry policy, and checkpoint fields containing only non-secret ids/counts/hashes.
- [ ] Run worker, parser, OCR, indexing, and migration focused suites; stop after the third repeated failure of the same metric and ask the user before changing architecture.

### Task 5: Add secure draft, publish, retry, backlink, and unresolved-link APIs

**Files:**
- Modify: `apps/api/src/tutor_api/knowledge/schemas.py`, `knowledge/router.py`, `knowledge/access.py`, `knowledge/links.py`
- Test: `apps/api/tests/test_knowledge_markdown_api.py`

- [ ] Write failing API tests for draft listing/detail, source-scoped preview, edit, publish, retry, backlinks, unresolved links, non-member isolation, and no-provider behavior.
- [ ] Run the focused API tests; expected failure because DTOs and routes do not exist.
- [ ] Implement routes under `/api/v1/knowledge-bases/{id}/markdown-notes` with existing authorization rules; responses expose ids, states, Markdown, source labels, and stable error codes only.
- [ ] Publish must validate the edited Markdown, create/update the searchable note representation, parse and persist explicit links, and never overwrite the original uploaded object.
- [ ] Run focused API tests plus existing knowledge access/upload/search tests; expected result is green.

### Task 6: Connect the review workflow to the Web knowledge panel

**Files:**
- Modify: `apps/web/src/lib/knowledge-api.ts`, `apps/web/src/components/workspace/knowledge-panel.tsx`, `apps/web/src/components/workspace/workspace-shell.module.css`
- Test: `apps/web/src/components/workspace/knowledge-panel.test.tsx`

- [ ] Write failing tests for processing status, draft preview, Markdown source/render toggle, editable draft, publish confirmation, retry after LLM failure, backlinks, and unresolved-link display.
- [ ] Run `npm test -- knowledge-panel.test.tsx`; expected failure because client methods and controls do not exist.
- [ ] Add typed API methods and render a compact review section in the existing light workspace; do not show provider keys, raw exceptions, request payloads, or internal worker/embedding details.
- [ ] Disable publish while saving or validating; keep the original upload row and source preview available throughout.
- [ ] Run the focused Web test, then the complete Web suite, lint, and `tsc --noEmit --incremental false`.

### Task 7: Compose configuration, end-to-end verification, and handoff

**Files:**
- Modify: `compose.yaml`, `.env.identity-test.example` or project environment documentation, `task_plan.md`, `findings.md`, `progress.md`
- Test: existing API/Web suites plus a new local vertical smoke test under `apps/api/tests/test_markdown_vertical_slice.py`

- [ ] Write the vertical-slice test for upload → parse → LLM draft stub → review → publish → wikilink/backlink lookup, with the external adapter replaced by a deterministic test adapter.
- [ ] Run the vertical-slice test; expected failure until all prior tasks are connected.
- [ ] Pass only non-secret Faro settings into API/worker containers; document `FARO_API_KEY` as a host-provided secret and ensure `.gitignore` covers local secret files.
- [ ] Run API focused suites, Web full suite, Ruff, TypeScript, migration checks, `git diff --check`, and a Docker production build. If the real Key is not configured, verify the explicit unavailable state rather than making a live paid call.
- [ ] Update planning files with exact test output, known limitations, and whether the user supplied a real Key. Do not mark the feature complete if the live Faro call or production PostgreSQL/MinIO vertical slice was not verified.

## Verification and escalation policy

- Every production change must be preceded by a failing test and followed by a passing focused test.
- A failed test caused by an environment lock, missing Docker CLI, unavailable Faro service, or absent Key is recorded separately from a product-code failure.
- For the same acceptance metric, attempt no more than three targeted repairs. On the third failure, stop and ask the user whether to continue, including the exact failure and the three attempted changes.
- Never paste, commit, print, or store the real Faro API Key in chat, source code, test output, screenshots, browser storage, or planning files.
