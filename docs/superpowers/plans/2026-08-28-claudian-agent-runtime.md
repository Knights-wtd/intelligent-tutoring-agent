# Claudian Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可在 Windows/Linux 宿主机运行的 Node.js 24 Agent Runtime，最大程度复用固定 Claudian commit，并提供 Claude SDK、文件、Bash、Web、MCP、Skills、子智能体和可恢复 session。

**Architecture:** Runtime 仅绑定 loopback，通过版本化 HTTP/NDJSON 协议接受 FastAPI 签发的 capability；provider-neutral contracts 与 Claudian 派生层分开，Obsidian API 只在 HostVaultAdapter 边界替换。所有累计调用和证据数量不设产品级上限，大输出落 sidecar，真实限制来自模型能力、磁盘、超时和可观测的 backpressure。

**Tech Stack:** Node.js 24, TypeScript 6, pnpm 11, Jest 30, Claude Agent SDK 0.3.226, MCP SDK ~1.30.0, ws 8.21, Claudian commit d190786d11cc0b067475dcffbf8c334ee565d208

---

### Task 1: 建立 workspace 协议包和 Runtime 脚手架

**Files:**
- Create: `packages/agent-protocol/package.json`
- Create: `packages/agent-protocol/tsconfig.json`
- Create: `packages/agent-protocol/src/index.ts`
- Create: `packages/agent-protocol/src/events.ts`
- Create: `packages/agent-protocol/src/runtime.ts`
- Create: `packages/agent-protocol/src/capability.ts`
- Create: `packages/agent-protocol/tests/contracts.test.ts`
- Create: `apps/agent-runtime/package.json`
- Create: `apps/agent-runtime/tsconfig.json`
- Create: `apps/agent-runtime/jest.config.mjs`
- Create: `apps/agent-runtime/src/config.ts`
- Create: `apps/agent-runtime/src/server.ts`
- Create: `apps/agent-runtime/tests/health.test.ts`
- Modify: `pnpm-workspace.yaml`
- Modify: `package.json`

- [ ] **Step 1: 写协议失败测试**

```ts
import { parseRuntimeEvent } from "../src/events";

it("accepts a monotonic replayable event envelope", () => {
  expect(parseRuntimeEvent({
    event_id: "7d62a87e-b89d-49d7-af1c-7accabc32324",
    session_id: "6bf39da0-d73f-49da-a471-95ca48bb48fa",
    turn_id: "35b7cd1e-2a23-4aa3-a704-9ba1fc4f9265",
    sequence: 1,
    event_type: "model_text_delta",
    timestamp: "2026-08-28T00:00:00Z",
    payload: { text: "hello" },
    idempotency_key: "turn-1-sequence-1",
  }).sequence).toBe(1);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir packages/agent-protocol test`

Expected: FAIL，因为 package 和 `parseRuntimeEvent` 尚不存在。

- [ ] **Step 3: 实现共享类型和严格解析器**

```ts
export type RuntimeEventType =
  | "turn_started" | "user_message" | "model_text_delta" | "thinking_delta"
  | "tool_started" | "tool_progress" | "tool_completed" | "tool_failed"
  | "subagent_started" | "subagent_completed" | "usage" | "compaction"
  | "session_state" | "index_state" | "error";

export interface RuntimeEventEnvelope {
  event_id: string;
  session_id: string;
  turn_id: string | null;
  sequence: number;
  event_type: RuntimeEventType;
  timestamp: string;
  payload: Record<string, unknown>;
  idempotency_key: string;
}

export function parseRuntimeEvent(value: unknown): RuntimeEventEnvelope {
  if (!value || typeof value !== "object") throw new TypeError("event must be an object");
  const event = value as Record<string, unknown>;
  if (!Number.isSafeInteger(event.sequence) || Number(event.sequence) < 1) {
    throw new TypeError("event.sequence must be a positive safe integer");
  }
  for (const key of ["event_id", "session_id", "event_type", "timestamp", "idempotency_key"] as const) {
    if (typeof event[key] !== "string" || event[key].length === 0) throw new TypeError(`event.${key} is required`);
  }
  if (!event.payload || typeof event.payload !== "object" || Array.isArray(event.payload)) {
    throw new TypeError("event.payload must be an object");
  }
  return event as unknown as RuntimeEventEnvelope;
}
```

```ts
export type RuntimeInputBlock =
  | { readonly type: "text"; readonly text: string }
  | { readonly type: "image"; readonly media_type: string; readonly data: string };

export interface RuntimeStartRequest {
  session_id: string;
  turn_id: string;
  input: readonly RuntimeInputBlock[];
  workspace_roots: readonly string[];
  provider: string;
  model: string;
  permission_mode: "bypassPermissions";
  capability: string;
  callback_url: string;
  idempotency_key: string;
}

export interface RuntimeStartResponse {
  execution_id: string;
  native_session_id: string;
  accepted_sequence: number;
}
```

协议不得含 `maxEvidence`、`maxHistoryMessages`、`maxWebResults` 或累计工具调用上限。

- [ ] **Step 4: 实现 loopback health server**

```ts
export interface RuntimeConfig {
  host: "127.0.0.1" | "::1";
  port: number;
  apiToken: string;
  sidecarRoot: string;
  maxContextTokens: number;
}

export const RUNTIME_PROTOCOL_VERSION = "1.0";
```

`GET /v1/health` 返回 `{status:"ok", protocol_version:"1.0", upstream_commit, node_version}`；除 health 外所有路径要求 `Authorization: Bearer <AGENT_RUNTIME_TOKEN>`。

- [ ] **Step 5: 运行测试和类型检查**

Run: `pnpm install && pnpm --dir packages/agent-protocol test && pnpm --dir apps/agent-runtime test && pnpm --dir apps/agent-runtime typecheck`

Expected: PASS；Node 22 启动 Runtime 时测试明确拒绝，Node 24 通过。

- [ ] **Step 6: 提交**

```powershell
git add package.json pnpm-workspace.yaml pnpm-lock.yaml packages/agent-protocol apps/agent-runtime
git commit -m "feat: scaffold agent runtime protocol"
```

### Task 2: 固定并复制 Claudian 上游代码与许可证

**Files:**
- Create: `scripts/vendor-claudian.ps1`
- Create: `apps/agent-runtime/src/claudian/**`
- Create: `apps/agent-runtime/UPSTREAM.md`
- Create: `apps/agent-runtime/PATCHES.md`
- Create: `apps/agent-runtime/FILES.json`
- Create: `apps/agent-runtime/THIRD_PARTY_NOTICES.md`
- Create: `apps/agent-runtime/licenses/claudian-MIT.txt`
- Create: `apps/agent-runtime/tests/upstream-manifest.test.ts`
- Create: `apps/agent-runtime/tests/conformance/**`

- [ ] **Step 1: 写 manifest 失败测试**

```ts
import manifest from "../FILES.json" with { type: "json" };

it("pins the approved Claudian source", () => {
  expect(manifest.upstreamCommit).toBe("d190786d11cc0b067475dcffbf8c334ee565d208");
  expect(manifest.files.length).toBeGreaterThan(0);
  expect(manifest.files.every((file) => /^[a-f0-9]{64}$/.test(file.sha256))).toBe(true);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/agent-runtime test -- upstream-manifest`

Expected: FAIL，因为 `FILES.json` 尚不存在。

- [ ] **Step 3: 实现固定 commit vendoring 脚本**

```powershell
param(
  [Parameter(Mandatory=$true)][string]$SourceRoot
)
$ExpectedCommit = 'd190786d11cc0b067475dcffbf8c334ee565d208'
$ActualCommit = (git -C $SourceRoot rev-parse HEAD).Trim()
if ($ActualCommit -ne $ExpectedCommit) { throw "Expected Claudian $ExpectedCommit, got $ActualCommit" }
$Include = @(
  'src/core/execution','src/core/providers','src/core/tools','src/core/security',
  'src/core/prompt','src/core/skills','src/core/process','src/core/storage/VaultFileAdapter.ts',
  'src/providers/claude/execution','src/providers/claude/history','src/providers/claude/runtime',
  'src/providers/claude/security','src/providers/claude/storage'
)
```

脚本逐文件复制到 `apps/agent-runtime/src/claudian/<原路径>`，使用 `Get-FileHash -Algorithm SHA256` 生成排序稳定的 `FILES.json`；不得复制 Obsidian UI 主入口或使用整目录覆盖现有 adapter。

- [ ] **Step 4: 写许可证和 patch 记录**

`UPSTREAM.md` 必须写明仓库、版本 `2.2.4`、commit、vendor 日期 `2026-08-28` 和复制范围。`licenses/claudian-MIT.txt` 保留完整 MIT 文本及 `Copyright (c) 2025`。`PATCHES.md` 逐项记录 import 重定向、Obsidian 边界替换、Node host 适配和安全补丁；`THIRD_PARTY_NOTICES.md` 在发行包中引用许可证，但任何 React 设置组件不得读取或显示该文件。

- [ ] **Step 5: 移植适用上游测试**

优先复制并最小改写以下测试意图：`ProviderExecutionBackend`、`ClaudeExecutionEventNormalizer`、`ClaudeSessionRecovery`、`ClaudePermissionUpdates`、`ManagedStdioProcess`、`AgentVaultStorage`、`SkillStorage`、path/windows shim。测试 import 指向 `src/claudian`，adapter 差异写入 `PATCHES.md`。

- [ ] **Step 6: 生成 vendor 内容并验证**

Run: `powershell -ExecutionPolicy Bypass -File scripts/vendor-claudian.ps1 -SourceRoot 'C:\Users\asus\AppData\Local\Temp\claudian-reference'`

Expected: commit 校验成功，`FILES.json` 中所有 hash 与复制文件一致。

Run: `pnpm --dir apps/agent-runtime test:conformance`

Expected: 适用上游 conformance tests 全部通过。

- [ ] **Step 7: 提交**

```powershell
git add scripts/vendor-claudian.ps1 apps/agent-runtime
git commit -m "feat: vendor approved Claudian runtime core"
```

### Task 3: 接入 Provider Registry、Claude SDK 和持久 session

**Files:**
- Create: `apps/agent-runtime/src/providers/registry.ts`
- Create: `apps/agent-runtime/src/providers/types.ts`
- Create: `apps/agent-runtime/src/providers/claude/ClaudeProvider.ts`
- Create: `apps/agent-runtime/src/runtime/RuntimeService.ts`
- Create: `apps/agent-runtime/src/runtime/SessionRegistry.ts`
- Create: `apps/agent-runtime/src/runtime/EventSink.ts`
- Create: `apps/agent-runtime/src/runtime/SidecarStore.ts`
- Create: `apps/agent-runtime/tests/provider-registry.test.ts`
- Create: `apps/agent-runtime/tests/session-recovery.test.ts`
- Create: `apps/agent-runtime/tests/event-sink.test.ts`

- [ ] **Step 1: 写 provider 和恢复失败测试**

```ts
it("resumes a native Claude session after Runtime restart", async () => {
  const first = await harness.startTurn({ session_id: "app-session", input: "first" });
  await harness.restartRuntime();
  const second = await harness.startTurn({ session_id: "app-session", input: "second" });
  expect(second.native_session_id).toBe(first.native_session_id);
  expect(second.sequence).toBeGreaterThan(first.sequence);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/agent-runtime test -- provider-registry session-recovery event-sink`

Expected: FAIL，因为 Registry、SessionRegistry 和 EventSink 尚不存在。

- [ ] **Step 3: 实现 provider-neutral contract**

```ts
export interface AgentProvider {
  readonly id: string;
  start(request: RuntimeStartRequest, signal: AbortSignal): AsyncIterable<RuntimeEventEnvelope>;
  stop(sessionId: string): Promise<void>;
  rewind(sessionId: string, checkpointId: string): Promise<void>;
  fork(sessionId: string, checkpointId: string): Promise<{ native_session_id: string }>;
  health(): Promise<{ status: "ok" | "degraded" | "unavailable"; detail?: string }>;
}
```

`ProviderRegistry.require(id)` 对未知/禁用 provider 抛出结构化 `provider_unavailable`，首个完整实现注册为 `claude`；Faro 只保留 adapter 扩展点，不伪装成具备 Claude tools 的实现。

- [ ] **Step 4: 适配 Claude SDK**

`ClaudeProvider` 复用 Claudian 的 execution/session/history/runtime 文件，设置 `permissionMode: "bypassPermissions"`，向 SDK 提供全部 capability 允许的 workspace roots、MCP servers、Skills 和 subagent 配置。不得在 prompt 中加入“无教材禁止回答”或“仅依据教材”；system prompt 明确允许结合 Vault、模型知识和公开 Web，并要求标识来源与不确定性。

- [ ] **Step 5: 实现事件确认和 sidecar**

`EventSink.publish(event)` 使用 `idempotency_key` POST 到 FastAPI callback，只有收到持久化 ACK 才推进 cursor；重试采用 1s/2s/4s/8s/30s 上限退避。payload JSON 超过 `AGENT_INLINE_EVENT_BYTES` 时，`SidecarStore` 原子写入 `<sidecarRoot>/<session>/<event>.json`，事件 payload 只保留 `{sidecar_id,sha256,size,media_type}`，不截断正文。

- [ ] **Step 6: 运行测试**

Run: `pnpm --dir apps/agent-runtime test -- provider-registry session-recovery event-sink`

Expected: PASS，包括重复 ACK、Runtime restart、Stop/Resume/Rewind/Fork 和 sidecar hash。

- [ ] **Step 7: 提交**

```powershell
git add apps/agent-runtime/src/providers apps/agent-runtime/src/runtime apps/agent-runtime/tests
git commit -m "feat: add Claude provider sessions and replayable events"
```

### Task 4: 实现 capability、路径策略和 Vault 文件工具

**Files:**
- Create: `apps/agent-runtime/src/security/capability.ts`
- Create: `apps/agent-runtime/src/security/path-policy.ts`
- Create: `apps/agent-runtime/src/security/redact.ts`
- Create: `apps/agent-runtime/src/vault/HostVaultAdapter.ts`
- Create: `apps/agent-runtime/src/vault/atomic-write.ts`
- Create: `apps/agent-runtime/src/vault/watcher.ts`
- Create: `apps/agent-runtime/tests/capability.test.ts`
- Create: `apps/agent-runtime/tests/path-policy.windows.test.ts`
- Create: `apps/agent-runtime/tests/path-policy.posix.test.ts`
- Create: `apps/agent-runtime/tests/vault-tools.test.ts`

- [ ] **Step 1: 写路径逃逸失败测试**

```ts
it.each(["../other-user/a.md", "C:\\Windows\\win.ini", "vault\\..\\..\\secret", "\\\\server\\share\\x"])(
  "rejects %s outside granted roots",
  async (candidate) => expect(policy.resolveWritable(candidate)).rejects.toMatchObject({ code: "path_outside_grant" }),
);
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/agent-runtime test -- capability path-policy vault-tools`

Expected: FAIL，因为路径策略和 HostVaultAdapter 尚不存在。

- [ ] **Step 3: 实现签名 capability 验证**

Capability payload 包含 `version,user_id,session_id,grants,tool_categories,vault_roots,issued_at,expires_at,nonce`；Runtime 验证 HMAC-SHA256、过期时间、session 绑定和 nonce 格式。每次普通文件工具调用同时检查 knowledge-base grant、允许动作和 `realpath` 后的根目录包含关系。

- [ ] **Step 4: 实现 HostVaultAdapter**

```ts
export interface HostVaultAdapter {
  read(relativePath: string): Promise<Buffer>;
  writeAtomic(relativePath: string, content: Buffer, expectedHash?: string): Promise<{ beforeHash: string | null; afterHash: string }>;
  moveAtomic(from: string, to: string, expectedHash?: string): Promise<void>;
  remove(relativePath: string, expectedHash?: string): Promise<void>;
  list(prefix?: string): AsyncIterable<{ path: string; size: number; sha256: string }>;
}
```

写入使用同目录临时文件、flush、rename；Windows rename 冲突采用有界重试。`expectedHash` 不匹配返回 `vault_conflict`，不得覆盖。新建、修改、移动、重命名和删除均生成 change event；支持 `.md` 及配置允许的附件类型，不设置文件数量累计上限。

- [ ] **Step 5: 运行跨平台测试**

Run: `pnpm --dir apps/agent-runtime test -- capability path-policy vault-tools`

Expected: PASS；junction/symlink、大小写、UNC、drive-relative、`..`、NUL 和编码变体均不能逃逸；授权 Vault CRUD 通过。

- [ ] **Step 6: 提交**

```powershell
git add apps/agent-runtime/src/security apps/agent-runtime/src/vault apps/agent-runtime/tests
git commit -m "feat: enforce agent capabilities and vault boundaries"
```

### Task 5: 实现 Bash、公共 Web 和 SSRF 防护

**Files:**
- Create: `apps/agent-runtime/src/tools/bash/BashTool.ts`
- Create: `apps/agent-runtime/src/tools/bash/process-tree.ts`
- Create: `apps/agent-runtime/src/tools/web/WebSearchTool.ts`
- Create: `apps/agent-runtime/src/tools/web/WebFetchTool.ts`
- Create: `apps/agent-runtime/src/security/ssrf.ts`
- Create: `apps/agent-runtime/tests/bash-tool.test.ts`
- Create: `apps/agent-runtime/tests/web-tools.test.ts`
- Create: `apps/agent-runtime/tests/ssrf.test.ts`

- [ ] **Step 1: 写无累计上限和 SSRF 失败测试**

```ts
it("allows more than twenty sequential public fetches", async () => {
  for (let index = 0; index < 25; index += 1) await web.fetch(`https://public.example/${index}`);
  expect(fakeHttp.requests).toHaveLength(25);
});

it.each(["http://127.0.0.1/x", "http://169.254.169.254/latest/meta-data", "http://[::1]/x"])(
  "blocks private target %s",
  async (url) => expect(web.fetch(url)).rejects.toMatchObject({ code: "ssrf_blocked" }),
);
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/agent-runtime test -- bash-tool web-tools ssrf`

Expected: FAIL，因为工具尚不存在。

- [ ] **Step 3: 实现宿主机命令执行**

Bash/PowerShell 工具默认自动执行，不增加应用审批 UI；工作目录必须为授权 Vault root 或显式外部 workspace root。输出采用流事件，超过 inline 阈值转 sidecar；Stop 终止完整进程树。审计记录命令、cwd、exit code、duration、stdout/stderr sidecar 和脱敏环境变量，secret 值不写事件。

- [ ] **Step 4: 实现 WebSearch/WebFetch**

WebSearch 通过 provider native web tool 或配置的公开 search adapter；WebFetch 支持 HTTPS/HTTP 公网目标、重定向逐跳复验、DNS A/AAAA 全量复验、响应类型/解压大小/单请求超时和并发 backpressure。不得设置累计网页数或固定摘录数；长正文写 sidecar 并允许模型继续读取。

- [ ] **Step 5: 运行测试**

Run: `pnpm --dir apps/agent-runtime test -- bash-tool web-tools ssrf`

Expected: PASS；25 次以上网页调用成功，private/link-local/metadata/DNS rebinding/redirect-to-private 被拒绝，长网页未静默截断。

- [ ] **Step 6: 提交**

```powershell
git add apps/agent-runtime/src/tools apps/agent-runtime/src/security/ssrf.ts apps/agent-runtime/tests
git commit -m "feat: add host command and public web tools"
```

### Task 6: 接入 MCP、Skills、子智能体和 Runtime 控制 API

**Files:**
- Create: `apps/agent-runtime/src/mcp/McpManager.ts`
- Create: `apps/agent-runtime/src/mcp/config.ts`
- Create: `apps/agent-runtime/src/skills/SkillRepository.ts`
- Create: `apps/agent-runtime/src/skills/SkillWatcher.ts`
- Create: `apps/agent-runtime/src/subagents/SubagentManager.ts`
- Modify: `apps/agent-runtime/src/runtime/RuntimeService.ts`
- Modify: `apps/agent-runtime/src/server.ts`
- Create: `apps/agent-runtime/tests/mcp.test.ts`
- Create: `apps/agent-runtime/tests/skills.test.ts`
- Create: `apps/agent-runtime/tests/subagents.test.ts`
- Create: `apps/agent-runtime/tests/runtime-api.test.ts`

- [ ] **Step 1: 写三类能力失败测试**

```ts
it("loads global and vault skills without a product count cap", async () => {
  await repository.refresh();
  expect(repository.list()).toHaveLength(75);
});

it.each(["stdio", "sse", "streamable-http"])("connects MCP transport %s", async (transport) => {
  expect((await harness.connectMcp(transport)).status).toBe("connected");
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/agent-runtime test -- mcp skills subagents runtime-api`

Expected: FAIL，因为 manager 和控制路由尚不存在。

- [ ] **Step 3: 实现 MCP manager**

MCP config 支持 stdio、SSE、Streamable HTTP；stdio 复用 Claudian `ManagedStdioProcess`，网络 transport 复用与 Web 相同的公网/显式 allowlist 策略。每个 server/tool 的状态、错误和耗时进入事件与审计；server 故障只使对应工具降级，不终止 Runtime。

- [ ] **Step 4: 实现 Skills 和子智能体**

Skills 从全局目录和每个 Vault `.claude/skills`/配置目录加载，复用 Claudian codec/validation，文件 watcher 更新缓存。SubagentManager 复用 Claude 原生子智能体事件和 history sidecar，父子 session/tool call 均保留关联 ID；不设置子智能体累计数量产品上限，但使用队列、并发配置和可观测 backpressure。

- [ ] **Step 5: 完成控制 API**

实现 `POST /v1/sessions/start`、`POST /v1/sessions/:id/stop`、`resume`、`rewind`、`fork`、`GET /v1/sessions/:id`、`GET /v1/diagnostics`、`GET /v1/sidecars/:id`。每个 mutation 需要 Runtime bearer token、capability 和 idempotency key；重复 start 返回原执行映射，不创建第二个 Claude turn。

- [ ] **Step 6: 运行 Runtime 全量门禁**

Run: `pnpm --dir apps/agent-runtime test && pnpm --dir apps/agent-runtime typecheck && pnpm --dir apps/agent-runtime lint && pnpm --dir apps/agent-runtime test:conformance`

Expected: 全部通过；Jest 无 open handles；许可证文件存在发行输出但 UI bundle 不包含 notice 文本。

- [ ] **Step 7: 提交**

```powershell
git add apps/agent-runtime/src apps/agent-runtime/tests apps/agent-runtime/package.json pnpm-lock.yaml
git commit -m "feat: complete Claudian-compatible agent runtime"
```
