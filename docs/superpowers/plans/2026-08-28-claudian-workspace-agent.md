# Claudian Workspace Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有受限 Tutor 主链替换为 Claudian 派生的完整工作区 Agent，同时保留现有认证、ACL、知识库、题库和旧 Tutor 数据。

**Architecture:** 以 FastAPI 作为认证、授权、事件持久化、Vault 投影和索引控制面，以宿主机 Node.js 24 `apps/agent-runtime` 作为 Claude Agent SDK 执行面，以永久 Vault Markdown 作为正文事实来源。实现按五个可独立验证的详细计划推进，最终一次性切换 `TutorPanel` 到 `AgentPanel`，不把固定 RAG 或固定网页搜索作为长期产品行为。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/pgvector, Node.js 24, TypeScript, pnpm 11, Claude Agent SDK 0.3.226, MCP SDK ~1.30.0, Next.js 16.3, React 19.2, Vitest, Jest

---

## 计划集合和强制顺序

1. `docs/superpowers/plans/2026-08-28-claudian-agent-runtime.md`
2. `docs/superpowers/plans/2026-08-28-agent-control-plane-vault.md`
3. `docs/superpowers/plans/2026-08-28-agent-web-workspace.md`
4. `docs/superpowers/plans/2026-08-28-agent-index-migration-deployment.md`
5. `docs/superpowers/plans/2026-08-28-claudian-agent-cutover-acceptance.md`

每个详细计划必须在自己的测试门禁通过后再进入下一个计划。开发期间允许 Agent API 和旧 Tutor API 并存，但前端切换只在第五个计划执行。

## 锁定的文件边界

### 上游派生和协议

- Create: `apps/agent-runtime/**` — 宿主机 Node.js 24 运行时、Claudian 派生代码、provider、工具、MCP、Skills、session 和 sidecar。
- Create: `packages/agent-protocol/src/**` — FastAPI、Runtime 和 Web 共用的事件、请求与 capability JSON Schema/TypeScript 类型。
- Create: `scripts/vendor-claudian.ps1` — 固定 commit 校验、文件复制、hash 清单生成。
- Create: `apps/agent-runtime/UPSTREAM.md`
- Create: `apps/agent-runtime/PATCHES.md`
- Create: `apps/agent-runtime/FILES.json`
- Create: `apps/agent-runtime/THIRD_PARTY_NOTICES.md`
- Create: `apps/agent-runtime/licenses/claudian-MIT.txt`

### FastAPI 控制面

- Create: `apps/api/src/tutor_api/agent/models.py`
- Create: `apps/api/src/tutor_api/agent/schemas.py`
- Create: `apps/api/src/tutor_api/agent/capability.py`
- Create: `apps/api/src/tutor_api/agent/runtime_client.py`
- Create: `apps/api/src/tutor_api/agent/event_store.py`
- Create: `apps/api/src/tutor_api/agent/service.py`
- Create: `apps/api/src/tutor_api/agent/router.py`
- Create: `apps/api/src/tutor_api/agent/legacy.py`
- Create: `apps/api/src/tutor_api/vault/models.py`
- Create: `apps/api/src/tutor_api/vault/storage.py`
- Create: `apps/api/src/tutor_api/vault/sync.py`
- Create: `apps/api/src/tutor_api/vault/service.py`
- Create: `apps/api/src/tutor_api/vault/router.py`
- Create: `apps/api/src/tutor_api/vault/migration.py`
- Create: `apps/api/migrations/versions/0016_agent_workspace.py`
- Modify: `apps/api/src/tutor_api/knowledge/models.py` — 只增加 Vault、change-set 和 planner 关联字段。
- Modify: `apps/api/src/tutor_api/knowledge/indexing.py` — 接受 Vault snapshot 和 AI planner 输出，保留原子激活。
- Modify: `apps/api/src/tutor_api/knowledge/worker.py`
- Modify: `apps/api/src/tutor_api/worker_main.py`
- Modify: `apps/api/src/tutor_api/core/config.py`
- Modify: `apps/api/src/tutor_api/main.py`
- Modify: `apps/api/migrations/env.py`

### Web 工作区

- Create: `apps/web/src/lib/agent-api.ts`
- Create: `apps/web/src/lib/agent-events.ts`
- Create: `apps/web/src/components/workspace/agent-panel.tsx`
- Create: `apps/web/src/components/workspace/agent-composer.tsx`
- Create: `apps/web/src/components/workspace/agent-message-list.tsx`
- Create: `apps/web/src/components/workspace/agent-tool-card.tsx`
- Create: `apps/web/src/components/workspace/agent-session-sidebar.tsx`
- Create: `apps/web/src/components/workspace/agent-settings.tsx`
- Create: `apps/web/src/components/workspace/agent-panel.module.css`
- Modify: `apps/web/src/components/workspace/workspace-shell.tsx`
- Modify: `apps/web/src/components/workspace/workspace-shell.module.css`
- Modify: `apps/web/src/app/api/[...path]/route.ts` — 仅继续代理 HTTP；WebSocket 使用公开 FastAPI URL，不伪装成 Next Route Handler WebSocket。

### 发布和运维

- Modify: `pnpm-workspace.yaml`
- Modify: `package.json`
- Modify: `pnpm-lock.yaml`
- Modify: `.env.example`
- Modify: `compose.yaml`
- Modify: `README.md`
- Modify: `.github/workflows/quality.yml`
- Create: `scripts/install-agent-runtime.ps1`
- Create: `scripts/start-agent-runtime.ps1`
- Create: `scripts/smoke-agent-runtime.ps1`
- Create: `scripts/smoke-agent-runtime.sh`

## 当前未提交改动逐文件处置

| 文件 | 处置 | 执行阶段 |
|---|---|---|
| `.env.example` | 保留文件，不保留 Tutor 固定数量配置；迁移为 Runtime/Vault/Agent 配置 | 部署计划 |
| `README.md` | 替换“有界 Wikipedia Tutor”说明为完整 Agent 架构、风险和运维说明 | 部署计划 |
| `apps/api/src/tutor_api/core/config.py` | 保留 Faro context 改进；移除 Tutor 数量上限字段；加入 Agent/Vault 配置 | 控制面计划 |
| `apps/api/src/tutor_api/knowledge/access.py` | 保留并测试 `list_readable_knowledge_bases`，作为 capability 授权来源 | 控制面计划 |
| `apps/api/src/tutor_api/llm/faro.py` | 保留可复用的大 context 预算逻辑，转入 Provider Registry 测试范围 | Runtime/控制面计划 |
| `apps/api/src/tutor_api/main.py` | 保留现有 adapter 兼容性；新增 Agent/Vault router，Runtime 不可用不得阻塞 lifespan | 控制面计划 |
| `apps/api/src/tutor_api/tutor/router.py` | 保留 legacy history 只读 API；不再作为新 Agent 主链 | 切换计划 |
| `apps/api/src/tutor_api/tutor/schemas.py` | 保留旧数据读取 schema；不向 Agent 协议扩张 | 切换计划 |
| `apps/api/src/tutor_api/tutor/service.py` | 迁移 ACL/跨知识库测试意图；撤回固定证据和 Wikipedia 主链改动 | 切换计划 |
| `apps/api/src/tutor_api/tutor/web_search.py` | 删除未跟踪固定 Wikipedia adapter；功能由 Runtime WebSearch/WebFetch 取代 | Runtime 计划 |
| `apps/api/tests/test_tutor_web_search.py` | 删除未跟踪固定 Wikipedia 测试；SSRF/多轮网页测试迁移到 Runtime | Runtime 计划 |
| `apps/api/tests/test_compose_security.py` | 保留安全断言并改为 Runtime loopback、secret、Vault mount 和非 Agent 隔离 | 部署计划 |
| `apps/api/tests/test_config.py` | 移除固定 Tutor 上限断言，加入百万上下文和 Runtime 配置断言 | 控制面计划 |
| `apps/api/tests/test_llm_faro.py` | 保留 context 预算回归 | 控制面计划 |
| `apps/api/tests/test_tutor.py` | 保留 legacy 所有权测试；将 unrestricted 目标迁移到 Agent API 测试 | 切换计划 |
| `apps/web/src/lib/tutor-api.ts` | 保留 legacy history 类型；新交互改用 `agent-api.ts` | Web 计划 |
| `apps/web/src/components/workspace/tutor-panel.tsx` | 最终删除并由 `agent-panel.tsx` 替换 | 切换计划 |
| `apps/web/src/components/workspace/tutor-panel.test.tsx` | 将可复用的 citation/navigation 意图迁移到 AgentPanel 测试后删除 | Web/切换计划 |
| `apps/web/src/components/workspace/workspace-shell.tsx` | 保留跨空间 citation 导航改进并改接 Agent 事件 | Web 计划 |
| `apps/web/src/components/workspace/workspace-shell.test.tsx` | 保留跨知识库导航回归并更名为 Agent 行为 | Web 计划 |
| `compose.yaml` | 移除 Tutor 固定限制；增加独立宿主机 Runtime 配置说明和可选开发服务 | 部署计划 |

任何任务执行前先运行 `git status --short`，确认这些改动仍然存在；不得使用 `git reset --hard`、`git checkout -- .` 或覆盖式复制整个工作树。

### Task 1: 记录可恢复基线和改动清单

**Files:**
- Create: `artifacts/agent-migration/pre-implementation-status.txt`
- Create: `artifacts/agent-migration/pre-implementation-diff.patch`
- Create: `artifacts/agent-migration/pre-implementation-untracked.sha256`

- [ ] **Step 1: 捕获当前状态**

```powershell
New-Item -ItemType Directory -Force artifacts/agent-migration | Out-Null
git status --short | Set-Content artifacts/agent-migration/pre-implementation-status.txt
git diff --binary | Set-Content artifacts/agent-migration/pre-implementation-diff.patch
Get-FileHash apps/api/src/tutor_api/tutor/web_search.py,apps/api/tests/test_tutor_web_search.py -Algorithm SHA256 |
  Format-Table -HideTableHeaders Path,Hash |
  Out-String |
  Set-Content artifacts/agent-migration/pre-implementation-untracked.sha256
```

- [ ] **Step 2: 验证基线包含全部既有改动**

Run: `Get-Content artifacts/agent-migration/pre-implementation-status.txt`

Expected: 包含 19 个 `M` 条目、2 个 Tutor `??` 条目，以及已确认的 spec/plan 文档；文件内容非空。

- [ ] **Step 3: 提交仅包含基线工件和计划**

```powershell
git add artifacts/agent-migration docs/superpowers/specs docs/superpowers/plans
git commit -m "docs: lock workspace agent migration baseline"
```

### Task 2: 按顺序执行五个详细计划

**Files:**
- Modify: 本计划“计划集合和强制顺序”列出的所有文件
- Test: 每个详细计划列出的精确测试文件

- [ ] **Step 1: 执行 Runtime 计划**

Run: `pnpm --dir apps/agent-runtime test && pnpm --dir apps/agent-runtime typecheck && pnpm --dir apps/agent-runtime lint`

Expected: Runtime 单元、协议、Claudian conformance、路径、SSRF、MCP、Skills、subagent 和 session 恢复测试全部通过。

- [ ] **Step 2: 执行 FastAPI 控制面和 Vault 计划**

Run: `python -m pytest apps/api/tests/test_agent_models.py apps/api/tests/test_agent_capability.py apps/api/tests/test_agent_api.py apps/api/tests/test_vault_sync.py -q`

Expected: Agent 模型、ACL capability、事件 replay、Vault CRUD/冲突/同步测试全部通过。

- [ ] **Step 3: 执行 Web 工作区计划**

Run: `pnpm --dir apps/web test -- agent-panel workspace-shell && pnpm --dir apps/web exec tsc --noEmit`

Expected: AgentPanel、session 恢复、tool card、设置和跨知识库导航测试通过，TypeScript 无错误。

- [ ] **Step 4: 执行索引、迁移和部署计划**

Run: `python -m pytest apps/api/tests/test_semantic_index_plan.py apps/api/tests/test_vault_migration.py apps/api/tests/test_compose_security.py -q`

Expected: AI 计划校验、旧索引保留、hash 一致迁移、部署隔离测试通过。

- [ ] **Step 5: 执行切换和验收计划**

Run: `powershell -ExecutionPolicy Bypass -File scripts/smoke-agent-runtime.ps1`

Expected: Windows Node 24 Runtime、FastAPI、Web、Vault、命令、Web、MCP、Skills、subagent 和恢复 smoke 全部成功。

### Task 3: 运行全量发布门禁

**Files:**
- Modify: `.github/workflows/quality.yml`
- Test: `apps/api/tests/**`
- Test: `apps/web/src/**/*.test.ts`
- Test: `apps/web/src/**/*.test.tsx`
- Test: `apps/agent-runtime/tests/**`

- [ ] **Step 1: 运行 API 全量测试和覆盖率**

Run: `python -m pytest apps/api/tests --cov=apps/api/src/tutor_api --cov-fail-under=100`

Expected: 既有 API 测试与新增 Agent/Vault 测试全部通过，覆盖率 100%；已有平台相关 skip 数量不增加。

- [ ] **Step 2: 运行 Python 静态检查**

Run: `python -m ruff check apps/api/src apps/api/tests apps/api/migrations`

Expected: `All checks passed!`

- [ ] **Step 3: 运行 Runtime 全量门禁**

Run: `pnpm --dir apps/agent-runtime test && pnpm --dir apps/agent-runtime typecheck && pnpm --dir apps/agent-runtime lint && pnpm --dir apps/agent-runtime test:conformance`

Expected: 全部命令退出码 0，upstream commit/hash 检查通过。

- [ ] **Step 4: 运行 Web 全量门禁**

Run: `pnpm --dir apps/web test && pnpm --dir apps/web exec tsc --noEmit && pnpm --dir apps/web lint && pnpm --dir apps/web build`

Expected: Vitest、TypeScript、ESLint 和 Next.js 16.3 production build 全部通过。

- [ ] **Step 5: 运行 compose 和故障隔离 smoke**

Run: `docker compose --env-file .env config && docker compose --env-file .env up --build -d`

Expected: PostgreSQL、Redis、MinIO、API、worker、Web 健康；停止 Runtime 后 `/api/v1/health`、登录、知识库浏览和题库仍成功，Agent API 返回结构化 `runtime_unavailable`。

- [ ] **Step 6: 提交发布门禁**

```powershell
git add .github/workflows/quality.yml artifacts/agent-migration
git commit -m "test: enforce workspace agent release gates"
```

## 总体验收追踪

- 设计验收 1–7：Runtime 请求不包含固定问题、历史、证据、网页或工具累计上限；由 conformance 和配置测试覆盖。
- 验收 8–9、24：FastAPI capability + Runtime path policy + 跨租户集成测试覆盖。
- 验收 10–11、16–17：Claude SDK、Web、Bash、MCP、Skills 和 subagent Runtime 测试覆盖。
- 验收 12–15、25：Vault CRUD、change set、watcher、索引原子激活和迁移 hash 测试覆盖。
- 验收 18–20：session/event replay、Runtime 重启、Stop/Resume/Rewind/Fork 和 sidecar 测试覆盖。
- 验收 21：Provider context capability 与百万上下文配置测试覆盖。
- 验收 22–23：全量回归和 Runtime 故障隔离 smoke 覆盖。
- 验收 26–28：上游 conformance、固定 commit、许可证清单和前端不可见测试覆盖。
- 验收 29：基线工件和逐文件处置表覆盖。
- 验收 30：切换门禁禁止 `TutorPanel` 或固定 Wikipedia 作为新主链。

## 逐条规格覆盖自审

| 验收 | 实施任务 | 自动/人工证据 |
|---:|---|---|
| 1 | Runtime Task 3；Cutover Task 3 | active prompt/config 文本扫描 |
| 2 | Runtime Task 3；Cutover Task 3 | system prompt conformance |
| 3 | Web Task 2；Cutover Task 4 | >500 字 composer/acceptance test |
| 4 | Runtime Task 3；Web Task 1 | session JSONL + event replay test |
| 5 | Runtime Task 1/3；Index Task 2 | protocol 字段扫描、250+ chunks test |
| 6 | Runtime Task 5/6；Cutover Task 4 | 120 files、30 web/tool calls test |
| 7 | Runtime Task 3/5；Web Task 3 | sidecar full-content test |
| 8 | Control Plane Task 2 | all-readable-KB capability test |
| 9 | Runtime Task 4；Control Plane Task 2 | Windows/Linux path + ACL test |
| 10 | Runtime Task 3/5 | Vault + model + public Web prompt/tool test |
| 11 | Runtime Task 5 | 25+ sequential public fetches test |
| 12 | Runtime Task 4；Control Plane Task 5 | Vault CRUD/move/delete test |
| 13 | Control Plane Task 6 | external file auto-enrollment test |
| 14 | Index Task 1/2 | chunks/concepts/terms/tags/links test |
| 15 | Index Task 2 | planner/index failure keeps active index test |
| 16 | Runtime Task 5 | PowerShell/Bash process-tree smoke |
| 17 | Runtime Task 6 | MCP transports、Skills、subagent tests |
| 18 | Runtime Task 3；Control Plane Task 4 | browser refresh/runtime restart replay test |
| 19 | Runtime Task 3；Control Plane Task 4；Web Task 4 | Stop/Resume/Rewind/Fork tests |
| 20 | Runtime Task 3；Web Task 3 | sidecar hash/download/preview test |
| 21 | Control Plane Task 2；Web Task 4 | 1,000,000 context config/capability test |
| 22 | Master Task 3 | API/Runtime/Web full regression |
| 23 | Control Plane Task 3/4；Cutover Task 5 | Runtime-down non-Agent smoke |
| 24 | Control Plane Task 2；Cutover Task 4 | cross-user/classroom/KB acceptance |
| 25 | Index Task 3 | inventory count/bytes/hash verification |
| 26 | Runtime Task 2；Index Task 6 | Claudian conformance CI |
| 27 | Runtime Task 2 | UPSTREAM/FILES/license package checks |
| 28 | Runtime Task 2；Cutover Task 4 | backend present + frontend absent scans |
| 29 | Master Task 1；Cutover Task 5 | baseline patch/hash + final disposition |
| 30 | Cutover Task 1/2/3 | active TutorPanel/Wikipedia/limit scan |

自审结论：设计文档第 1–20 章和验收 1–30 均有明确实施任务和验证证据；未发现缺项。
