# Per-Knowledge-Base Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real, tenant-safe graph endpoint and an accessible Obsidian-style graph panel for each knowledge base.

**Architecture:** Read accepted notes and links from confirmed candidate batches without adding a migration. The API returns stable node and edge DTOs scoped through existing readable-knowledge-base authorization. The Web client renders a deterministic native SVG plus an equivalent searchable node list, so no graph dependency is added.

**Tech Stack:** FastAPI, SQLAlchemy 2, Pydantic, pytest, Next.js 16, React 19, TypeScript, Vitest, Testing Library, native SVG.

---

## File map

- Create `apps/api/src/tutor_api/knowledge/graph.py`: graph query and domain DTOs.
- Modify `apps/api/src/tutor_api/knowledge/schemas.py`: public graph response schemas.
- Modify `apps/api/src/tutor_api/knowledge/router.py`: authenticated graph endpoint.
- Create `apps/api/tests/test_knowledge_graph.py`: query, filtering, authorization, and endpoint tests.
- Modify `apps/web/src/lib/knowledge-api.ts`: graph types and `knowledgeApi.graph()`.
- Modify `apps/web/src/lib/knowledge-api.test.ts`: client URL and error tests.
- Create `apps/web/src/components/workspace/graph-layout.ts`: deterministic layout with bounded coordinates.
- Create `apps/web/src/components/workspace/graph-layout.test.ts`: pure layout tests.
- Create `apps/web/src/components/workspace/knowledge-graph-panel.tsx`: SVG, search, focus, states, and text alternative.
- Create `apps/web/src/components/workspace/knowledge-graph-panel.test.tsx`: graph interaction and accessibility tests.
- Modify `apps/web/src/components/workspace/workspace-shell.module.css`: graph surface styles only; shell integration belongs to the workspace plan.

### Task 1: Build the tenant-scoped graph query

**Files:**
- Create: `apps/api/src/tutor_api/knowledge/graph.py`
- Create: `apps/api/tests/test_knowledge_graph.py`

- [ ] **Step 1: Write the failing domain tests**

Add fixtures that create two knowledge bases, a confirmed batch with accepted/rejected notes and links, and a second unconfirmed batch. Assert that only accepted records from the requested confirmed knowledge base are returned and that a classroom learner can read but an outsider receives the existing 404 behavior.

```python
def test_graph_contains_only_accepted_records_from_confirmed_batches(session) -> None:
    owner, space, knowledge_base, _, _ = create_source(session)
    batch, chapter, concept, link = seed_graph_batch(session, owner, space, knowledge_base)

    graph = load_knowledge_graph(session, owner, knowledge_base.id)

    assert [node.title for node in graph.nodes] == ["移动无线传播", "路径损耗"]
    assert [(edge.source_id, edge.target_id, edge.relation) for edge in graph.edges] == [
        (chapter.id, concept.id, "mentions")
    ]
    assert batch.state is CandidateBatchState.CONFIRMED
    assert link.review_state is CandidateReviewState.ACCEPTED


def test_graph_hides_another_users_knowledge_base(session) -> None:
    owner, space, knowledge_base, _, _ = create_source(session)
    outsider = create_user(session, "outsider@example.com")
    seed_graph_batch(session, owner, space, knowledge_base)

    with pytest.raises(HTTPException) as error:
        load_knowledge_graph(session, outsider, knowledge_base.id)

    assert error.value.status_code == 404
```

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_knowledge_graph.py -q -p no:cacheprovider
```

Expected: collection fails because `tutor_api.knowledge.graph` does not exist.

- [ ] **Step 3: Implement immutable graph DTOs and the query**

Create `graph.py` with these public contracts and a query that joins `KnowledgeCandidateBatch`, filters `CONFIRMED`, filters note/link review state `ACCEPTED`, and resolves link endpoint keys inside the same batch.

```python
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_readable_knowledge_base
from tutor_api.knowledge.models import (
    CandidateBatchState,
    CandidateReviewState,
    KnowledgeCandidateBatch,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
)


@dataclass(frozen=True, slots=True)
class KnowledgeGraphNode:
    id: UUID
    title: str
    kind: str
    source_pointers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeGraphEdge:
    id: UUID
    source_id: UUID
    target_id: UUID
    kind: str
    relation: str
    source_pointer: str


@dataclass(frozen=True, slots=True)
class KnowledgeGraph:
    knowledge_base_id: UUID
    nodes: tuple[KnowledgeGraphNode, ...]
    edges: tuple[KnowledgeGraphEdge, ...]


def load_knowledge_graph(
    session: Session, user: User, knowledge_base_id: UUID
) -> KnowledgeGraph:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    notes = list(
        session.scalars(
            select(KnowledgeCandidateNote)
            .join(KnowledgeCandidateBatch, KnowledgeCandidateBatch.id == KnowledgeCandidateNote.batch_id)
            .where(
                KnowledgeCandidateNote.knowledge_base_id == knowledge_base.id,
                KnowledgeCandidateNote.space_id == knowledge_base.space_id,
                KnowledgeCandidateNote.review_state == CandidateReviewState.ACCEPTED,
                KnowledgeCandidateBatch.state == CandidateBatchState.CONFIRMED,
            )
            .order_by(KnowledgeCandidateNote.created_at, KnowledgeCandidateNote.ordinal)
        )
    )
    node_id_by_key = {(note.batch_id, note.candidate_key): note.id for note in notes}
    links = list(
        session.scalars(
            select(KnowledgeCandidateLink)
            .join(KnowledgeCandidateBatch, KnowledgeCandidateBatch.id == KnowledgeCandidateLink.batch_id)
            .where(
                KnowledgeCandidateLink.knowledge_base_id == knowledge_base.id,
                KnowledgeCandidateLink.space_id == knowledge_base.space_id,
                KnowledgeCandidateLink.review_state == CandidateReviewState.ACCEPTED,
                KnowledgeCandidateBatch.state == CandidateBatchState.CONFIRMED,
            )
            .order_by(KnowledgeCandidateLink.created_at, KnowledgeCandidateLink.ordinal)
        )
    )
    edges = tuple(
        KnowledgeGraphEdge(
            id=link.id,
            source_id=node_id_by_key[(link.batch_id, link.source_key)],
            target_id=node_id_by_key[(link.batch_id, link.target_key)],
            kind=link.kind.value,
            relation=link.relation,
            source_pointer=link.source_pointer,
        )
        for link in links
        if (link.batch_id, link.source_key) in node_id_by_key
        and (link.batch_id, link.target_key) in node_id_by_key
    )
    return KnowledgeGraph(
        knowledge_base_id=knowledge_base.id,
        nodes=tuple(
            KnowledgeGraphNode(
                id=note.id,
                title=note.title,
                kind=note.kind.value,
                source_pointers=tuple(note.source_pointers),
            )
            for note in notes
        ),
        edges=edges,
    )
```

- [ ] **Step 4: Run the domain tests**

Run the command from Step 2. Expected: all graph query tests pass.

- [ ] **Step 5: Commit the domain query**

```powershell
git add apps/api/src/tutor_api/knowledge/graph.py apps/api/tests/test_knowledge_graph.py
git commit -m "feat(api): query confirmed knowledge graphs"
```

### Task 2: Expose the graph endpoint

**Files:**
- Modify: `apps/api/src/tutor_api/knowledge/schemas.py:75-130`
- Modify: `apps/api/src/tutor_api/knowledge/router.py:180-250`
- Modify: `apps/api/tests/test_knowledge_graph.py`

- [ ] **Step 1: Add failing endpoint tests**

```python
def test_get_graph_returns_nodes_and_edges(client_and_engine) -> None:
    client, engine = client_and_engine
    registration = register(client, "graph-owner")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    seed_confirmed_graph(engine, registration["user"]["id"], knowledge_base["id"])

    response = client.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}/graph")

    assert response.status_code == 200
    assert response.json()["knowledge_base_id"] == knowledge_base["id"]
    assert len(response.json()["nodes"]) == 2
    assert len(response.json()["edges"]) == 1
```

- [ ] **Step 2: Verify the endpoint is absent**

Run the graph test command. Expected: endpoint test receives 404.

- [ ] **Step 3: Add response schemas and route**

```python
class KnowledgeGraphNodeResponse(BaseModel):
    id: UUID
    title: str
    kind: str
    source_pointers: list[str]


class KnowledgeGraphEdgeResponse(BaseModel):
    id: UUID
    source_id: UUID
    target_id: UUID
    kind: str
    relation: str
    source_pointer: str


class KnowledgeGraphResponse(BaseModel):
    knowledge_base_id: UUID
    nodes: list[KnowledgeGraphNodeResponse]
    edges: list[KnowledgeGraphEdgeResponse]
```

Add a `GET /api/v1/knowledge-bases/{knowledge_base_id}/graph` route that opens `session_scope`, calls `load_knowledge_graph`, and maps tuples to the response schemas. Do not catch the existing authorization exceptions.

- [ ] **Step 4: Run graph and knowledge authorization tests**

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_knowledge_graph.py apps/api/tests/test_knowledge_retrieval.py -q -p no:cacheprovider
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the endpoint**

```powershell
git add apps/api/src/tutor_api/knowledge/schemas.py apps/api/src/tutor_api/knowledge/router.py apps/api/tests/test_knowledge_graph.py
git commit -m "feat(api): expose knowledge graph snapshots"
```

### Task 3: Add the Web graph client and deterministic layout

**Files:**
- Modify: `apps/web/src/lib/knowledge-api.ts`
- Modify: `apps/web/src/lib/knowledge-api.test.ts`
- Create: `apps/web/src/components/workspace/graph-layout.ts`
- Create: `apps/web/src/components/workspace/graph-layout.test.ts`

- [ ] **Step 1: Write failing client and layout tests**

```ts
it("requests one knowledge base graph", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ knowledge_base_id: "kb/1", nodes: [], edges: [] })),
  );
  await knowledgeApi.graph("kb/1");
  expect(fetch).toHaveBeenCalledWith("/api/v1/knowledge-bases/kb%2F1/graph", expect.anything());
});

it("keeps every graph node inside the view box", () => {
  const positions = layoutGraph(
    Array.from({ length: 12 }, (_, index) => ({ id: `n-${index}`, title: `N${index}` })),
    800,
    520,
  );
  expect([...positions.values()].every(({ x, y }) => x >= 48 && x <= 752 && y >= 48 && y <= 472)).toBe(true);
});
```

- [ ] **Step 2: Run the two Web tests and verify failure**

```powershell
pnpm --dir apps/web test -- src/lib/knowledge-api.test.ts src/components/workspace/graph-layout.test.ts
```

Expected: missing `knowledgeApi.graph` and `graph-layout` module failures.

- [ ] **Step 3: Add graph types, request method, and layout**

Use these public Web types:

```ts
export type KnowledgeGraphNode = {
  id: string;
  title: string;
  kind: string;
  source_pointers: string[];
};

export type KnowledgeGraphEdge = {
  id: string;
  source_id: string;
  target_id: string;
  kind: string;
  relation: string;
  source_pointer: string;
};

export type KnowledgeGraph = {
  knowledge_base_id: string;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
};
```

Add `knowledgeApi.graph(id, signal)` using the existing `requestJson` and `resource` helpers. Declare `type GraphLayoutNode = Pick<KnowledgeGraphNode, "id" | "title">` and accept `readonly GraphLayoutNode[]` in `layoutGraph`, so pure layout tests do not invent API-only fields. Implement a stable radial layout: sort by `id`, place one node at center, place remaining nodes on rings of at most eight, clamp every coordinate to a 48px inset, and return `Map<string, {x: number; y: number}>`.

- [ ] **Step 4: Run the two Web tests**

Expected: both files pass.

- [ ] **Step 5: Commit the client and layout**

```powershell
git add apps/web/src/lib/knowledge-api.ts apps/web/src/lib/knowledge-api.test.ts apps/web/src/components/workspace/graph-layout.ts apps/web/src/components/workspace/graph-layout.test.ts
git commit -m "feat(web): add graph client and layout"
```

### Task 4: Build the accessible graph panel

**Files:**
- Create: `apps/web/src/components/workspace/knowledge-graph-panel.tsx`
- Create: `apps/web/src/components/workspace/knowledge-graph-panel.test.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`

- [ ] **Step 1: Write failing component tests**

Cover loading, empty, failure/retry, search, node focus, SVG labels, and the text alternative.

```tsx
it("renders a searchable SVG and equivalent node list", async () => {
  mockKnowledgeApi.graph.mockResolvedValue(graphFixture);
  const user = userEvent.setup();
  render(<KnowledgeGraphPanel knowledgeBase={{ id: "kb-1", name: "无线通信" }} />);

  expect(await screen.findByRole("img", { name: "无线通信关联图" })).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "关联图节点列表" })).toHaveTextContent("路径损耗");
  await user.type(screen.getByRole("searchbox", { name: "搜索关联图节点" }), "路径");
  expect(screen.getByRole("button", { name: "聚焦路径损耗" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the component test and verify failure**

```powershell
pnpm --dir apps/web test -- src/components/workspace/knowledge-graph-panel.test.tsx
```

Expected: component module is missing.

- [ ] **Step 3: Implement the panel**

The component accepts `knowledgeBase: Pick<KnowledgeBase, "id" | "name">`. On ID change it aborts the old request, loads `knowledgeApi.graph`, and resets search/focus. Render:

- `<svg role="img" aria-label={`${name}关联图`}>` with `<line>` edges and keyboard-focusable node buttons represented through a paired list.
- A searchbox that filters the node list without deleting graph context.
- A visible “适应视图” control that clears node focus and restores the full-layout transform.
- A selected-node details region showing kind and source pointers.
- An empty state linking back through an optional `onReviewCandidates` callback.
- A retry button on non-abort failure.

Use native SVG only. Put visible node interaction in HTML buttons layered over the graph or in the equivalent list; do not make Canvas the only interaction surface.

- [ ] **Step 4: Run component, layout, and client tests**

```powershell
pnpm --dir apps/web test -- src/components/workspace/knowledge-graph-panel.test.tsx src/components/workspace/graph-layout.test.ts src/lib/knowledge-api.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the graph panel**

```powershell
git add apps/web/src/components/workspace/knowledge-graph-panel.tsx apps/web/src/components/workspace/knowledge-graph-panel.test.tsx apps/web/src/components/workspace/workspace-shell.module.css
git commit -m "feat(web): render accessible knowledge graphs"
```

### Task 5: Verify the graph slice

**Files:**
- Modify only if a verification failure reveals a graph-slice defect.

- [ ] **Step 1: Run API graph and schema tests**

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_knowledge_graph.py apps/api/tests/test_knowledge_schema.py -q -p no:cacheprovider
```

Expected: pass.

- [ ] **Step 2: Run Web tests, lint, and type-aware build**

```powershell
pnpm --dir apps/web test -- src/components/workspace/knowledge-graph-panel.test.tsx src/components/workspace/graph-layout.test.ts src/lib/knowledge-api.test.ts
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: all commands exit 0.

- [ ] **Step 3: Record the verification commit only if fixes were needed**

Stage only the exact graph files changed by verification, inspect `git diff --cached --name-only`, and then commit:

```powershell
git add apps/api/src/tutor_api/knowledge/graph.py apps/api/src/tutor_api/knowledge/schemas.py apps/api/src/tutor_api/knowledge/router.py apps/api/tests/test_knowledge_graph.py apps/web/src/lib/knowledge-api.ts apps/web/src/lib/knowledge-api.test.ts apps/web/src/components/workspace/graph-layout.ts apps/web/src/components/workspace/graph-layout.test.ts apps/web/src/components/workspace/knowledge-graph-panel.tsx apps/web/src/components/workspace/knowledge-graph-panel.test.tsx apps/web/src/components/workspace/workspace-shell.module.css
git diff --cached --name-only
git commit -m "fix: close knowledge graph verification gaps"
```

## Execution clarifications (mandatory)

Keep every helper in `apps/api/tests/test_knowledge_graph.py`; do not depend on another test module at runtime.

- Copy the existing `session` and `create_source` helpers from `test_knowledge_candidate_models.py` unchanged.
- Define `create_user(session, email)` by deriving a unique username from the email, constructing `User(email=email, username=username, password_hash="hash")`, adding it, flushing, and returning it.
- Define `seed_graph_batch(session, owner, space, knowledge_base)` using the document/version created by `create_source`. Create one `CONFIRMED` batch; accepted chapter/concept notes named “移动无线传播” and “路径损耗”; one rejected note; one accepted `mentions` link between the accepted notes; one rejected link; and one separate `NEEDS_REVIEW` batch. Commit and return `(batch, chapter, concept, link)`.
- For HTTP tests, copy `make_client`, `register`, and `create_knowledge_base` from `test_knowledge_retrieval.py`. Define `seed_confirmed_graph(engine, user_id, knowledge_base_id)` to open a session, load the registered user's personal space and requested knowledge base, create its document/version plus the same confirmed two-node graph, commit, and close the session.