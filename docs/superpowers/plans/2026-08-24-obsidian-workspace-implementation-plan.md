# Obsidian Personal Study Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current SaaS-style shell with the approved C review-inbox workspace: knowledge bases at far left, task tabs in the center, and the contextual AI tutor at right.

**Architecture:** Hoist knowledge-base loading and selection to a shell-level hook, convert knowledge and question panels to controlled components, and manage central views with a pure tab reducer. Desktop uses the existing resizable-panel library; tablet and mobile render the library and tutor as controlled drawers. This plan consumes the graph and tutor slices from the two prerequisite plans.

**Tech Stack:** Next.js 16, React 19, TypeScript, CSS Modules, react-resizable-panels 4.9, Vitest, Testing Library.

---

## Prerequisites and file map

Complete and verify these plans first:

1. `docs/superpowers/plans/2026-08-24-knowledge-graph-plan.md`
2. `docs/superpowers/plans/2026-08-24-contextual-ai-tutor-plan.md`

Before editing, read `apps/web/AGENTS.md`, `apps/web/node_modules/react-resizable-panels/README.md`, `DESIGN.md`, and `apps/web/.impeccable/surfaces/s-web-src-components-workspace-workspace-shell-tsx.md`.

- Create `apps/web/src/components/workspace/use-knowledge-library.ts`: shared list/create/select lifecycle.
- Create `apps/web/src/components/workspace/use-knowledge-library.test.tsx`: hook request and selection tests.
- Create `apps/web/src/components/workspace/workspace-tabs.ts`: central tab types and reducer.
- Create `apps/web/src/components/workspace/workspace-tabs.test.ts`: graph dedupe/close/focus tests.
- Create `apps/web/src/components/workspace/workspace-preferences.ts`: safe per-space last-view persistence.
- Create `apps/web/src/components/workspace/workspace-preferences.test.ts`: storage validation tests.
- Create `apps/web/src/components/workspace/workspace-icons.tsx`: inline accessible SVG primitives.
- Create `apps/web/src/components/workspace/knowledge-library-sidebar.tsx`: leftmost knowledge-base column.
- Create `apps/web/src/components/workspace/knowledge-library-sidebar.test.tsx`: separate row/button targets.
- Create `apps/web/src/components/workspace/study-dashboard.tsx`: continue-learning and due-review inbox.
- Create `apps/web/src/components/workspace/study-dashboard.test.tsx`: honest resume-state tests.
- Modify `apps/web/src/components/workspace/knowledge-panel.tsx`: controlled selected knowledge base.
- Modify `apps/web/src/components/workspace/knowledge-panel.test.tsx`: controlled-context tests.
- Modify `apps/web/src/components/workspace/question-bank-panel.tsx`: controlled selected knowledge base/question.
- Modify `apps/web/src/components/workspace/question-bank-panel.test.tsx`: controlled-context tests.
- Rewrite `apps/web/src/components/workspace/workspace-shell.tsx`: approved shell and integration.
- Rewrite `apps/web/src/components/workspace/workspace-shell.test.tsx`: approved interaction contract.
- Rewrite `apps/web/src/components/workspace/workspace-shell.module.css`: durable Obsidian-like layout.
- Modify `apps/web/src/components/workspace/workspace-styles.regression-1.test.ts`: new CSS invariants.
- Modify `DESIGN.md`: replace seed guidance with tokens that survive the build.

### Task 1: Create shared knowledge-library and tab state

**Files:**
- Create: `apps/web/src/components/workspace/use-knowledge-library.ts`
- Create: `apps/web/src/components/workspace/use-knowledge-library.test.tsx`
- Create: `apps/web/src/components/workspace/workspace-tabs.ts`
- Create: `apps/web/src/components/workspace/workspace-tabs.test.ts`
- Create: `apps/web/src/components/workspace/workspace-preferences.ts`
- Create: `apps/web/src/components/workspace/workspace-preferences.test.ts`

- [ ] **Step 1: Write failing hook, reducer, and persistence tests**

```ts
it("selects the first knowledge base and preserves an explicit selection after refresh", async () => {
  mockKnowledgeApi.list.mockResolvedValueOnce([wireless, digital]).mockResolvedValueOnce([
    wireless,
    digital,
    notes,
  ]);
  const { result } = renderHook(() => useKnowledgeLibrary("personal"));
  await waitFor(() => expect(result.current.selectedKnowledgeBaseId).toBe("wireless"));
  act(() => result.current.select("digital"));
  await act(() => result.current.refresh());
  expect(result.current.selectedKnowledgeBaseId).toBe("digital");
});

it("deduplicates a graph tab by knowledge base", () => {
  const once = reduceWorkspaceTabs(initialTabs, {
    type: "open-graph",
    knowledgeBaseId: "wireless",
    knowledgeBaseName: "无线通信",
  });
  const twice = reduceWorkspaceTabs(once, {
    type: "open-graph",
    knowledgeBaseId: "wireless",
    knowledgeBaseName: "无线通信",
  });
  expect(twice.tabs.filter((tab) => tab.id === "graph:wireless")).toHaveLength(1);
  expect(twice.activeTabId).toBe("graph:wireless");
});

it("rejects stale or malformed stored workspace preferences", () => {
  localStorage.setItem("workspace:personal", '{"activeTabId":7}');
  expect(readWorkspacePreference("personal")).toBeNull();
});
```

- [ ] **Step 2: Run tests and verify missing modules**

```powershell
pnpm --dir apps/web test -- src/components/workspace/use-knowledge-library.test.tsx src/components/workspace/workspace-tabs.test.ts src/components/workspace/workspace-preferences.test.ts
```

Expected: module resolution failures.

- [ ] **Step 3: Implement the state contracts**

Use this tab union:

```ts
export type WorkspaceTab =
  | { id: "today"; kind: "today"; label: "今日任务" }
  | { id: "knowledge"; kind: "knowledge"; label: "知识库" }
  | { id: "practice"; kind: "practice"; label: "题库练习"; questionVersionId?: string }
  | { id: `graph:${string}`; kind: "graph"; label: string; knowledgeBaseId: string };

export type WorkspaceTabsState = {
  tabs: WorkspaceTab[];
  activeTabId: WorkspaceTab["id"];
};
```

`useKnowledgeLibrary(spaceId)` returns `items`, `selectedKnowledgeBase`, `selectedKnowledgeBaseId`, `isLoading`, `error`, `select`, `create`, and `refresh`. Abort old list/create requests when `spaceId` changes or the hook unmounts. Selection belongs only here.

Persist only `{selectedKnowledgeBaseId, activeTabId}` under `workspace:${spaceId}`. Validate strings and known tab ID patterns before using stored values; storage failure must fall back silently.

- [ ] **Step 4: Run the state tests**

Expected: pass.

- [ ] **Step 5: Commit shared state**

```powershell
git add apps/web/src/components/workspace/use-knowledge-library.ts apps/web/src/components/workspace/use-knowledge-library.test.tsx apps/web/src/components/workspace/workspace-tabs.ts apps/web/src/components/workspace/workspace-tabs.test.ts apps/web/src/components/workspace/workspace-preferences.ts apps/web/src/components/workspace/workspace-preferences.test.ts
git commit -m "refactor(web): centralize workspace knowledge state"
```

### Task 2: Build the leftmost knowledge-library column

**Files:**
- Create: `apps/web/src/components/workspace/workspace-icons.tsx`
- Create: `apps/web/src/components/workspace/knowledge-library-sidebar.tsx`
- Create: `apps/web/src/components/workspace/knowledge-library-sidebar.test.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`

- [ ] **Step 1: Write failing sidebar tests**

```tsx
it("separates knowledge selection from the per-row graph action", async () => {
  const onSelect = vi.fn();
  const onOpenGraph = vi.fn();
  const user = userEvent.setup();
  render(
    <KnowledgeLibrarySidebar
      knowledgeBases={[wireless, digital]}
      selectedKnowledgeBaseId="wireless"
      onSelect={onSelect}
      onOpenGraph={onOpenGraph}
      onCreate={vi.fn()}
    />,
  );

  await user.click(screen.getByRole("button", { name: "选择数字通信" }));
  expect(onSelect).toHaveBeenCalledWith("digital");
  expect(onOpenGraph).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "打开数字通信关联图" }));
  expect(onOpenGraph).toHaveBeenCalledWith(digital);
  expect(onSelect).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 2: Run the sidebar test and verify failure**

```powershell
pnpm --dir apps/web test -- src/components/workspace/knowledge-library-sidebar.test.tsx
```

Expected: component is missing.

- [ ] **Step 3: Implement sidebar and inline SVG icons**

Render each row as siblings, never a nested button:

```tsx
<li className={styles.knowledgeBaseRow}>
  <button
    aria-current={selected ? "page" : undefined}
    aria-label={`选择${knowledgeBase.name}`}
    className={styles.knowledgeBaseName}
    onClick={() => onSelect(knowledgeBase.id)}
    type="button"
  >
    {knowledgeBase.name}
  </button>
  <button
    aria-label={`打开${knowledgeBase.name}关联图`}
    className={styles.knowledgeGraphButton}
    onClick={() => onOpenGraph(knowledgeBase)}
    title={`打开《${knowledgeBase.name}》关联图`}
    type="button"
  >
    <GraphIcon aria-hidden="true" />
  </button>
</li>
```

Put create-knowledge-base in a compact disclosure/form at the top. Put import, due review, space switch, classroom entry, and settings below the list or in the footer. Do not place classroom spaces above personal knowledge bases.

- [ ] **Step 4: Run sidebar tests**

Expected: selection, graph action, creation validation, loading, empty, and failure/retry tests pass.

- [ ] **Step 5: Commit the sidebar**

```powershell
git add apps/web/src/components/workspace/workspace-icons.tsx apps/web/src/components/workspace/knowledge-library-sidebar.tsx apps/web/src/components/workspace/knowledge-library-sidebar.test.tsx apps/web/src/components/workspace/workspace-shell.module.css
git commit -m "feat(web): add leftmost knowledge library"
```

### Task 3: Build the honest continue-learning dashboard

**Files:**
- Create: `apps/web/src/components/workspace/study-dashboard.tsx`
- Create: `apps/web/src/components/workspace/study-dashboard.test.tsx`
- Modify: `apps/web/src/lib/question-bank-api.ts`
- Modify: `apps/web/src/lib/question-bank-api.test.ts`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`

- [ ] **Step 1: Write failing dashboard and due-query tests**

```tsx
it("uses the first due review item as the primary continuation", async () => {
  mockQuestionBankApi.listReviewItems.mockResolvedValue({ items: [dueItem], next_cursor: null });
  const user = userEvent.setup();
  const onOpenPractice = vi.fn();
  render(<StudyDashboard knowledgeBase={wireless} onOpenKnowledge={vi.fn()} onOpenPractice={onOpenPractice} />);

  expect(await screen.findByRole("heading", { name: "继续上次练习" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "继续学习" }));
  expect(onOpenPractice).toHaveBeenCalledWith(dueItem.question_version_id);
});

it("does not invent reading progress when there is no persisted reading cursor", async () => {
  mockQuestionBankApi.listReviewItems.mockResolvedValue({ items: [], next_cursor: null });
  render(<StudyDashboard knowledgeBase={wireless} onOpenKnowledge={vi.fn()} onOpenPractice={vi.fn()} />);
  expect(await screen.findByText("从知识库检索或整理资料开始")).toBeInTheDocument();
  expect(screen.queryByText(/%/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests and verify failure**

```powershell
pnpm --dir apps/web test -- src/components/workspace/study-dashboard.test.tsx src/lib/question-bank-api.test.ts
```

Expected: dashboard missing and review client does not yet send `scope=due`.

- [ ] **Step 3: Implement due review and fallback behavior**

Extend `ReviewItem` with `attempted_at`. Change `listReviewItems` to accept `{scope?: "all" | "due"; limit?: number}` and build query parameters through `URLSearchParams`.

`StudyDashboard` loads `scope=due, limit=20`. Its primary state order is:

1. First due review item → heading “继续上次练习”, button opens practice at that question.
2. No due items → heading selected knowledge-base name, button opens the knowledge/search tab.
3. No selected knowledge base → instruct the user to create or select one.

Show due count and ordered rows. Do not render the synthetic 62% shown in the concept page because no reading cursor is currently persisted.

- [ ] **Step 4: Run dashboard and question client tests**

Expected: pass.

- [ ] **Step 5: Commit the dashboard**

```powershell
git add apps/web/src/components/workspace/study-dashboard.tsx apps/web/src/components/workspace/study-dashboard.test.tsx apps/web/src/lib/question-bank-api.ts apps/web/src/lib/question-bank-api.test.ts apps/web/src/components/workspace/workspace-shell.module.css
git commit -m "feat(web): add review-first study dashboard"
```

### Task 4: Convert knowledge and question panels to controlled context

**Files:**
- Modify: `apps/web/src/components/workspace/knowledge-panel.tsx:14-240`
- Modify: `apps/web/src/components/workspace/knowledge-panel.test.tsx`
- Modify: `apps/web/src/components/workspace/question-bank-panel.tsx:13-180`
- Modify: `apps/web/src/components/workspace/question-bank-panel.test.tsx`

- [ ] **Step 1: Replace tests with failing controlled-prop contracts**

```tsx
render(<KnowledgePanel spaceName="我的空间" knowledgeBase={wireless} />);
expect(mockKnowledgeApi.list).not.toHaveBeenCalled();
expect(screen.getByLabelText("知识库面板")).toHaveTextContent("无线通信");

render(<QuestionBankPanel knowledgeBase={wireless} initialQuestionVersionId="q-2" />);
expect(mockKnowledgeApi.list).not.toHaveBeenCalled();
await waitFor(() => expect(mockQuestionBankApi.listQuestions).toHaveBeenCalledWith("wireless", expect.any(AbortSignal)));
```

- [ ] **Step 2: Run both panel tests and verify prop errors/failures**

```powershell
pnpm --dir apps/web test -- src/components/workspace/knowledge-panel.test.tsx src/components/workspace/question-bank-panel.test.tsx
```

Expected: old components require `spaceId` and still list their own knowledge bases.

- [ ] **Step 3: Hoist knowledge-base state out of both panels**

Use these props:

```ts
type KnowledgePanelProps = {
  spaceName: string;
  knowledgeBase: KnowledgeBase;
};

type QuestionBankPanelProps = {
  knowledgeBase: KnowledgeBase;
  initialQuestionVersionId?: string;
};
```

Delete duplicated knowledge-base list/create/select state from both files. Key the inner stateful component by `knowledgeBase.id` so upload/search/candidate/answer requests are aborted and view state resets on selection. Keep all existing upload, status, candidate, search, preview, question, attempt, assessment, history, and review logic.

Remove the create-knowledge-base form and knowledge-base chip list from the center panel; creation now lives in the sidebar.

- [ ] **Step 4: Run the two panel suites**

Expected: existing real workflow tests pass with controlled fixtures and no duplicate `knowledgeApi.list` calls.

- [ ] **Step 5: Commit the controlled panels**

```powershell
git add apps/web/src/components/workspace/knowledge-panel.tsx apps/web/src/components/workspace/knowledge-panel.test.tsx apps/web/src/components/workspace/question-bank-panel.tsx apps/web/src/components/workspace/question-bank-panel.test.tsx
git commit -m "refactor(web): drive study panels from shell context"
```

### Task 5: Rebuild the desktop shell and central tabs

**Files:**
- Rewrite: `apps/web/src/components/workspace/workspace-shell.tsx`
- Rewrite: `apps/web/src/components/workspace/workspace-shell.test.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`

- [ ] **Step 1: Write failing approved-layout integration tests**

```tsx
it("renders knowledge bases at far left and the tutor at right", async () => {
  mockKnowledgeApi.list.mockResolvedValue([wireless, digital]);
  render(<WorkspaceShell spaces={[personalSpace]} />);

  expect(await screen.findByRole("navigation", { name: "知识库" })).toBeInTheDocument();
  expect(screen.getByRole("main")).toHaveAttribute("data-layout", "library-center-tutor");
  expect(screen.getByLabelText("AI 家教")).toBeInTheDocument();
  expect(screen.queryByText("服务正常")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("MVP 功能说明")).not.toBeInTheDocument();
});

it("opens and reuses the requested graph tab without changing library selection", async () => {
  mockKnowledgeApi.list.mockResolvedValue([wireless, digital]);
  const user = userEvent.setup();
  render(<WorkspaceShell spaces={[personalSpace]} />);
  await user.click(await screen.findByRole("button", { name: "打开数字通信关联图" }));
  expect(screen.getByRole("tab", { name: "关联图 · 数字通信" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("button", { name: "选择无线通信" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByLabelText("AI 家教")).toHaveTextContent("关联图：数字通信");
});
```

- [ ] **Step 2: Run shell tests and verify old-layout failures**

```powershell
pnpm --dir apps/web test -- src/components/workspace/workspace-shell.test.tsx
```

Expected: old space rail, static tree, MVP notice, repeated status, and missing graph/tutor behavior fail the new assertions.

- [ ] **Step 3: Implement the approved desktop composition**

At `>=1280px`, render one horizontal `Group` with IDs `library`, `center`, and `tutor`, defaults approximately `20/55/25`, and two keyboard-accessible separators. The shell owns:

- selected space and classroom modal state;
- `useKnowledgeLibrary(selectedSpace.id)`;
- `WorkspaceTabsState` and persisted preference;
- library/tutor drawer state for later responsive work;
- current tutor context derived from the active tab.

Central tab content mapping:

```tsx
switch (activeTab.kind) {
  case "today":
    return <StudyDashboard ... />;
  case "knowledge":
    return selectedKnowledgeBase ? <KnowledgePanel ... /> : <KnowledgeEmptyState />;
  case "practice":
    return selectedKnowledgeBase ? <QuestionBankPanel ... /> : <KnowledgeEmptyState />;
  case "graph":
    return <KnowledgeGraphPanel knowledgeBase={knowledgeBaseForGraphTab} />;
}
```

Remove the old topbar, docMeta strip, static content tree, MVP explanation, and bottom statusbar. Keep classroom create/join functionality behind the sidebar footer entry.

- [ ] **Step 4: Run shell, sidebar, graph, tutor, and panel tests**

```powershell
pnpm --dir apps/web test -- src/components/workspace/workspace-shell.test.tsx src/components/workspace/knowledge-library-sidebar.test.tsx src/components/workspace/knowledge-graph-panel.test.tsx src/components/workspace/tutor-panel.test.tsx src/components/workspace/knowledge-panel.test.tsx src/components/workspace/question-bank-panel.test.tsx
```

Expected: pass.

- [ ] **Step 5: Commit the desktop shell**

```powershell
git add apps/web/src/components/workspace/workspace-shell.tsx apps/web/src/components/workspace/workspace-shell.test.tsx apps/web/src/components/workspace/workspace-shell.module.css
git commit -m "feat(web): ship Obsidian study workspace shell"
```

### Task 6: Add tablet/mobile drawers and CSS regression contracts

**Files:**
- Create: `apps/web/src/components/workspace/use-workspace-breakpoint.ts`
- Create: `apps/web/src/components/workspace/use-workspace-breakpoint.test.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`
- Modify: `apps/web/src/components/workspace/workspace-styles.regression-1.test.ts`

- [ ] **Step 1: Write failing breakpoint and CSS contract tests**

```ts
it.each([
  [1400, "desktop"],
  [1100, "tablet"],
  [700, "mobile"],
] as const)("maps %ipx to %s", (width, expected) => {
  mockMatchMediaWidth(width);
  const { result } = renderHook(() => useWorkspaceBreakpoint());
  expect(result.current).toBe(expected);
});
```

Update the style regression test to require `@media (max-width: 1279px)`, `959px`, and `719px`, a fixed drawer backdrop, 44px mobile targets, and no page-level `min-width` above the viewport.

- [ ] **Step 2: Run breakpoint and style tests and verify failure**

```powershell
pnpm --dir apps/web test -- src/components/workspace/use-workspace-breakpoint.test.tsx src/components/workspace/workspace-styles.regression-1.test.ts
```

Expected: hook missing and old breakpoints fail.

- [ ] **Step 3: Implement responsive rendering**

- Desktop (`>=1280`): full resizable group.
- Tablet (`960–1279`): library + center; tutor opens as right drawer.
- Compact (`720–959`): center only; library and tutor open as left/right drawers.
- Mobile (`<720`): center only, one visible task; both side panels are modal drawers with focus return, Escape close, backdrop close, and 44px controls.

Use `matchMedia` subscriptions in the hook and render desktop panels or drawer portals based on the returned mode. Closing a drawer must not destroy tutor conversation or knowledge selection state.

- [ ] **Step 4: Run responsive and shell tests**

Expected: pass, including keyboard open/close and state preservation.

- [ ] **Step 5: Commit responsive behavior**

```powershell
git add apps/web/src/components/workspace/use-workspace-breakpoint.ts apps/web/src/components/workspace/use-workspace-breakpoint.test.tsx apps/web/src/components/workspace/workspace-shell.tsx apps/web/src/components/workspace/workspace-shell.module.css apps/web/src/components/workspace/workspace-styles.regression-1.test.ts
git commit -m "feat(web): add responsive study workspace drawers"
```

### Task 7: Full regression, browser acceptance, and design-system carbonization

**Files:**
- Modify: `DESIGN.md`
- Create: `.impeccable/design.json`
- Modify only source/test files implicated by a failing check.

- [ ] **Step 1: Run complete Web verification**

```powershell
pnpm test:web
pnpm lint:web
pnpm build:web
```

Expected: all exit 0.

- [ ] **Step 2: Run targeted API verification from prerequisite slices**

```powershell
& 'apps\api\.venv\Scripts\python.exe' -m pytest apps/api/tests/test_knowledge_graph.py apps/api/tests/test_tutor.py apps/api/tests/test_llm_faro.py apps/api/tests/test_schema.py -q -p no:cacheprovider
& 'apps\api\.venv\Scripts\python.exe' -m ruff check apps/api/src/tutor_api apps/api/tests/test_knowledge_graph.py apps/api/tests/test_tutor.py
```

Expected: pass.

- [ ] **Step 3: Rebuild Docker services and run browser acceptance**

Use the repository's real `.env` without printing it. Rebuild Web/API, then verify at widths 1440, 1024, 768, and 390:

- select three knowledge bases;
- open each row's graph button and confirm tab dedupe/correct context;
- open/close library and tutor drawers with keyboard;
- complete one knowledge search and one question attempt;
- verify missing-key tutor state sends no request;
- after adding the server key outside source control, send one grounded tutor prompt and open one citation;
- confirm no page-level horizontal scroll or console error.

- [ ] **Step 4: Re-run Impeccable document in scan mode**

Replace the seed marker in `DESIGN.md` with the exact implemented colors, typography, spacing, radius, component, breakpoint, and motion rules. Generate `.impeccable/design.json` from those real tokens. Do not change the approved “个人学习库房” north star or the left-library/center-tabs/right-tutor grammar.

- [ ] **Step 5: Run the required independent finish review**

Provide the reviewer with the original request, approved C comp, `PRODUCT.md`, `DESIGN.md`, the page spec, surface brief, browser screenshots, and relevant diff. Apply every material fix that protects the direction contract, accessibility, responsiveness, or real-function boundary. Do not run a second detector.

- [ ] **Step 6: Commit final verified design and fixes**

Commit design carbonization separately from any verification fix. First stage only the two design artifacts:

```powershell
git add DESIGN.md .impeccable/design.json
git diff --cached --name-only
git commit -m "docs: carbonize personal study workspace design"
```

If verification changed workspace source or tests, stage only the exact files named in that failing check (never `apps/web`, `apps/api/src/tutor_api`, or `apps/api/tests` as a directory), inspect `git diff --cached --name-only`, run `git diff --cached --check`, and commit them as `fix: close workspace verification gaps`. Unstage every pre-existing unrelated file before either commit.

## Execution clarifications (mandatory)

At the top of each new workspace test file, define complete local `KnowledgeBase` fixtures rather than importing test data from another suite:

```ts
const wireless: KnowledgeBase = { id: "wireless", space_id: "personal", name: "无线通信", state: "ready", created_at: "2026-08-24T00:00:00Z", updated_at: "2026-08-24T00:00:00Z" };
const digital: KnowledgeBase = { ...wireless, id: "digital", name: "数字通信" };
const notes: KnowledgeBase = { ...wireless, id: "notes", name: "学习笔记" };
```

Define `personalSpace`, due-review items, conversations, and graph results beside the tests that consume them, with every required field from the exported production type. Tests must not rely on execution order or another test file's module state.