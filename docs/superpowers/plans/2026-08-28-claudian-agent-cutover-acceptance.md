# Claudian Agent Cutover and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将生产工作区一次性切换到完整 AgentPanel，收束上一版有界 RAG/Wikipedia 改动，验证 30 条验收标准并形成可回滚发布证据。

**Architecture:** 切换只发生在 Runtime、控制面、Vault、Web、语义索引和迁移全部通过后；旧 Tutor 数据/API 保持只读兼容，但固定 RAG 和 Wikipedia 不再进入新交互主链。发布使用功能可用性、ACL、安全、故障隔离、跨平台和许可证门禁，不以删除旧数据作为完成条件。

**Tech Stack:** FastAPI/Pytest/Ruff, Node.js 24/Jest, Next.js 16.3/Vitest/TypeScript/ESLint, Docker Compose, PowerShell, PostgreSQL

---

### Task 1: 将 WorkspaceShell 正式切换到 AgentPanel

**Files:**
- Modify: `apps/web/src/components/workspace/workspace-shell.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.test.tsx`
- Delete: `apps/web/src/components/workspace/tutor-panel.tsx`
- Delete: `apps/web/src/components/workspace/tutor-panel.test.tsx`
- Modify: `apps/web/src/lib/tutor-api.ts`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`
- Create: `apps/web/src/components/workspace/agent-cutover.test.tsx`

- [ ] **Step 1: 写切换失败测试**

```tsx
it("mounts AgentPanel as the only AI workspace experience", async () => {
  render(<WorkspaceShell spaces={spaces} />);
  await user.click(screen.getByRole("button", { name: "AI 助教" }));
  expect(await screen.findByTestId("agent-panel")).toBeVisible();
  expect(screen.queryByTestId("tutor-panel")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "MCP" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Skills" })).toBeVisible();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/web test -- agent-cutover workspace-shell`

Expected: FAIL，因为 WorkspaceShell 仍引用 TutorPanel。

- [ ] **Step 3: 替换组件**

删除 `TutorPanel` import/render 和仅供固定 RAG citation 使用的状态；直接渲染 `AgentPanel`，传入当前 space/knowledge base、全部可读知识库投影、文件导航 callback 和 drawer state。保留当前跨 space citation/file 导航改进，不增加长期模式开关。

- [ ] **Step 4: 收缩 tutor-api.ts**

只保留读取旧 Tutor conversations/messages 所需类型和函数，文件头标明 legacy read-only；新 session、stream、citation、Web、tool 和设置全部使用 `agent-api.ts`。删除任何新代码对 Tutor send endpoint 的调用。

- [ ] **Step 5: 删除旧组件并运行测试**

Run: `pnpm --dir apps/web test -- agent-cutover agent-panel workspace-shell`

Expected: PASS；项目中 `TutorPanel` 搜索结果为 0，legacy history 仍可从 Agent session sidebar 打开。

- [ ] **Step 6: 提交**

```powershell
git add -A apps/web/src/components/workspace apps/web/src/lib/tutor-api.ts
git commit -m "feat: cut workspace over to AgentPanel"
```

### Task 2: 收束受限 Tutor 后端而保留只读历史

**Files:**
- Modify: `apps/api/src/tutor_api/tutor/router.py`
- Modify: `apps/api/src/tutor_api/tutor/schemas.py`
- Modify: `apps/api/src/tutor_api/tutor/service.py`
- Delete: `apps/api/src/tutor_api/tutor/web_search.py`
- Delete: `apps/api/tests/test_tutor_web_search.py`
- Modify: `apps/api/tests/test_tutor.py`
- Modify: `apps/api/src/tutor_api/main.py`

- [ ] **Step 1: 写主链隔离失败测试**

```python
def test_agent_send_never_calls_legacy_tutor_adapter(client, agent_runtime, legacy_tutor_adapter):
    response = client.post("/api/v1/agent/sessions", json=session_payload())
    session_id = response.json()["id"]
    assert client.post(f"/api/v1/agent/sessions/{session_id}/turns", json={"message": "联合知识库和网页回答"}).status_code == 202
    legacy_tutor_adapter.assert_not_called()


def test_legacy_history_remains_readable_but_send_is_gone(client, legacy_conversation):
    assert client.get(f"/api/v1/tutor/conversations/{legacy_conversation.id}").status_code == 200
    assert client.post("/api/v1/tutor/messages", json={"content": "new"}).status_code in {404, 410}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_tutor.py apps/api/tests/test_agent_api.py -q`

Expected: FAIL，因为旧 send 或固定 Web 主链仍可达。

- [ ] **Step 3: 保留只读 legacy router**

Tutor router 仅提供旧 conversation list/get 和 citation 投影；mutation endpoint 返回 410 `{code:"legacy_tutor_retired",replacement:"/api/v1/agent"}` 或从 router 移除。旧 `TutorConversation`/`TutorMessage` 模型和 0015 migration 保留。

- [ ] **Step 4: 删除固定 Wikipedia adapter**

确认 Runtime `web-tools.test.ts` 已覆盖公共 Web、多轮 fetch、SSRF 和长 sidecar 后，删除两个未跟踪 Wikipedia 文件；从 `main.py` 移除 `tutor_web_search_adapter` 构造和 app state。`Tutor service` 删除固定 evidence/history/count 主链逻辑，只留下 legacy serializer/reader。

- [ ] **Step 5: 运行后端测试**

Run: `python -m pytest apps/api/tests/test_tutor.py apps/api/tests/test_agent_api.py apps/api/tests/test_agent_capability.py -q`

Expected: PASS；legacy history 可读，新 turn 只到 Agent Runtime，固定 Wikipedia 代码不存在。

- [ ] **Step 6: 提交**

```powershell
git add -A apps/api/src/tutor_api/tutor apps/api/src/tutor_api/main.py apps/api/tests
git commit -m "refactor: retire bounded tutor execution path"
```

### Task 3: 清除固定限制配置和文档表述

**Files:**
- Modify: `.env.example`
- Modify: `compose.yaml`
- Modify: `README.md`
- Modify: `apps/api/src/tutor_api/core/config.py`
- Modify: `apps/api/tests/test_config.py`
- Modify: `apps/api/tests/test_compose_security.py`
- Create: `apps/api/tests/test_agent_policy_regression.py`

- [ ] **Step 1: 写限制回归失败测试**

```python
@pytest.mark.parametrize("forbidden", [
    "无教材证据时禁止", "仅依据教材", "TUTOR_PROMPT_MAX_CHARACTERS",
    "TUTOR_HISTORY_MESSAGES", "TUTOR_KNOWLEDGE_SOURCES", "TUTOR_WEB_SEARCH_MAX_RESULTS",
])
def test_removed_restrictions_do_not_exist_in_active_configuration_or_prompts(forbidden):
    active_text = read_active_agent_sources_and_templates()
    assert forbidden not in active_text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_agent_policy_regression.py -q`

Expected: FAIL，当前未提交配置和 README 仍描述有界 Tutor。

- [ ] **Step 3: 更新配置和部署文本**

删除问题字符、历史条数、本地证据数、知识库数、网页结果数和固定摘录长度变量。保留高容量/安全资源配置：1,000,000 context 目标、inline event bytes、sidecar storage、per-request timeout、并发/backpressure、disk watermark、session idle/warm duration；值可调且失败显式，不把内容静默裁成固定 N 条。

- [ ] **Step 4: 更新 README**

说明 Vault + 模型知识 + 公共 Web 的组合、宿主机 yolo 风险、普通文件工具 ACL、Bash 宿主权限、MCP/Skills/subagents、迁移/回滚、Runtime 故障隔离和许可证后端位置。不得在前端截图或设置说明中展示 MIT/commit 标签。

- [ ] **Step 5: 运行配置回归**

Run: `python -m pytest apps/api/tests/test_agent_policy_regression.py apps/api/tests/test_config.py apps/api/tests/test_compose_security.py -q`

Expected: PASS。

Run: `rg -n "无教材证据时禁止|仅依据教材|TUTOR_PROMPT_MAX_CHARACTERS|TUTOR_HISTORY_MESSAGES|TUTOR_KNOWLEDGE_SOURCES|TUTOR_WEB_SEARCH_MAX_RESULTS" . -g '!docs/superpowers/**' -g '!artifacts/**' -g '!.git/**'`

Expected: 无 active source/config 命中；legacy migration artifacts 可排除。

- [ ] **Step 6: 提交**

```powershell
git add .env.example compose.yaml README.md apps/api/src/tutor_api/core/config.py apps/api/tests
git commit -m "docs: replace bounded tutor policy with workspace agent policy"
```

### Task 4: 执行 30 条产品验收和安全矩阵

**Files:**
- Create: `apps/api/tests/test_agent_acceptance.py`
- Create: `apps/agent-runtime/tests/acceptance.test.ts`
- Create: `apps/web/src/components/workspace/agent-acceptance.test.tsx`
- Create: `artifacts/agent-migration/acceptance-report.md`

- [ ] **Step 1: 写无固定数量限制的自动验收**

```ts
it("processes a large workspace and repeated tools without product count caps", async () => {
  const vault = await harness.createVault({ markdownFiles: 120, conceptsPerFile: 12 });
  const session = await harness.startSession(vault);
  for (let index = 0; index < 30; index += 1) await session.fetchPublic(`https://public.example/${index}`);
  expect((await session.listReadableFiles()).length).toBe(120);
  expect(session.events.filter((event) => event.event_type === "tool_completed").length).toBeGreaterThanOrEqual(30);
});
```

- [ ] **Step 2: 写 ACL/路径自动验收**

```python
def test_agent_cannot_read_foreign_user_or_unjoined_classroom(acceptance_harness):
    result = acceptance_harness.run_file_tool_as("learner", ["foreign-personal", "unjoined-classroom"])
    assert result == ["capability_denied", "capability_denied"]
    assert acceptance_harness.audit.rejections == 2
```

- [ ] **Step 3: 运行三层验收测试**

Run: `pnpm --dir apps/agent-runtime test -- acceptance && python -m pytest apps/api/tests/test_agent_acceptance.py -q && pnpm --dir apps/web test -- agent-acceptance`

Expected: PASS，覆盖设计验收 1–21、24–28。

- [ ] **Step 4: 执行故障和迁移验收**

按顺序验证：Runtime kill/restart、MCP kill、public Web timeout、database transient failure、watcher event storm、planner failure、disk-low simulation、WebSocket refresh replay、Vault conflict、migration hash。每项在 `acceptance-report.md` 记录命令、UTC/本地时间、结果、日志路径和关联 ID。

- [ ] **Step 5: 验证许可证不可见性**

Run: `rg -n "d190786d11cc0b067475dcffbf8c334ee565d208|Claudian MIT|Copyright \(c\) 2025" apps/web/.next apps/web/src`

Expected: 无前端命中。

Run: `rg -n "d190786d11cc0b067475dcffbf8c334ee565d208|Copyright \(c\) 2025" apps/agent-runtime/UPSTREAM.md apps/agent-runtime/THIRD_PARTY_NOTICES.md apps/agent-runtime/licenses apps/agent-runtime/dist`

Expected: 源码/后端/发行包存在固定 commit 和许可证声明。

- [ ] **Step 6: 填写验收报告**

`acceptance-report.md` 使用 1–30 编号逐条写 `PASS`、对应自动测试、人工 smoke 和证据路径；第 29 条附 pre-implementation status/diff/hash 与最终处置表；第 30 条附 active route/component 搜索结果。

- [ ] **Step 7: 提交**

```powershell
git add apps/api/tests/test_agent_acceptance.py apps/agent-runtime/tests/acceptance.test.ts apps/web/src/components/workspace/agent-acceptance.test.tsx artifacts/agent-migration/acceptance-report.md
git commit -m "test: verify workspace agent acceptance matrix"
```

### Task 5: 运行全量回归、回滚演练和最终发布门禁

**Files:**
- Modify: `.github/workflows/quality.yml`
- Create: `artifacts/agent-migration/release-report.md`
- Create: `artifacts/agent-migration/rollback-report.md`

- [ ] **Step 1: 运行 API 全量门禁**

Run: `python -m pytest apps/api/tests --cov=apps/api/src/tutor_api --cov-fail-under=100`

Expected: 全部通过、覆盖率 100%，既有 skip 不增加。

Run: `python -m ruff check apps/api/src apps/api/tests apps/api/migrations`

Expected: `All checks passed!`

- [ ] **Step 2: 运行 Runtime 全量门禁**

Run: `pnpm --dir apps/agent-runtime test && pnpm --dir apps/agent-runtime typecheck && pnpm --dir apps/agent-runtime lint && pnpm --dir apps/agent-runtime test:conformance && pnpm --dir apps/agent-runtime package`

Expected: 全部退出码 0，无 open handles，package hash/provenance 验证通过。

- [ ] **Step 3: 运行 Web 全量门禁**

Run: `pnpm --dir apps/web test && pnpm --dir apps/web exec tsc --noEmit && pnpm --dir apps/web lint && pnpm --dir apps/web build`

Expected: 全部通过，AgentPanel 是唯一 active AI workspace component。

- [ ] **Step 4: 运行 Docker 和非 Agent 故障隔离**

Run: `docker compose --env-file .env config && docker compose --env-file .env up --build -d`

Expected: API/worker/Web/数据库服务健康。停止 Runtime 后验证：注册/登录、`/api/v1/health`、知识库 list/read、题库 list/attempt 成功；Agent create/send 返回可恢复 503，恢复 Runtime 后 session 可继续。

- [ ] **Step 5: 演练回滚**

执行 migration CLI `rollback`：旧 active index 与 legacy read path 恢复；AgentPanel 显示维护状态；Vault 中切换后新建文件仍存在且 manifest 可导回；随后重新 cutover 并验证 hash/cursor/session。把命令和结果写入 `rollback-report.md`。

- [ ] **Step 6: 生成 release report**

`release-report.md` 记录 git commit、Claudian commit、Node/Python/pnpm 版本、migration head、file count/bytes/hash、各测试命令结果、Windows/Linux smoke、30 条验收报告链接、已知运维风险和回滚命令。不得写 secret。

- [ ] **Step 7: 检查工作树处置完整性**

Run: `git status --short && git diff --check`

Expected: 无意外未跟踪实现文件；原 19 个修改和 2 个未跟踪 Tutor 文件均已按总计划处置；`git diff --check` 无 whitespace error。

- [ ] **Step 8: 提交最终发布证据**

```powershell
git add .github/workflows/quality.yml artifacts/agent-migration
git commit -m "chore: certify Claudian workspace agent cutover"
```
