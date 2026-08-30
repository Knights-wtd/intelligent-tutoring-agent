# Agent Web Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用支持流式事件、工具卡片、会话恢复、设置和工作区文件导航的 React AgentPanel 替代受限聊天体验，并保持现有知识库工作区交互不回归。

**Architecture:** 浏览器用 REST 创建/控制 session，用直接指向 FastAPI 的 WebSocket 接收可重放事件；客户端 reducer 只根据持久事件构建 UI，断线按 sequence cursor 重连。组件按 composer、message list、tool card、session sidebar 和 settings 拆分，Claudian 的交互与样式意图尽量复用，但不引入 Obsidian API。

**Tech Stack:** Next.js 16.3, React 19.2, TypeScript, Vitest 4, Testing Library, CSS Modules, WebSocket

---

## Next.js 16.3 约束

实施前读取 `apps/web/node_modules/next/dist/docs/01-app/02-guides/backend-for-frontend.md` 中 Route Handler 和 WebSocket 限制，以及 `apps/web/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/route.md` 的 streaming 说明。Next Route Handler 继续代理普通 HTTP；由于部署适配器可能在 response 后关闭连接，不在 `apps/web/src/app/api/[...path]/route.ts` 中模拟 WebSocket upgrade。生产反向代理应将 `/api/v1/agent/ws/*` 直接转发 FastAPI。

### Task 1: 建立 Agent API client 和事件 reducer

**Files:**
- Create: `apps/web/src/lib/agent-api.ts`
- Create: `apps/web/src/lib/agent-events.ts`
- Create: `apps/web/src/lib/agent-api.test.ts`
- Create: `apps/web/src/lib/agent-events.test.ts`
- Modify: `apps/web/src/lib/api-base.ts`

- [ ] **Step 1: 写事件幂等和 WebSocket URL 失败测试**

```ts
it("deduplicates replayed events and preserves sequence order", () => {
  const once = reduceAgentEvents(emptyAgentView(), event({ sequence: 1, idempotency_key: "one" }));
  const replayed = reduceAgentEvents(once, event({ sequence: 1, idempotency_key: "one" }));
  expect(replayed.events).toHaveLength(1);
  expect(replayed.lastSequence).toBe(1);
});

it("builds a direct FastAPI websocket URL", () => {
  expect(agentWebSocketUrl("session", 9, "http://localhost:8000"))
    .toBe("ws://localhost:8000/api/v1/agent/ws/session?after=9");
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/web test -- src/lib/agent-api.test.ts src/lib/agent-events.test.ts`

Expected: FAIL，因为 client/reducer 尚不存在。

- [ ] **Step 3: 定义共享 Web 类型**

```ts
export type AgentSessionState = "running" | "waiting_input" | "stopped" | "failed" | "archived";

export interface AgentEventEnvelope {
  event_id: string;
  session_id: string;
  turn_id: string | null;
  sequence: number;
  event_type: string;
  timestamp: string;
  payload: Record<string, unknown>;
  idempotency_key: string;
}

export interface AgentSessionSummary {
  id: string;
  title: string;
  provider: string;
  model: string;
  state: AgentSessionState;
  last_event_sequence: number;
  is_legacy: boolean;
}
```

Web 类型必须与 `packages/agent-protocol` JSON contract 保持字段名一致；不得加入 `maxEvidence`、`maxHistoryMessages`、`maxWebResults`。

- [ ] **Step 4: 实现 REST 和 WebSocket client**

`agentApi` 包含 create/list/get/archive/send/stop/resume/rewind/fork/events/settings/MCP/Skills/diagnostics/sidecar。`connectAgentEvents(sessionId,after,onEvent,onState)` 使用 exponential backoff，收到事件后立即推进本地 cursor；关闭 code 表示 unauthorized 时停止重试，普通断线重连并带 `after`。

- [ ] **Step 5: 实现 reducer**

Reducer 维护 message blocks、thinking、tool lifecycle、subagent、usage、session state、index state 和 error。只接受 `sequence == lastSequence + 1` 或完全相同的 replay event；gap 触发 `needsReplay`，不自行猜测缺失内容。大 payload 显示 sidecar 引用，按需请求 preview。

- [ ] **Step 6: 运行测试**

Run: `pnpm --dir apps/web test -- src/lib/agent-api.test.ts src/lib/agent-events.test.ts`

Expected: PASS，包括 replay、gap、reconnect、401/403 停止和 ws/wss URL。

- [ ] **Step 7: 提交**

```powershell
git add apps/web/src/lib
git commit -m "feat: add replayable agent web client"
```

### Task 2: 构建 Agent composer 和消息列表

**Files:**
- Create: `apps/web/src/components/workspace/agent-composer.tsx`
- Create: `apps/web/src/components/workspace/agent-message-list.tsx`
- Create: `apps/web/src/components/workspace/agent-panel.module.css`
- Create: `apps/web/src/components/workspace/agent-composer.test.tsx`
- Create: `apps/web/src/components/workspace/agent-message-list.test.tsx`

- [ ] **Step 1: 写长输入和来源组合失败测试**

```tsx
it("submits a prompt longer than 500 characters without client truncation", async () => {
  const prompt = "知识库与网页联合推理。".repeat(100);
  render(<AgentComposer disabled={false} onSend={onSend} linkedContexts={[]} />);
  await user.type(screen.getByRole("textbox"), prompt);
  await user.click(screen.getByRole("button", { name: "发送" }));
  expect(onSend).toHaveBeenCalledWith(expect.objectContaining({ text: prompt }));
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/web test -- agent-composer agent-message-list`

Expected: FAIL，因为组件尚不存在。

- [ ] **Step 3: 实现 composer**

Composer 支持普通文本、当前文件/选择、多个 Vault 文件引用、附件、Skill 和 agent mention；不设置 500/4000 字符产品上限。发送时只传引用和用户输入，不把本地知识证据预先截为 5/20 条。running 状态显示 Stop，stopped/failed 状态显示 Resume；快捷键与 Claudian 风格一致，IME composition 不误发送。

- [ ] **Step 4: 实现 message list**

消息列表按 turn 渲染 user、assistant streaming text、thinking 折叠块、citation/link、compaction、usage 和 error；加载旧事件时保持稳定 key。知识库引用回调提供 `{knowledgeBaseId,vaultFileId,path,heading}`，网页引用使用安全新窗口；不把网页正文缩成唯一固定短摘录。

- [ ] **Step 5: 运行测试**

Run: `pnpm --dir apps/web test -- agent-composer agent-message-list`

Expected: PASS，包括 >500 字输入、IME、多上下文、stream delta、legacy message、知识库与网页链接。

- [ ] **Step 6: 提交**

```powershell
git add apps/web/src/components/workspace/agent-composer* apps/web/src/components/workspace/agent-message-list* apps/web/src/components/workspace/agent-panel.module.css
git commit -m "feat: add unrestricted agent composer and messages"
```

### Task 3: 构建工具、diff、命令、Web、MCP 和子智能体卡片

**Files:**
- Create: `apps/web/src/components/workspace/agent-tool-card.tsx`
- Create: `apps/web/src/components/workspace/agent-tool-card.test.tsx`
- Create: `apps/web/src/components/workspace/agent-sidecar-preview.tsx`
- Create: `apps/web/src/components/workspace/agent-sidecar-preview.test.tsx`
- Modify: `apps/web/src/components/workspace/agent-panel.module.css`

- [ ] **Step 1: 写工具生命周期失败测试**

```tsx
it.each(["bash", "read", "write", "web_search", "web_fetch", "mcp", "skill", "subagent"])(
  "renders %s lifecycle without approval UI",
  (toolKind) => {
    render(<AgentToolCard tool={toolEvent({ toolKind, state: "running" })} />);
    expect(screen.getByTestId(`agent-tool-${toolKind}`)).toBeVisible();
    expect(screen.queryByText("批准执行")).not.toBeInTheDocument();
  },
);
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/web test -- agent-tool-card agent-sidecar-preview`

Expected: FAIL，因为组件尚不存在。

- [ ] **Step 3: 实现 tool cards**

Tool card 统一呈现状态、耗时、输入摘要和输出；write/edit/move/delete 显示 path 与 diff；Bash 显示 command/cwd/exit code 和流式输出；Web 显示 URL/search query；MCP 显示 server/tool；Skill/Subagent 显示名称和父子关联。界面不出现 host command 审批按钮，因为已确认默认 yolo；危险权限在设置和文档中持续警示。

- [ ] **Step 4: 实现 sidecar preview**

Preview 按 media type 流式加载文本/JSON/diff，显示 size/hash 和“下载完整内容”；默认只渲染虚拟化窗口防止 DOM 卡死，但完整 sidecar 可继续读取，不向用户谎称内容被截断。HTML 作为文本或 sandboxed preview，绝不直接注入未净化 HTML。

- [ ] **Step 5: 运行测试**

Run: `pnpm --dir apps/web test -- agent-tool-card agent-sidecar-preview`

Expected: PASS，包括 tool progress/completed/failed、large output、diff、Bash、Web、MCP、Skill 和 subagent。

- [ ] **Step 6: 提交**

```powershell
git add apps/web/src/components/workspace/agent-tool-card* apps/web/src/components/workspace/agent-sidecar-preview* apps/web/src/components/workspace/agent-panel.module.css
git commit -m "feat: render agent tools and full sidecars"
```

### Task 4: 构建 session sidebar、设置和诊断

**Files:**
- Create: `apps/web/src/components/workspace/agent-session-sidebar.tsx`
- Create: `apps/web/src/components/workspace/agent-session-sidebar.test.tsx`
- Create: `apps/web/src/components/workspace/agent-settings.tsx`
- Create: `apps/web/src/components/workspace/agent-settings.test.tsx`
- Modify: `apps/web/src/components/workspace/agent-panel.module.css`

- [ ] **Step 1: 写 session 恢复和设置失败测试**

```tsx
it("offers resume rewind and fork for a native session", async () => {
  render(<AgentSessionSidebar sessions={[nativeSession()]} onResume={resume} onRewind={rewind} onFork={fork} />);
  expect(screen.getByRole("button", { name: "继续" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "回退" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "分叉" })).toBeEnabled();
});

it("shows one-million-token configuration and no evidence count fields", () => {
  render(<AgentSettings value={settings({ context_window: 1_000_000 })} />);
  expect(screen.getByDisplayValue("1000000")).toBeVisible();
  expect(screen.queryByLabelText(/证据数量|历史条数|网页结果数/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/web test -- agent-session-sidebar agent-settings`

Expected: FAIL，因为组件尚不存在。

- [ ] **Step 3: 实现 session sidebar**

显示 active/warm/archived/legacy sessions，支持新建、切换、归档、Stop、Resume、Rewind、Fork。legacy Tutor session 只允许查看和归档，不显示原生恢复动作。刷新后从 URL/local preference 恢复 session ID，再用 last persisted sequence 重放。

- [ ] **Step 4: 实现设置和诊断**

设置包括 provider/model/context window、permission mode、workspace roots、MCP、Skills、subagent、Web 和 Runtime health。默认显示 `bypassPermissions` 风险警告；context window 可为 1,000,000，但后端返回 provider capability 小于请求时显示实际值。secret 只显示 configured/not-configured，不回显明文。License/commit 信息不在前端展示。

- [ ] **Step 5: 运行测试**

Run: `pnpm --dir apps/web test -- agent-session-sidebar agent-settings`

Expected: PASS，包括 legacy read-only、refresh restore、million context、health degradation 和 secret redaction。

- [ ] **Step 6: 提交**

```powershell
git add apps/web/src/components/workspace/agent-session-sidebar* apps/web/src/components/workspace/agent-settings* apps/web/src/components/workspace/agent-panel.module.css
git commit -m "feat: add agent sessions settings and diagnostics"
```

### Task 5: 组装 AgentPanel 并接入工作区导航

**Files:**
- Create: `apps/web/src/components/workspace/agent-panel.tsx`
- Create: `apps/web/src/components/workspace/agent-panel.test.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.tsx:1-360`
- Modify: `apps/web/src/components/workspace/workspace-shell.test.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`
- Modify: `apps/web/src/components/workspace/workspace-preferences.ts`
- Modify: `apps/web/src/components/workspace/workspace-preferences.test.ts`

- [ ] **Step 1: 写端到端组件失败测试**

```tsx
it("replays a running session and opens a file from another readable knowledge base", async () => {
  render(<WorkspaceShell spaces={spaces} />);
  await user.click(screen.getByRole("button", { name: "AI 助教" }));
  server.emit(agentFileLink({ spaceId: "class-space", knowledgeBaseId: "class-kb", path: "概念/函数.md" }));
  await user.click(await screen.findByRole("button", { name: "打开 概念/函数.md" }));
  expect(await screen.findByText("函数知识库")).toBeVisible();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/web test -- agent-panel workspace-shell workspace-preferences`

Expected: FAIL，因为 AgentPanel 尚未组装。

- [ ] **Step 3: 实现 AgentPanel orchestration**

AgentPanel 加载 sessions/settings，创建或恢复当前 session，建立 WebSocket，使用 reducer 渲染 composer/messages/tools/sidebar/settings。Runtime unavailable 时显示可重试状态，不使 workspace shell 崩溃；非 Agent panel 仍可切换和操作。

- [ ] **Step 4: 接入 WorkspaceShell**

在本阶段保留 `TutorPanel` import 作为切换前兼容，但加入 `AgentPanel` 可编译接线和新的 file/citation callback。沿用当前未提交改动中的跨 space/knowledge base 导航：先切换 space，等待知识库列表加载，再选择 knowledge base 和 Vault file；ACL 失败显示“资源不可用”，不泄露 foreign path。

- [ ] **Step 5: 运行组件测试**

Run: `pnpm --dir apps/web test -- agent-panel workspace-shell workspace-preferences`

Expected: PASS，包括 send/stream/stop/reconnect、跨知识库文件导航、Runtime 503 和移动端 drawer。

- [ ] **Step 6: 运行 Web 全量门禁**

Run: `pnpm --dir apps/web test && pnpm --dir apps/web exec tsc --noEmit && pnpm --dir apps/web lint && pnpm --dir apps/web build`

Expected: 全部通过；Next build 不出现 WebSocket Route Handler 假支持。

- [ ] **Step 7: 提交**

```powershell
git add apps/web/src/components/workspace apps/web/src/lib apps/web/src/app/api/[...path]/route.ts
git commit -m "feat: integrate agent workspace panel"
```
