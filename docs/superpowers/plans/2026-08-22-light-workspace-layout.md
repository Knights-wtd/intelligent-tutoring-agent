# Light Workspace Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有三栏工作台改为暖白、浅灰、柔紫与薄荷绿组成的浅色界面，移除装饰图标，改善信息层级和窄屏排版，同时保持全部现有功能行为。

**Architecture:** 保留 `WorkspaceShell`、`KnowledgePanel`、`QuestionBankPanel` 和现有 API client 的边界。`WorkspaceShell` 只调整语义结构、删除无功能装饰控件并为可响应面板添加稳定类名；视觉系统和断点集中维护在现有 CSS Module 中。测试以组件语义断言和 CSS 合同断言覆盖图标移除、占位控件移除、浅色 token 与无固定横向溢出。

**Tech Stack:** Next.js 16、React 19、TypeScript、CSS Modules、react-resizable-panels、Vitest、Testing Library。

**Safety:** 当前 feature worktree 包含大量用户已有改动。执行时只修改本计划列出的文件，不 stage、不 commit、不 stash、不 reset。

---

## File map

- Modify `apps/web/src/components/workspace/workspace-shell.tsx`: 删除装饰符号和无功能按钮，为三个可调面板及分隔线增加响应式类名。
- Modify `apps/web/src/components/workspace/workspace-shell.module.css`: 浅色 token、排版、控件层级、面板响应式和 reduced-motion。
- Modify `apps/web/src/components/workspace/workspace-shell.test.tsx`: 回归覆盖纯文字导航和占位控件清理。
- Modify `apps/web/src/components/workspace/workspace-styles.regression-1.test.ts`: 回归覆盖浅色设计 token、固定最小宽度移除和响应式面板规则。
- Modify `task_plan.md`, `progress.md`, `findings.md`: 记录实现、验证和剩余功能边界。

### Task 1: 锁定纯文字导航与真实交互边界

**Files:**
- Modify: `apps/web/src/components/workspace/workspace-shell.test.tsx`

- [ ] **Step 1: 添加失败的语义回归测试**

在 `WorkspaceShell` 测试末尾增加：

```tsx
it("uses text-only navigation and does not expose prototype-only actions", () => {
  render(<WorkspaceShell />);

  expect(screen.getByRole("main")).not.toHaveTextContent(/[⌕⋯◇📚📘📙▣↗◌●]/u);
  expect(screen.queryByRole("button", { name: "平台首页" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "创建或加入班级" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "搜索" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "更多操作" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "搜索空间内容" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "空间设置" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "展开工作区" })).not.toBeInTheDocument();
  expect(screen.getByText("服务正常")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
npm test -- --run src/components/workspace/workspace-shell.test.tsx
```

Expected: FAIL，报告装饰字符或原型按钮仍存在。

### Task 2: 清理图标和原型占位按钮

**Files:**
- Modify: `apps/web/src/components/workspace/workspace-shell.tsx:48-200`

- [ ] **Step 1: 将品牌和空间入口改为纯文字**

把品牌按钮改为静态品牌文字：

```tsx
<div className={styles.brandRow}>
  <strong className={styles.brand}>知学空间</strong>
</div>
```

删除“创建或加入班级”按钮。`SpaceButton` 只渲染文字内容：

```tsx
<button
  aria-current={selected ? "page" : undefined}
  aria-label={label}
  className={`${styles.spaceItem} ${selected ? styles.spaceItemActive : ""}`}
  onClick={onClick}
  type="button"
>
  <span className={styles.spaceCopy}>
    <b>{label}</b>
    <small>{isPersonal ? "个人学习资料" : "班级学习资料"}</small>
  </span>
</button>
```

- [ ] **Step 2: 删除顶部、树面板和标签栏中的无功能按钮**

删除以下按钮节点：平台首页、顶部搜索、更多操作、空间内容搜索、空间设置、左侧上传快捷按钮和展开工作区。保留中心知识库内真实的上传表单。顶部状态改为：

```tsx
<span className={styles.statusPill}>服务正常</span>
```

- [ ] **Step 3: 将内容树和辅助说明改成纯文字**

树节点改为：

```tsx
<div className={styles.treeNode}>教材与练习</div>
<div className={styles.treeNodeIndented}>资料文件</div>
<div className={styles.treeNodeFile}>
  已上传资料 <span className={styles.treeBadge}>可检索</span>
</div>
<div className={styles.treeNodeFile}>待处理资料</div>
<div className={styles.treeNodeActive}>资料检索</div>
<div className={styles.treeNode}>题库练习</div>
```

删除 `statusDot`、`contextMark`、`noticeIcon` 元素，并删除底部状态中的圆点字符。

- [ ] **Step 4: 为响应式面板增加稳定类名**

三个 `Panel` 和第二个 `Separator` 使用：

```tsx
<Panel className={styles.treePanelSlot} id="tree" minSize="18%" maxSize="34%">
<Panel className={styles.centerPanelSlot} id="center" minSize="34%">
<Separator
  aria-label="调整知识工作区和功能说明宽度"
  className={`${styles.separator} ${styles.contextSeparator}`}
/>
<Panel className={styles.contextPanelSlot} id="info" minSize="20%" maxSize="34%">
```

- [ ] **Step 5: 运行 focused 测试确认行为通过**

Run:

```powershell
npm test -- --run src/components/workspace/workspace-shell.test.tsx
```

Expected: PASS，现有空间切换、标签切换和键盘分隔线测试保持通过。

### Task 3: 建立浅色设计 token 和清晰表单层级

**Files:**
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`
- Modify: `apps/web/src/components/workspace/workspace-styles.regression-1.test.ts`

- [ ] **Step 1: 添加失败的 CSS 设计合同测试**

在 CSS Module 合同测试中增加：

```ts
it("keeps the approved light workspace tokens and responsive contract", () => {
  const stylesheet = readFileSync(
    path.join(process.cwd(), "src/components/workspace/workspace-shell.module.css"),
    "utf8",
  );

  expect(stylesheet).toContain("--bg: #fbfbfd");
  expect(stylesheet).toContain("--purple: #6558c9");
  expect(stylesheet).toContain("--green: #167c59");
  expect(stylesheet).not.toMatch(/\.panelGroup\s*\{[^}]*min-width:\s*(?:900|820|760)px/s);
  expect(stylesheet).toContain(".contextPanelSlot");
  expect(stylesheet).toContain("@media (prefers-reduced-motion: reduce)");
});
```

- [ ] **Step 2: 运行合同测试确认失败**

Run:

```powershell
npm test -- --run src/components/workspace/workspace-styles.regression-1.test.ts
```

Expected: FAIL，当前仍使用深色 token 和固定最小宽度。

- [ ] **Step 3: 替换根级视觉 token**

将 `.shell` token 调整为：

```css
.shell {
  --bg: #fbfbfd;
  --panel: #f7f7fa;
  --panel-deep: #ffffff;
  --panel-soft: #f2f1f7;
  --line: #e2e1e8;
  --text: #282733;
  --muted: #74727f;
  --purple: #6558c9;
  --purple-deep: #eeeafe;
  --green: #167c59;
  grid-template-columns: 184px minmax(0, 1fr);
  grid-template-rows: 48px minmax(0, 1fr) 30px;
  font-size: 13px;
}
```

将空间栏、顶部栏、内容树、中心面板、右栏和底栏分别使用 `#f2f1f7`、`#ffffff`、`#f7f7fa`、`#ffffff`、`#fafafd` 和 `#f7f7fa`，边框统一使用 `var(--line)`。

- [ ] **Step 4: 统一文字、卡片和控件尺寸**

按以下合同修改现有选择器：

```css
.knowledgePanel,
.questionBankPanel { gap: 16px; padding: 20px 22px 28px; }
.knowledgeHeader h2 { font-size: 20px; }
.inlineForm,
.searchForm,
.knowledgeHierarchy,
.questionCard,
.learningList,
.assessment { padding: 16px; border: 1px solid var(--line); border-radius: 12px; background: #fff; }
.inlineForm input,
.searchForm input { min-height: 40px; background: #fff; }
.knowledgePanel button,
.questionBankPanel button { min-height: 40px; border-radius: 8px; }
.inlineForm button[type="submit"],
.searchForm button[type="submit"] { border-color: var(--purple); background: var(--purple); color: #fff; }
```

普通文字颜色不浅于 `#74727f`；辅助标签最小 12px；底栏最小 11px。所有 hover/focus 使用 150–200ms 过渡。

- [ ] **Step 5: 移除废弃图标样式**

删除 `.spaceIcon`、`.railAction`、`.topButton`、`.iconButton`、`.headerActions`、`.uploadButton`、`.statusDot`、`.contextMark`、`.noticeIcon` 及其 hover/媒体查询引用。品牌 `.brand` 改为自适应宽度的文字，不再绘制方形图标。

- [ ] **Step 6: 运行 CSS 合同测试**

Run:

```powershell
npm test -- --run src/components/workspace/workspace-styles.regression-1.test.ts
```

Expected: PASS，两项 CSS 合同测试均通过。

### Task 4: 实现无横向溢出的响应式三栏

**Files:**
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`

- [ ] **Step 1: 取消固定工作区最小宽度**

```css
.panelGroup { width: 100%; min-width: 0; }
.treePanelSlot,
.centerPanelSlot,
.contextPanelSlot { min-width: 0; }
```

- [ ] **Step 2: 增加三个布局断点**

```css
@media (max-width: 1439px) {
  .shell { grid-template-columns: 160px minmax(0, 1fr); }
  .knowledgePanel, .questionBankPanel { padding-inline: 18px; }
}

@media (max-width: 1023px) {
  .shell { grid-template-columns: 132px minmax(0, 1fr); }
  .contextPanelSlot, .contextSeparator { display: none; }
  .metaPill { max-width: 38vw; }
}

@media (max-width: 767px) {
  .shell { grid-template-columns: 104px minmax(0, 1fr); }
  .treePanelSlot, .separator { display: none; }
  .inlineForm, .searchForm, .knowledgeHierarchy { grid-template-columns: 1fr; }
  .knowledgePanel button, .questionBankPanel button,
  .inlineForm input, .searchForm input { min-height: 44px; }
  .crumb, .metaPill { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .shell * { scroll-behavior: auto; transition-duration: .01ms !important; }
}
```

- [ ] **Step 3: 运行工作台和 CSS focused tests**

Run:

```powershell
npm test -- --run src/components/workspace/workspace-shell.test.tsx src/components/workspace/workspace-styles.regression-1.test.ts
```

Expected: PASS。

### Task 5: 完整验证和浏览器视觉验收

**Files:**
- Modify: `task_plan.md`
- Modify: `progress.md`
- Modify: `findings.md`

- [ ] **Step 1: 运行完整 Web 自动检查**

Run in `apps/web`:

```powershell
npm test -- --run
npm run lint
npx tsc --noEmit --incremental false
npm run build
```

Expected: 所有命令 exit 0；Vitest 0 failures；ESLint 0 errors；TypeScript 0 errors；Next.js build 完成。

- [ ] **Step 2: 重建本地 Web 容器**

Run in worktree root:

```powershell
docker compose --project-name mvp-phase6-20260821 --env-file .env.identity-test -f compose.yaml up -d --build --no-deps web
```

Expected: Web image built，容器 recreated、started、healthy。

- [ ] **Step 3: 浏览器视觉与功能验收**

在 `http://localhost:3000/` 登录现有本地测试账号，分别以 1440、1024、768px 视口检查：

- 页面为暖白/浅灰主色，柔紫突出当前项，薄荷绿只表示正常状态。
- 页面中不出现 emoji、字符图标、SVG 或无功能按钮。
- 1024px 隐藏右侧说明；768px 隐藏内容树；中心区无页面级横向滚动。
- 创建知识库、空库搜索、知识库/题库切换和题库空状态正常。
- 键盘 Tab 焦点清晰可见。

- [ ] **Step 4: 更新项目记录**

在三个记录文件追加同一日期条目，写明设计方案 A、修改范围、测试计数、浏览器验收结果和仍未实现的功能边界。不要把创建班级、空间设置、全局搜索或题目创作描述为已交付。

---

## Plan self-review

- Spec coverage: 色彩、三栏结构、图标清理、控件尺寸、响应式、可访问性、功能边界和验证均有对应任务。
- Placeholder scan: 无 TBD、TODO、模糊“适当处理”或未给命令的测试步骤。
- Type consistency: 新 CSS 类名在 JSX、CSS 和测试中统一为 `treePanelSlot`、`centerPanelSlot`、`contextPanelSlot`、`contextSeparator`。
- Scope: 仅 Web 组件、CSS、测试和项目记录；不触碰 API、数据库或未实现功能。
