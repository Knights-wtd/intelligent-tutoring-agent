# Knowledge Workspace Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make knowledge ingestion and candidate-review state recover from the database, present published notes and source documents in an explorer-style workspace, and provide an on-demand navigable graph without regressing authentication or the real Faro tutor path.

**Architecture:** Add a tenant-scoped workspace query service that composes documents, the highest-priority recent candidate batch, and published note summaries from existing tables, plus a lazy note-detail endpoint. The web client treats this snapshot as authoritative, renders explorer and review views as focused components, and lets the shell route graph-node selections back to a selected note. Existing upload, candidate confirmation, citation preview, graph, authentication, and tutor endpoints remain compatible.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2, pytest, React 19, Next.js 16, TypeScript, Vitest, Testing Library, CSS Modules, Docker Compose.

---

## File map

- Create `apps/api/src/tutor_api/knowledge/workspace.py`: tenant-scoped workspace snapshot and published-note detail queries.
- Modify `apps/api/src/tutor_api/knowledge/schemas.py`: document, note summary/detail, and workspace response contracts.
- Modify `apps/api/src/tutor_api/knowledge/router.py`: workspace and note-detail routes using existing access control.
- Create `apps/api/tests/test_knowledge_workspace.py`: API/service behavior, access control, state priority, and lazy detail tests.
- Modify `apps/web/src/lib/knowledge-api.ts`: matching TypeScript contracts and `workspace`/`note` requests.
- Modify `apps/web/src/lib/knowledge-api.test.ts`: request URL and response-contract tests.
- Create `apps/web/src/components/workspace/knowledge-explorer.tsx`: explorer tree and lazy document/note viewer.
- Create `apps/web/src/components/workspace/knowledge-explorer.test.tsx`: two-root tree, selection, and lazy-load behavior.
- Create `apps/web/src/components/workspace/knowledge-candidate-review.tsx`: focused candidate review UI extracted from the panel.
- Modify `apps/web/src/components/workspace/knowledge-panel.tsx`: authoritative snapshot restore, polling, upload/generation integration, and view selection.
- Modify `apps/web/src/components/workspace/knowledge-panel.test.tsx`: remount recovery and regression coverage.
- Modify `apps/web/src/components/workspace/knowledge-graph-panel.tsx`: explicit transform state, controls, wheel zoom, pan, and note navigation.
- Modify `apps/web/src/components/workspace/knowledge-graph-panel.test.tsx`: graph interaction tests.
- Modify `apps/web/src/components/workspace/workspace-shell.tsx`: pass graph-node navigation into the knowledge tab.
- Modify `apps/web/src/components/workspace/workspace-shell.test.tsx`: independent graph tab and node-to-note routing tests.
- Modify `apps/web/src/components/workspace/workspace-shell.module.css`: explorer, viewer, and graph interaction layout.
- Re-run existing auth, proxy, candidate-title, retrieval, tutor, compose, and Faro relay tests without weakening assertions.

### Task 1: Backend workspace snapshot query

**Files:**
- Create: `apps/api/src/tutor_api/knowledge/workspace.py`
- Modify: `apps/api/src/tutor_api/knowledge/schemas.py`
- Modify: `apps/api/src/tutor_api/knowledge/router.py`
- Test: `apps/api/tests/test_knowledge_workspace.py`

- [ ] **Step 1: Write failing workspace snapshot tests**

Create fixtures with two users, two knowledge bases, active/archived documents, multiple document versions, candidate batches in `confirmed`, `failed`, `needs_review`, and `processing`, plus published notes. Assert `GET /api/v1/knowledge-bases/{id}/workspace` returns only the requested tenant's active documents, uses the latest version per document, maps `UPLOADED/PARSING` to `processing`, `READY` to `searchable`, `FAILED` to `failed`, and chooses candidate state priority `processing > needs_review > failed > latest confirmed`. Assert an unrelated user receives 404.

The expected top-level contract is:

```python
{
    "knowledge_base_id": str(knowledge_base.id),
    "documents": [
        {
            "document_id": str(document.id),
            "document_version_id": str(version.id),
            "source_name": "wireless.docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "processing_state": "searchable",
            "created_at": version.created_at.isoformat(),
            "updated_at": version.updated_at.isoformat(),
        }
    ],
    "candidate_batch": {"id": str(processing_batch.id), "state": "processing", "notes": [], "links": []},
    "notes": [],
}
```

- [ ] **Step 2: Run the new API test and verify failure**

Run: `cd apps/api; uv run pytest tests/test_knowledge_workspace.py -q`

Expected: FAIL because the workspace route and response schemas do not exist.

- [ ] **Step 3: Add response schemas**

Add these schema shapes in `schemas.py`, reusing `KnowledgeCandidateBatchResponse` for the candidate field:

```python
class KnowledgeWorkspaceDocumentResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    source_name: str
    content_type: str
    processing_state: Literal["processing", "searchable", "failed"]
    created_at: datetime
    updated_at: datetime


class KnowledgeNoteSummaryResponse(BaseModel):
    id: UUID
    title: str
    kind: str
    parent_id: UUID | None
    source_document_id: UUID | None
    updated_at: datetime


class KnowledgeWorkspaceResponse(BaseModel):
    knowledge_base_id: UUID
    documents: list[KnowledgeWorkspaceDocumentResponse]
    candidate_batch: KnowledgeCandidateBatchResponse | None
    notes: list[KnowledgeNoteSummaryResponse]
```

- [ ] **Step 4: Implement the minimal tenant-scoped query service**

In `workspace.py`, define immutable query result dataclasses and:

```python
def load_knowledge_workspace(session: Session, user: User, knowledge_base_id: UUID) -> KnowledgeWorkspace:
    knowledge_base = get_writable_knowledge_base(session, user, knowledge_base_id)
    documents = _latest_active_documents(session, knowledge_base)
    candidate_batch = _attention_batch(session, knowledge_base)
    notes = _published_note_summaries(session, knowledge_base)
    return KnowledgeWorkspace(knowledge_base.id, documents, candidate_batch, notes)
```

Use correlated subqueries or grouped maximum `version_number` to return one latest version per active document. Derive note parents only from published structural links whose relation is `contains` or `所属结构`, choosing the first deterministic parent by source note title and link ordinal. Never query or return rows outside both `knowledge_base_id` and `space_id`.

- [ ] **Step 5: Add the route and serialize the selected batch with the existing helper**

Add:

```python
@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/workspace",
    response_model=KnowledgeWorkspaceResponse,
)
def get_knowledge_workspace(...):
    with session_scope(_session_factory(request)) as session:
        snapshot = load_knowledge_workspace(session, current_user, knowledge_base_id)
        return KnowledgeWorkspaceResponse(
            knowledge_base_id=snapshot.knowledge_base_id,
            documents=[KnowledgeWorkspaceDocumentResponse(**asdict(item)) for item in snapshot.documents],
            candidate_batch=(
                _candidate_batch_response(session, snapshot.candidate_batch)
                if snapshot.candidate_batch is not None
                else None
            ),
            notes=[KnowledgeNoteSummaryResponse(**asdict(item)) for item in snapshot.notes],
        )
```

Place the route after `_candidate_batch_response` so the serializer is defined before use.

- [ ] **Step 6: Run focused API tests**

Run: `cd apps/api; uv run pytest tests/test_knowledge_workspace.py tests/test_knowledge_graph.py tests/test_knowledge_candidate_service.py -q`

Expected: all tests PASS, including existing duplicate-title publication protection.

### Task 2: Lazy published-note detail endpoint

**Files:**
- Modify: `apps/api/src/tutor_api/knowledge/workspace.py`
- Modify: `apps/api/src/tutor_api/knowledge/schemas.py`
- Modify: `apps/api/src/tutor_api/knowledge/router.py`
- Modify: `apps/api/tests/test_knowledge_workspace.py`

- [ ] **Step 1: Write failing note-detail tests**

Seed one published note with a published revision, source markers, source document, a parent structural link, and a child structural link. Assert `GET /api/v1/knowledge-bases/{kb}/notes/{note}` returns title, kind, Markdown, source markers, source document ID/name, parent summary, child summaries, and updated time. Assert draft-only notes, notes in another knowledge base, and notes requested by another tenant return 404.

Expected response fields:

```python
{
    "id": str(note.id),
    "title": "路径损耗",
    "kind": "concept",
    "markdown": "# 路径损耗\n...",
    "source_markers": ["wireless.docx#block=150"],
    "source_document_id": str(document.id),
    "source_name": "wireless.docx",
    "parent": {"id": str(parent.id), "title": "移动无线传播"},
    "children": [{"id": str(child.id), "title": "自由空间模型"}],
    "updated_at": revision.updated_at.isoformat(),
}
```

- [ ] **Step 2: Run the note-detail test and verify failure**

Run: `cd apps/api; uv run pytest tests/test_knowledge_workspace.py -q -k note_detail`

Expected: FAIL with 404 because the route is absent.

- [ ] **Step 3: Add note-detail schemas and query**

Add `KnowledgeNoteReferenceResponse` and `KnowledgeNoteDetailResponse`. Implement:

```python
def load_published_note(
    session: Session, user: User, knowledge_base_id: UUID, note_id: UUID
) -> PublishedNoteDetail:
    knowledge_base = get_writable_knowledge_base(session, user, knowledge_base_id)
    # Join MarkdownNote to its PUBLISHED MarkdownRevision and optional source Document.
    # Raise HTTPException(404, "资源不存在") if no published row exists.
```

Resolve parent and children from published `MarkdownLink` rows and bound note IDs, not from candidate rows. Order children by title then ID for stable JSON.

- [ ] **Step 4: Add the lazy endpoint**

Add `GET /api/v1/knowledge-bases/{knowledge_base_id}/notes/{note_id}` with `response_model=KnowledgeNoteDetailResponse`, converting the dataclass result without returning ORM objects after the session closes.

- [ ] **Step 5: Run API workspace tests**

Run: `cd apps/api; uv run pytest tests/test_knowledge_workspace.py -q`

Expected: all tests PASS.

### Task 3: Web API contracts and authoritative restore

**Files:**
- Modify: `apps/web/src/lib/knowledge-api.ts`
- Modify: `apps/web/src/lib/knowledge-api.test.ts`
- Modify: `apps/web/src/components/workspace/knowledge-panel.tsx`
- Modify: `apps/web/src/components/workspace/knowledge-panel.test.tsx`

- [ ] **Step 1: Write failing client and remount tests**

Add client tests that expect:

```ts
knowledgeApi.workspace("kb-1", signal)
// GET /api/v1/knowledge-bases/kb-1/workspace
knowledgeApi.note("kb-1", "note-1", signal)
// GET /api/v1/knowledge-bases/kb-1/notes/note-1
```

Add component tests that unmount and remount `KnowledgePanel` while the mocked snapshot contains: (a) a processing document, (b) a processing candidate batch that later becomes `needs_review`, and (c) a failed batch. Assert the restored status is shown and polling resumes from the backend batch ID without localStorage.

- [ ] **Step 2: Run focused web tests and verify failure**

Run: `cd apps/web; pnpm test -- src/lib/knowledge-api.test.ts src/components/workspace/knowledge-panel.test.tsx`

Expected: FAIL because `workspace` and `note` do not exist and the panel does not restore state.

- [ ] **Step 3: Add TypeScript contracts and API methods**

Define `KnowledgeWorkspaceDocument`, `KnowledgeNoteSummary`, `KnowledgeWorkspace`, `KnowledgeNoteReference`, and `KnowledgeNoteDetail` matching the API. Add:

```ts
workspace(knowledgeBaseId: string, signal?: AbortSignal): Promise<KnowledgeWorkspace> {
  return requestJson(`/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/workspace`, { signal });
},
note(knowledgeBaseId: string, noteId: string, signal?: AbortSignal): Promise<KnowledgeNoteDetail> {
  return requestJson(`/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/notes/${resource(noteId)}`, { signal });
},
```

- [ ] **Step 4: Replace component-memory authority with snapshot hydration**

On every selected knowledge-base change, fetch one snapshot, populate document rows, candidate batch, accepted note/link IDs, and published-note summaries. Abort only the current request on unmount; do not clear the server-derived view first. For snapshot errors, preserve the frame and expose a `重新加载` action.

For `processing` documents, poll `documentStatus` and refresh the snapshot when a terminal state arrives. For `processing` candidate batches, poll the existing candidate detail endpoint and refresh the snapshot when the state changes. For `needs_review`, initialize accepted IDs from rows whose review state is not `rejected`. For `confirmed`, refresh snapshot and graph-visible note data. No business task ID is written to localStorage.

- [ ] **Step 5: Run focused restore tests**

Run: `cd apps/web; pnpm test -- src/lib/knowledge-api.test.ts src/components/workspace/knowledge-panel.test.tsx`

Expected: all focused tests PASS.

### Task 4: Explorer-style note and source browsing

**Files:**
- Create: `apps/web/src/components/workspace/knowledge-explorer.tsx`
- Create: `apps/web/src/components/workspace/knowledge-explorer.test.tsx`
- Create: `apps/web/src/components/workspace/knowledge-candidate-review.tsx`
- Modify: `apps/web/src/components/workspace/knowledge-panel.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`

- [ ] **Step 1: Write failing explorer tests**

Render summaries and documents and assert the tree always contains expanded roots `知识笔记` and `原始资料`; notes render with `.md`; document rows expose `处理中`, `可搜索`, or `失败`; clicking a note calls `knowledgeApi.note` only then and displays its Markdown, breadcrumb, source name, markers, and update time; clicking a DOCX displays metadata and the explicit searchable explanation rather than a fake page preview.

- [ ] **Step 2: Run explorer tests and verify failure**

Run: `cd apps/web; pnpm test -- src/components/workspace/knowledge-explorer.test.tsx`

Expected: FAIL because the explorer component does not exist.

- [ ] **Step 3: Implement focused explorer and candidate-review components**

`KnowledgeExplorer` receives `knowledgeBase`, `documents`, `notes`, optional `initialNoteId`, and `onReviewCandidates`. Build the hierarchy from `parent_id`, place orphan/cyclic notes at the root exactly once, and fetch detail only on selection. Render Markdown as readable pre-wrapped text without `dangerouslySetInnerHTML`. Document selection renders content type, processing state, timestamps, and a preview action only when an existing safe citation/preview URL is available; otherwise state that parsed content is available to search and Tutor.

Move the existing candidate note/link checkbox lists and confirm controls into `KnowledgeCandidateReview`, preserving duplicate-title display and all current acceptance semantics.

- [ ] **Step 4: Integrate toolbar and view switching**

The knowledge panel toolbar exposes `资料浏览`, `候选审核`, `上传资料`, `生成候选`, and `打开链路图`. Default to explorer; automatically surface the review badge for `needs_review` without forcing confirmation. Keep search results available as a separate compact section or viewer mode, not mixed beneath every note.

- [ ] **Step 5: Run knowledge UI tests**

Run: `cd apps/web; pnpm test -- src/components/workspace/knowledge-explorer.test.tsx src/components/workspace/knowledge-panel.test.tsx`

Expected: all tests PASS.

### Task 5: On-demand graph viewport and node navigation

**Files:**
- Modify: `apps/web/src/components/workspace/knowledge-graph-panel.tsx`
- Modify: `apps/web/src/components/workspace/knowledge-graph-panel.test.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.test.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`

- [ ] **Step 1: Write failing graph interaction tests**

Assert the graph is absent from the knowledge panel until `打开链路图` is clicked, then appears in the existing independent tab. In the graph panel assert buttons `放大`, `缩小`, `100%`, and `适应窗口`; current percentage; wheel-up increases scale; pointer drag changes translation; clamping remains between 40% and 240%; and clicking an SVG node or `打开知识笔记` invokes `onOpenNote(node.id)`.

- [ ] **Step 2: Run graph tests and verify failure**

Run: `cd apps/web; pnpm test -- src/components/workspace/knowledge-graph-panel.test.tsx src/components/workspace/workspace-shell.test.tsx`

Expected: FAIL because explicit zoom/pan and note routing are absent.

- [ ] **Step 3: Implement controlled graph transform state**

Replace the derived transform with `{ scale, x, y }`, constants `MIN_SCALE = 0.4`, `MAX_SCALE = 2.4`, and helpers that preserve the cursor anchor during wheel zoom. `100%` sets scale to `1` and centers the logical canvas; `适应窗口` uses the established fit transform; pointer capture drives panning; buttons use 20% increments. Apply one SVG `<g transform={`translate(${x} ${y}) scale(${scale})`}>` and show `Math.round(scale * 100)%`.

- [ ] **Step 4: Route graph node selection back to the explorer**

Add `onOpenNote?: (noteId: string) => void` to `KnowledgeGraphPanel`. The shell stores a pending knowledge-note ID, selects the graph's knowledge base, focuses the fixed knowledge tab, and passes the ID to `KnowledgePanel`, which forwards it to `KnowledgeExplorer` and clears it after selection is acknowledged.

- [ ] **Step 5: Run graph and shell tests**

Run: `cd apps/web; pnpm test -- src/components/workspace/knowledge-graph-panel.test.tsx src/components/workspace/workspace-shell.test.tsx src/components/workspace/knowledge-panel.test.tsx`

Expected: all tests PASS.

### Task 6: Authentication and real Faro product-path regression

**Files:**
- Verify/modify only if tests expose a regression: `apps/web/src/app/page.tsx`
- Verify/modify only if tests expose a regression: `apps/web/src/components/auth/auth-form.tsx`
- Verify/modify only if tests expose a regression: `apps/web/src/lib/api.ts`
- Verify/modify only if tests expose a regression: `apps/web/src/app/api/[...path]/route.ts`
- Verify/modify only if tests expose a regression: `scripts/faro_relay.py`
- Verify/modify only if tests expose a regression: `compose.yaml`
- Test: existing auth, proxy, tutor, compose, and Faro relay tests

- [ ] **Step 1: Run identity and proxy regression tests before changing code**

Run: `cd apps/web; pnpm test -- src/app/page.test.tsx src/components/auth/auth-form.test.tsx src/lib/api.test.ts src/app/api/[...path]/route.test.ts`

Expected: registration is followed by `/me`, login refreshes spaces, cookies are forwarded by the Next proxy, 401 clears authentication, and transient network errors do not render the login form. Any failure must be fixed with the smallest change and a failing regression assertion retained.

- [ ] **Step 2: Run API-side tutor/Faro boundary tests**

Run: `cd apps/api; uv run pytest tests/test_tutor_api.py tests/test_tutor_service.py tests/test_faro_relay.py tests/test_compose_security.py -q`

Expected: tests PASS without printing API secrets. If filenames differ, select existing `test_tutor*.py` files with PowerShell and pass their explicit paths to pytest.

- [ ] **Step 3: Rebuild the running product path**

Run: `docker compose up -d --build api worker web`

Expected: `api`, `worker`, and `web` are running; Postgres, Redis, and object storage remain healthy.

- [ ] **Step 4: Exercise Faro through the authenticated site API, not `/models`**

Use a disposable authenticated session through `http://127.0.0.1:3100/api/v1`, select a knowledge base with searchable content, and POST the same Tutor endpoint used by the browser UI. Assert HTTP success, a non-empty answer, and at least one knowledge citation when retrieval finds content. Inspect `docker compose logs --since 10m api worker faro-relay` and assert there are no proxy, TLS, or authentication errors. Redact tokens and never echo the Faro key.

- [ ] **Step 5: Verify browser-visible recovery**

Open the site, log in, start or observe a processing upload/candidate batch, switch to another workspace tab, return to knowledge, and assert the same server task is visible. Refresh and assert the explorer still lists both note and source roots.

### Task 7: Full verification and preservation checks

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run API focused and full suites**

Run:

```powershell
cd apps/api
uv run pytest tests/test_knowledge_workspace.py tests/test_knowledge_candidate_service.py tests/test_knowledge_retrieval.py tests/test_knowledge_graph.py -q
uv run pytest -q
uv run ruff check src tests
```

Expected: focused tests PASS; full suite has no failures (existing intentional skips remain skips); Ruff reports no issues.

- [ ] **Step 2: Run web focused and full suites plus build**

Run:

```powershell
cd apps/web
pnpm test -- src/lib/knowledge-api.test.ts src/components/workspace/knowledge-explorer.test.tsx src/components/workspace/knowledge-panel.test.tsx src/components/workspace/knowledge-graph-panel.test.tsx src/components/workspace/workspace-shell.test.tsx
pnpm test
pnpm build
```

Expected: focused and full tests PASS; Next production build succeeds.

- [ ] **Step 3: Check patch integrity and runtime health**

Run:

```powershell
git diff --check
docker compose ps
docker compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health').status)"
```

Expected: no whitespace errors; service rows are running/healthy; health status is `200`.

- [ ] **Step 4: Rehearse the existing real candidate batch in a rollback-only transaction**

For batch `b156986f-82f4-48a7-9bb9-4e35821cea81`, invoke the same confirmation service inside an explicit database transaction, assert 42 accepted notes and 34 accepted links can publish, then roll back. Confirm afterward that the batch remains `needs_review` and the formal-note count is unchanged. Do not call the public confirm endpoint and do not commit.

- [ ] **Step 5: Inspect the final diff without cleaning unrelated work**

Run: `git status --short --branch; git diff --stat; git diff --check`

Expected: only intended additions plus the pre-existing uncommitted changes are present; no `reset`, `clean`, recursive deletion, secret output, or automatic candidate confirmation occurred.
