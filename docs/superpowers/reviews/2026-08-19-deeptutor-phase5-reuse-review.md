# DeepTutor → Phase 5 Reuse Review — 2026-08-19

## Decision

**Do not copy DeepTutor wholesale or overwrite `apps/api`.**

DeepTutor is an Apache-2.0 project and selective source reuse is legally possible when the distribution obligations are observed. Technically, however, its parse/RAG and agent systems depend on a different persistence and runtime model. Direct copy-paste would bypass or duplicate the current product's space isolation, immutable source/version graph, database-backed worker leases, pgvector chunks, and S3-compatible object-storage boundaries.

This review is read-only. It does not change product code, dependencies, or tests.

## Compatibility matrix

| DeepTutor area | Source paths | Current Phase 5 target | Reuse class | Reason / required work |
|---|---|---|---|---|
| Canonical parse-result IR | `deeptutor/services/parsing/types.py`, `base.py` | Import/parse pipeline | **Reference only** | Current `tutor_api.knowledge.parsers` already has `ParsedDocument`, page/block evidence, structured errors, and an object-storage/worker boundary. Names and data shape differ. Copying would create duplicate contracts without closing the Docker worker failure. |
| Parser signatures/cache | `services/parsing/signature.py`, `cache.py`, `service.py` | Reproducible parsing | **Reference only** | Current worker persists deterministic pipeline signatures in immutable SQL document/index versions; DeepTutor caches on local paths and artifacts. A local cache cannot replace tenant-scoped object records or database state. |
| Docling/MinerU/MarkItDown engines | `services/parsing/engines/**` | PDF/DOCX/image parsing and OCR | **Not reusable as pasted code** | The engines rely on local source paths/work directories and optional heavyweight model/CLI installation. Current product deliberately uses bounded in-process parsers, PDFium/Tesseract adapters, MinIO, and DB worker jobs. Each engine would require an adapter, explicit dependency approval, resource limits, cleanup, and security review. |
| Embedding/index identity | `services/rag/index_versioning.py`, `embedding_signature.py` | Immutable index versions | **Reference only** | Both products value signatures/versioning, but DeepTutor stores `data/knowledge_bases/<kb>/version-*`; current product stores SQL `IndexVersion`/`Chunk` rows keyed to immutable `DocumentVersion` plus pgvector. Do not introduce a parallel directory index. |
| LlamaIndex / LightRAG / GraphRAG / PageIndex pipelines | `services/rag/pipelines/**` | Retrieval and graph capability | **Not directly reusable** | They bring incompatible external runtimes and separate storage/LLM contracts. Current retrieval is already a bounded SQL/pgvector implementation. Graph capability needs a dedicated data model and approval workflow, not a second KB engine. |
| Smart retriever | `services/rag/smart_retriever.py` | Hybrid retrieval | **Reference only** | Current `knowledge/retrieval.py` already has its own citation, active-index, range-preview, and authorization assumptions. Replacing it would risk losing citation/source-preview invariants. |
| Notebook records | `services/notebook/service.py` | Self-growing notes | **Adapt design, not code** | DeepTutor uses local JSON files below `data/user/workspace/notebook`; current product must use SQL models scoped by `space_id`, author, visibility, review state, provenance and citations. Its `RecordType` vocabulary and field ideas are useful. |
| Question / wrong-answer history | `agents/question/**`, `tools/question/**` | Question bank and wrong-question set | **Adapt concepts/prompts after model design** | DeepTutor's history reads its own SQLite session store and its pipeline invokes its own LLM/tools/stream contracts. It cannot be exposed by current FastAPI without fresh tables, permissions, immutable prompts/versioning and provider billing integration. |
| L0–L3 memory | `services/memory/**` | Long-term learner memory | **Adapt algorithms, not storage** | DeepTutor L0–L3 content is Markdown/JSON under a local `data/user` hierarchy. Current product needs explicit SQL records, per-user/space access, source/citation links, retention/deletion, review and audit controls. Pure helpers such as IDs/operation validation may be candidates only after a precise interface comparison. |
| Chat orchestrator / tools / capabilities | `runtime/orchestrator.py`, `runtime/registry/**`, `tools/**` | Unified Agent Loop | **Architecture reference only** | DeepTutor uses `UnifiedContext`, StreamBus, global registries, CLI/WebSocket/SDK runtime and provider factory. Current API has HTTP routers, provider/wallet models and a separate database worker; a direct paste would neither register endpoints nor enforce existing auth/billing. |

## Current project constraints that direct copying must not bypass

- API models already enforce `space_id`, owner/creator IDs, document versioning, active index versions and database worker lease/job state: `apps/api/src/tutor_api/knowledge/models.py`.
- Upload, idempotency, file-name validation, immutable objects and access checks are in `knowledge/service.py`, `knowledge/router.py`, `knowledge/access.py` and `knowledge/storage.py`.
- Parsing and index work execute through a database-leased worker in `knowledge/worker.py` and `worker_main.py`, not DeepTutor's local user-data workspaces.
- Phase 5 Task 10's real Docker ingestion/index/search defect remains blocked. Copying parser/RAG code would not diagnose that failed `IndexVersion` path and would add a second implementation while the first is unresolved.

## License and attribution requirements before any source-level reuse

DeepTutor's root `LICENSE` is Apache License 2.0. Its section 4 requires redistribution of the license, prominent notices for modified copied files, and retention of relevant copyright/patent/trademark/attribution notices. The repository also has `THIRD_PARTY_NOTICES.md`, including CSSwitch's MIT notice for the listed OAuth concepts.

Before copying any source or substantial prompt text:

1. Record exact source path and upstream revision/archive provenance in a project notice file.
2. Preserve the Apache-2.0 header/license and any file-level copyright/third-party notice relevant to the copied portion.
3. Add a prominent local modification notice to altered copied files.
4. Check that the candidate does not itself originate from a separately licensed dependency or include vendor code.
5. Add the minimum required dependency only after lockfile, container, security, resource-limit and license review.

## Recommended implementation direction

1. **Do not resume Task 10 by copying DeepTutor.** Its real Compose failure remains a separate, paused diagnostic item.
2. Start the next Phase 5 business slice with a current-native schema/API plan for learner notes, question attempts and wrong-question collection. Treat DeepTutor's `NotebookRecord`, question-history ordering rules and memory consolidation behavior as product references.
3. Implement the slice in the current architecture (Alembic + SQLAlchemy + FastAPI + focused tests), with source/citation provenance and space/user authorization from day one.
4. Only after the schema boundary is approved, selectively port a small pure Apache-2.0 helper if that removes genuine implementation work. Do not port path-based storage, registries, provider factories or entire pipelines.

## Independent review status

Two requested independent read-only review agents were launched for parse/RAG and memory/agent modules, respectively, but both ended without a report because the subagent service returned `429 Too Many Requests`. The main review above is based on direct local source inspection. A fresh independent review should be obtained before source-level copying begins.
