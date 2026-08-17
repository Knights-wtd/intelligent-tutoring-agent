# Versioned Knowledge Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver space-scoped knowledge bases, safe PDF/DOCX/Markdown/image/Obsidian imports, resumable parsing, immutable index versions, cited retrieval, and source preview.

**Architecture:** Add a bounded `tutor_api.knowledge` module with parser, OCR, embedding, and object-storage ports. Original files remain immutable in S3-compatible storage; metadata, pages, blocks, indexes, chunks, and job checkpoints live in PostgreSQL. Tests inject memory storage and deterministic adapters; Docker uses MinIO, Tesseract, and a database-backed worker.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PostgreSQL/pgvector, MinIO, pypdf, pypdfium2, Pillow/pytesseract, safe ZIP/XML parsing, Next.js/Vitest.

---

### Task 1: Runtime adapters and bounded configuration

**Files:** Modify `apps/api/pyproject.toml`, lock files, and `core/config.py`; create `knowledge/storage.py`, `knowledge/ocr.py`, `knowledge/embeddings.py`; test `tests/test_knowledge_adapters.py`.

- [x] Write failing tests for safe object keys, memory round-trip, redacted OCR errors, deterministic fixed-dimension embeddings, and bounded settings.
- [x] Run the focused test and confirm missing-module failures.
- [x] Implement protocols/adapters. Reject absolute paths, traversal, NUL, and backslashes; normalize Unicode and L2-normalize vectors.
- [x] Add upload/Vault limits plus OCR and embedding backend/model/dimension settings.
- [x] Run focused tests and Ruff; commit `feat: add knowledge runtime adapters`.

**Delivery record (2026-08-16):** Completed in commits `00b9551`, `8f267ba`, and `1bb2fb1`. Specification review PASS; final code-quality review PASS. Verification: 63 focused adapter tests passed, 77 config tests passed, full API 228 passed/3 skipped, Ruff passed, and `git diff --check` passed.
### Task 2: Versioned knowledge schema

**Files:** Create `knowledge/models.py` and migration `0006_versioned_knowledge.py`; modify `migrations/env.py`; test `tests/test_knowledge_schema.py` and `tests/test_schema.py`.

- [x] Test one active index per KB, source-version uniqueness, content hashes, signature/dimension consistency, and cascades.
- [x] Implement knowledge bases, documents, versions, pages, blocks, index versions, chunks, and ingestion jobs with UUIDs, `space_id`, owner/audit fields, state enums, hashes, source pointers, leases, retries, and checkpoints.
- [x] Enable pgvector on PostgreSQL while retaining a JSON fallback for SQLite tests; dimensions cannot silently mix in one index.
- [x] Run schema tests and Alembic upgrade/downgrade/upgrade; commit `feat: add versioned knowledge schema`.
- [x] Complete specification review with PASS.
- [x] Complete iterative code-quality hardening and obtain final quality-review PASS.
- [x] Re-run focused schema tests, Alembic tests, the complete API suite, Ruff without cache, PostgreSQL offline SQL checks, and `git diff --check`.

**Delivery record (2026-08-16):** Task 2 completed in initial commit `bac0e0d` and quality-hardening commits `8129e28`, `67780ed`, and `000240d`. Specification review PASS; code-quality review final PASS after iterative hardening. Final verification: knowledge schema 105 passed, schema/Alembic 33 passed, complete API 345 passed/3 skipped, Ruff passed, and `git diff --check` passed. PostgreSQL validation was limited to offline SQL for `CREATE EXTENSION vector` and `VECTOR`; real PostgreSQL/pgvector permissions, DBAPI round-trips, concurrency, and performance remain for integration acceptance.

### Task 3: Space-scoped knowledge APIs

**Files:** Create `knowledge/access.py`, `schemas.py`, `service.py`, `router.py`; modify `main.py`; test `tests/test_knowledge_bases.py`.

- [x] Test personal owner read/write; classroom member read; creator/teacher write; student write 403; non-member read 404.
- [x] Implement server-side membership checks only.
- [x] Add create/list/detail endpoints with trimmed, unique 1-120 character names.
- [x] Run tests; commit `feat: add scoped knowledge bases`.

### Task 4: Safe immutable uploads

**Files:** Modify knowledge service/router/schemas; test `tests/test_knowledge_uploads.py`.

- [x] Test MIME/extension pairs, size limits, SHA-256 dedupe, filename sanitization, idempotency, and tenant isolation.
- [x] Stream to a temporary object while hashing, verify format, then promote to an immutable space/document/version key.
- [x] Create immutable metadata and a queued job. Replayed idempotency returns the same version; identical bytes may reuse storage without overwriting history.
- [x] Run tests; commit `feat: add immutable knowledge uploads`.

### Task 5: Native parsing and Obsidian import

**Files:** Create `knowledge/parsers.py` plus deterministic fixtures/tests in `tests/test_knowledge_parsers.py`.

- [x] Generate tiny PDF, DOCX, Markdown, PNG, and Vault ZIP fixtures in test code.
- [x] Assert page numbers, ordered blocks, frontmatter/tags, tables, attachments, wikilinks, and ZIP traversal/bomb rejection.
- [x] Implement native-first parsing. Low-text/garbled PDF pages become `needs_ocr`; DOCX uses safe ZIP/XML; Markdown retains line ranges; Vault entries are normalized and cannot escape a temporary sandbox.
- [x] Run tests; commit `feat: parse supported knowledge formats`.

### Task 6: Selective OCR and page evidence

**Files:** Modify `knowledge/ocr.py`, `parsers.py`, and `apps/api/Dockerfile`; test `tests/test_knowledge_ocr.py`.

- [x] Test that OCR runs only for images/low-confidence PDF pages, preserves page numbers, bounds pixels/time/languages, and checkpoints partial failure without exposing provider details.
- [x] Implement Tesseract OCR and pypdfium2 page rendering only when needed.
- [x] Install English/Chinese Tesseract runtime packages in the container before returning to the non-root user.
- [x] Run fake-adapter tests and an optional local Tesseract smoke marker; commit `feat: add selective page OCR`.

**Delivery record (2026-08-17):** Task 6 final PASS. Delivery commits: `e2e2a6b feat: add selective page OCR`, `d9f244d fix: bound selective OCR resources`, and `5225691 fix: close OCR lifecycle gaps`. The initial complete specification review passed; the final independent incremental specification review passed with 11 focused tests, and the final independent quality/security review passed with 7 focused tests plus real BrokenPipe, Windows Job-handle, repeated-success, and repeated-timeout lifecycle probes. Final main-thread bounded verification: OCR 49 passed, adapter OCR 10 passed, parser 57 passed, targeted Ruff PASS, and `git diff --check d9f244d..5225691` PASS. Not run: the full API suite, real Tesseract/container smoke, Docker, PostgreSQL, MinIO, external services, a live POSIX process-group path, or a complex PDFium corpus.

### Task 7: Immutable indexing and reliable worker

**Files:** Create `knowledge/indexing.py`, `knowledge/worker.py`, `worker_main.py`; modify service and `compose.yaml`; test `test_knowledge_indexing.py` and `test_knowledge_worker.py`.

- [ ] Test heading-aware chunks, overlap bounds, hash reuse, signatures, failed rebuild preserving the active index, atomic activation, leased claims, stale recovery, retry bounds, and restart without duplicates.
- [ ] Persist source page/block pointers, lexical terms, embeddings, model/dimension, and hashes under a building index version.
- [ ] Validate and activate in one transaction; supersede the previous active version only after success.
- [ ] Claim jobs with database leases and PostgreSQL `FOR UPDATE SKIP LOCKED`; run the worker from the same Compose image.
- [ ] Run tests; commit `feat: build knowledge indexes reliably`.

### Task 8: Hybrid retrieval and secure source preview

**Files:** Create `knowledge/retrieval.py`; modify router/schemas/storage; test `test_knowledge_retrieval.py` and `test_knowledge_sources.py`.

- [ ] Test exact-term and vector recall, reciprocal-rank fusion, active-index-only behavior, tenant isolation, and correct page citations on a fixed corpus.
- [ ] Add `POST /api/v1/knowledge-bases/{id}/search` with bounded excerpts and citation identifiers.
- [ ] Add authenticated source/page endpoints with range support or short-lived S3 presigning; never expose object keys, credentials, or provider errors.
- [ ] Run tests; commit `feat: add cited knowledge retrieval`.

### Task 9: C3 knowledge panel

**Files:** Create `apps/web/src/lib/knowledge-api.ts`, `knowledge-panel.tsx`, and tests; modify workspace shell/CSS.

- [ ] Test space-scoped loading, create KB, upload progress, simple ready/failed states, search, and citation preview.
- [ ] Implement hierarchy `知识库 → 教材/练习 → 文件`; keep OCR, embedding, and worker internals hidden from learners.
- [ ] Keep tutor/model/balance/knowledge failures independent and retryable.
- [ ] Run Web tests, lint, and build; commit `feat: connect knowledge workspace`.

### Task 10: End-to-end verification and records

**Files:** Modify `.env.example`, `README.md`, `task_plan.md`, `findings.md`, and `progress.md`.

- [ ] Run API unit/coverage/Ruff and Web test/lint/build.
- [ ] Run migration round-trip against isolated PostgreSQL/pgvector.
- [ ] Start isolated Compose; register, create a KB, upload Markdown/PDF, wait for ready, search, and open a cited page.
- [ ] Record exact results and remaining provider-dependent limits. Describe DeepTutor ideas as research only; do not copy source without a separate Apache-2.0 attribution review.
- [ ] Mark Milestone 3 complete only when every supported format has a deterministic fixture and the Docker vertical slice passes.
- [ ] Commit `docs: record versioned knowledge delivery`.

## Self-review

- The plan covers design sections 6-7, recovery rules, isolation, source preview, supported formats, hybrid retrieval, and the C3 knowledge hierarchy.
- Agent tutoring, questions, wrong answers, long-term memory, and class publishing remain Milestones 4-5 and are intentionally not hidden inside this plan.
- No DeepTutor source code is scheduled for direct copying; only interface and lifecycle ideas are used.
- No TODO/TBD placeholders are present; each task names exact files, tests, commands, expected behavior, and a commit boundary.
