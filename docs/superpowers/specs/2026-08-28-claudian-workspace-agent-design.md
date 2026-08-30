# Claudian 派生完整工作区智能体设计

日期：2026-08-28
状态：五部分方案均已获用户确认，待书面规格复核
参考上游：Claudian 2.2.4，commit `d190786d11cc0b067475dcffbf8c334ee565d208`
许可证：MIT，Copyright (c) 2025

## 1. 背景

当前项目的 AI Tutor 仍然是一次 completion 驱动的有界 RAG：后端先截取提问、最近若干条对话、本地检索结果和少量网页摘录，再一次性提交给 Faro/OpenAI-compatible 模型。这个模型不能像工作区智能体一样自主遍历知识库、连续检索网页、使用 Skills/MCP/子智能体、运行命令或修改文件。

当前未提交版本已经放宽了一部分限制并加入固定 Wikipedia/Wikimedia 搜索，但仍存在产品级累计上限：

| 项目 | 当前未提交版本限制 |
|---|---:|
| 提问长度 | 默认 4,000 字符，配置最大 20,000 |
| 对话历史 | 默认 30 条，配置最大 100 条 |
| 本地来源 | 最多 20 条 |
| 知识库数量 | 默认 100，配置最大 500 |
| 网页来源 | 默认 3，配置最大 10 |
| 网页摘录 | 默认 1,200 字符，配置最大 4,000 |
| 网络来源 | 固定 Wikipedia/Wikimedia |
| 检索 query | 仍截到 500 字符 |
| Faro 上下文 | 默认 32,000 token |
| Faro 并发 | 默认 2，配置最大 32 |
| Vault 文件数 | 默认 5,000，配置验证最大 100,000 |
| Vault 解压大小 | 默认 500 MiB，配置验证最大 20 GiB |

这些限制与项目的知识形态不匹配。当前知识库按知识点、方法和专有名词拆分，单条笔记通常不足以独立回答问题；真正的答案需要模型将多个知识点、通用知识和公开网页内容组合起来。因此，本设计不继续把固定数字改大，而是将 Tutor 直接替换为接近 Claudian 的完整工作区智能体，通过工具循环、分页、流式输出、sidecar 和 session compaction 管理资源。

## 2. 已确认目标

1. 取消“无教材证据时禁止使用通用知识回答”。
2. 取消“有教材证据时仅依据教材回答”。
3. 取消提问字符数、最近对话条数、本地证据条数、知识库数量、网页数量和累计工具调用数量的产品级固定上限。
4. 取消“网页只能提供短摘录”的语义限制；大型内容通过分页、sidecar 和按需读取处理。
5. 当前知识库只作为会话入口，Agent 可访问该用户有权读取的全部知识库。
6. Vault Markdown 正文成为最终事实来源；数据库承担 ACL、修订、索引、搜索和前端投影。
7. Agent 可以读取、创建、修改、重命名、移动和删除知识库文件。
8. 新建和外部修改的受支持文件自动纳入知识库；AI 根据内容决定分块、知识点、术语、标签和关联，但不决定是否收录。
9. Agent 可以结合模型通用知识和公共互联网，支持连续多轮 WebSearch/WebFetch。
10. Agent 可以在宿主机运行 Bash/PowerShell 等命令，默认不弹应用层审批。
11. 支持 MCP、Skills、子智能体、长任务、session 恢复、rewind 和 fork。
12. 首个完整 Provider 使用 Claude Agent SDK，同时保留 Faro Provider 抽象和未来 Provider 扩展能力。
13. Runtime 使用宿主机原生 Node.js 24 服务，而不是放进现有容器。
14. 直接替换现有 Tutor，不提供长期的新旧模式开关，也不发布只有聊天和搜索能力的缩水中间版本。
15. 尽量原样复用 Claudian 的模块、类型、事件、样式行为和测试，以减少能力缩水和回归风险。
16. 保留当前系统已有的用户、班级和知识库 ACL；扩大 Agent 能力不能等同于取消多租户隔离。
17. Agent Runtime 故障不得影响登录、知识库浏览、题库和其他非 Agent 功能。

## 3. 非目标与边界

- 本设计不尝试通过应用层审计把宿主机 `yolo` Bash 宣称为安全沙箱。
- 本设计不删除现有 Tutor 表、旧 MinIO 对象或数据库正文；它们在迁移稳定期保留为回滚源。
- 本设计不让 AI 直接绕过后端事务写 PostgreSQL 索引表。
- 本设计不把浏览器或 Node 进程内存作为 session、事件或同步状态的唯一来源。
- 本设计不为累积文件、证据、网页和工具调用设置人为的低固定上限；仍允许通过磁盘容量、Provider 实际 context、并发调度、网络超时和操作系统资源进行真实容量保护。
- 本设计不改变用户已经确认的默认宽松权限模式，但仍保留 `normal`、`plan` 和更严格部署的技术能力。

## 4. 方案比较与选择

### 4.1 方案 A：继续扩大现有 RAG

优点是改动小，但本质仍是一次 completion，无法完整支持工具循环、文件系统、MCP、Skills、子智能体、session 恢复和 Claudian 交互。把 20 改成 20,000 只会把限制变成更大的魔法数，并不能获得工作区 Agent 能力。

### 4.2 方案 B：独立重写完整 Agent

可以彻底控制架构，但会重复实现 Claudian 已经具备的 execution、tool event、session、MCP、Skills、subagent、Bash、权限模式和 UI 状态机，工作量和行为偏差最大。

### 4.3 方案 C：Claudian 派生运行时 + 当前项目适配层

采用此方案。尽量保留 Claudian 的核心文件、类型、事件和测试，只替换 Obsidian 插件边界、Vault adapter、配置存储、认证/ACL 和 Web UI renderer。这样最接近用户指定目标，并减少重新实现造成的能力缺失和 bug。

## 5. 总体架构

新增宿主机服务：

```text
apps/agent-runtime/
```

逻辑边界：

```text
Browser / Next.js
        |
        | HTTPS + WebSocket
        v
FastAPI control plane
  - authentication
  - knowledge-base ACL
  - capability signing
  - Agent session metadata
  - event persistence/replay
  - Vault revision projection
  - index orchestration
  - audit
        |
        | Named Pipe / Unix socket
        | loopback fallback + shared secret
        v
Node.js 24 Agent Runtime
  - Claude Agent SDK
  - Provider Registry
  - Read/Write/Edit/Glob/Grep/LS
  - Bash/process management
  - WebSearch/WebFetch
  - MCP
  - Skills
  - subagents
  - native JSONL sessions
  - sidecar outputs
        |
        v
Permanent Vault filesystem
```

FastAPI 是认证和数据授权的信任边界；Agent Runtime 是执行引擎。Runtime 不自行推断用户是否可访问某个知识库，而是消费 FastAPI 根据现有 ACL 签发的短期 capability。

永久 Vault 建议布局：

```text
<AGENT_VAULT_ROOT>/
  spaces/
    <space-id>/
      <knowledge-base-id>/
        .knowledge-base.json
        notes/
        attachments/
        .claude/skills/
        .agent/sessions/
        .agent/audit/
        .agent/index-state/
```

全局 Runtime 数据和大型工具输出放在独立受控目录：

```text
<AGENT_RUNTIME_DATA_ROOT>/
  sessions/<session-id>/
    outputs/<tool-call-id>/
    jsonl/
    recovery/
```

## 6. Claudian 上游复用与许可证

参考源码位于研究工作副本，依据 commit：

```text
d190786d11cc0b067475dcffbf8c334ee565d208
```

参考版本依赖：

```json
{
  "@anthropic-ai/claude-agent-sdk": "0.3.226",
  "@modelcontextprotocol/sdk": "~1.30.0",
  "node": ">=24 <25"
}
```

优先复用的上游模块包括：

- `src/core/execution`
- `src/core/providers`
- `src/core/tools`
- `src/core/security`
- `src/core/prompt`
- `src/core/skills`
- `src/core/process`
- `src/core/storage/VaultFileAdapter.ts`
- `src/providers/claude/execution`
- `src/providers/claude/history`
- `src/providers/claude/runtime`
- `src/providers/claude/security`
- `src/providers/claude/storage`
- `src/features/chat`
- `src/features/settings`
- `src/style`

上游保真规则：

1. 能原样保留的文件不进行无意义改写。
2. 优先通过 adapter 替换 Obsidian API 边界。
3. 保留工具名、事件类型、session 语义和原始测试。
4. 对修改过的上游文件记录 patch 原因。
5. 建立 `UPSTREAM.md`、`PATCHES.md` 和 `FILES.json`，记录来源 commit、复制文件及本地变更。
6. 在发行包和源码中保留 `THIRD_PARTY_NOTICES.md` 与 `licenses/claudian-MIT.txt`。
7. MIT License、原作者版权和 commit 信息不要求显示在前端界面。

## 7. Vault、数据库投影与索引

### 7.1 Vault 为正文事实来源

Markdown 正文和支持的附件以永久 Vault 文件为最终事实来源。数据库继续保存：

- 用户、空间、班级和知识库权限；
- `MarkdownNote` 投影；
- `MarkdownRevision` 历史；
- `MarkdownLink`；
- `Chunk`；
- `IndexVersion`；
- 搜索和前端查询所需元数据；
- 同步、索引和审计状态。

API、Agent、Shell、Git 或外部编辑器产生的文件变化都进入同一同步流水线，避免“Agent 写入”和“用户写入”形成两套数据规则。

### 7.2 自动收录

位于授权知识库 Vault 范围内的受支持文件自动纳入知识库，不要求 AI 先批准是否收录。AI 负责理解内容并提出：

- 分块；
- 知识点；
- 方法；
- 术语和别名；
- 标签；
- 内部链接；
- 跨笔记关联；
- 索引元数据。

若 AI 索引失败，文件仍然是知识库的一部分，Agent 仍可使用 `Read`、`Glob` 和 `Grep` 访问。

### 7.3 两阶段索引

第一阶段是确定性基础索引：

- 识别文件类型；
- 规范化路径；
- 计算内容 hash；
- 提取 Markdown frontmatter、标题和明确链接；
- 创建或更新 `VaultFile`、`MarkdownNote` 和 Revision；
- 建立最小可搜索文本；
- 记录 change set。

第二阶段是 AI 语义索引：

- Agent/索引模型读取完整内容及必要关联文件；
- 输出符合版本化 JSON Schema 的 `SemanticIndexPlan`；
- 确定性后端校验路径、引用、权限和数据一致性；
- 创建新 `IndexVersion`；
- 全部成功后原子激活。

AI 不直接执行任意 SQL，也不能决定跳过合法 Vault 文件。

### 7.4 稳定文件身份

每个 Vault 文件具有稳定 UUID，路径只是可变属性。重命名和移动时：

- UUID 不变；
- Revision 历史不丢失；
- 反向链接继续指向同一逻辑文件；
- 索引记录更新路径，而不是删除后重新创建无关文档。

`.knowledge-base.json` 或受控 sidecar 保存必要的映射信息；数据库也保存对应 `VaultFile`。

### 7.5 Watcher 和变化归并

Watcher 监控：

- Agent 文件工具；
- 宿主机 Shell；
- Git checkout、merge、pull；
- 外部编辑器；
- 迁移和后台任务。

同步使用内容 hash、来源 ID 和 change set 去重，防止：

```text
Vault -> DB -> Vault -> DB
```

形成循环。Git 等一次产生大量文件变化时，应归并为一个 `VaultChangeSet`，再按依赖顺序处理，而不是生成大量无序的独立任务。

### 7.6 原子写和冲突

写文件采用同目录临时文件、flush/fsync（平台允许时）和原子 rename。若 Vault 内容与数据库投影冲突：

1. 先保存数据库旧正文为 `MarkdownRevision`；
2.记录冲突来源、before/after hash 和审计事件；
3.以 Vault 正文更新数据库投影；
4.触发新索引；
5.保留恢复入口。

删除产生 tombstone 和 Revision，不立即不可恢复地清除历史。

### 7.7 初始迁移

初始迁移顺序：

1. 从数据库和 MinIO 导出文件；
2.生成稳定 UUID 与 hash manifest；
3.校验文件数、字节数、正文和附件 hash；
4.启动 shadow sync；
5.比较 Vault、数据库投影和现有搜索结果；
6.建立但不立即激活新索引；
7.通过一致性检查后原子切换；
8.稳定期内保留旧数据作为回滚源。

## 8. Agent Runtime 与 Provider

### 8.1 Node.js 24 宿主机服务

Agent Runtime 使用 Node.js `>=24 <25`，不进入现有 compose。优先使用：

- Windows Named Pipe；
- Unix domain socket；
- 必要时 loopback TCP + 双向 shared secret。

Runtime 提供健康检查、版本、Provider 状态、MCP 状态、活动 session 和队列指标。

### 8.2 Provider Registry

保留通用 Provider Registry：

- Claude Agent SDK Provider：首个完整 Provider；
- Faro Provider：保留兼容和未来扩展，不再作为完整 Agent 的能力上限；
- 未来 Provider：只要能满足工具循环和 session 协议即可接入。

Provider 层统一暴露：

- session create/resume；
- streaming event；
- tool loop；
- stop；
- context compaction；
- usage；
- error normalization。

### 8.3 Claude SDK

首期使用：

```text
@anthropic-ai/claude-agent-sdk 0.3.226
```

默认权限模式采用 Claudian 风格：

```text
yolo -> bypassPermissions
```

同时保留：

- `normal`
- `plan`
- 未来部署自定义模式

这不是旧 Tutor 的证据限制开关，而是工具执行权限模式。

### 8.4 工具能力

保留 Claudian 相应能力和事件语义，包括：

```text
Read Write Edit Glob Grep LS NotebookEdit
Bash BashOutput KillShell write_stdin
WebSearch WebFetch
Agent spawn_agent send_input wait wait_agent resume_agent close_agent
AskUserQuestion TodoWrite
EnterPlanMode ExitPlanMode
Mcp ListMcpResources ReadMcpResource ToolSearch
Skill
```

若 Claude SDK 版本中的实际工具名或接口发生变化，适配层负责版本映射，但前端事件模型保持稳定。

### 8.5 宿主机命令

命令直接在宿主机执行，默认自动运行，不弹应用层审批。Runtime 保留：

- PTY 和非 PTY；
- 流式 stdout/stderr；
- 后台进程；
- `write_stdin`；
- 停止和 kill；
- 退出码；
- 工作目录；
- 大输出 sidecar；
- 审计引用。

必须明确：知识库文件工具受 capability 和路径校验约束，但宿主机 Bash 的真实权限更大。应用层日志不能替代 OS 用户、文件 ACL、容器/VM 或防火墙。如果部署者需要强隔离，应在操作系统层实施。

### 8.6 公共 WebSearch/WebFetch

替换固定 Wikipedia/Wikimedia 实现：

- 可搜索公开互联网；
- 支持多轮搜索和链接追踪；
- 累计网页数量不设产品级固定上限；
- 正文不使用固定短摘录作为唯一上下文；
- 大网页保存 sidecar，可分页、检索和按需加入上下文；
- 记录来源 URL、时间、hash 和工具事件。

WebFetch 阻止：

- localhost 和环回地址；
- 链路本地地址；
- RFC1918 私网；
- IPv6 私网/本地地址；
- 云 metadata 地址；
- 危险 scheme；
- 重定向到受阻目标；
- DNS 解析后落入受阻网段。

该规则只约束内建 Web 工具。Bash、MCP 和第三方 Skills 的网络访问若需强制限制，必须依赖宿主机防火墙或更强隔离。

### 8.7 MCP

支持：

- stdio；
- SSE；
- Streamable HTTP；
- server 生命周期和健康检查；
- tool discovery；
- resources；
- 超时、重启和错误隔离；
- secret 引用；
- 审计。

单个 MCP server 崩溃不得导致整个 Runtime 退出。

### 8.8 Skills

Skills 搜索范围：

```text
<Vault>/.claude/skills
C:\Users\asus\.agents\skills
C:\Users\asus\.codex\skills
```

局部 Vault Skill 优先级和冲突处理尽量遵循 Claudian。全局目录通过配置解析，不能在通用实现中硬编码特定用户名。Runtime 支持刷新、禁用、错误诊断和来源显示。

用户提供的 `C:\Users\asus\Downloads\skills-main.zip` 已在当前 Windows 用户范围安装/更新到 `C:\Users\asus\.agents\skills`；ZIP 中 37 个 Skill 均存在且 `SKILL.md` hash 一致。既有 `obsidian-auto-card` frontmatter 警告不是本次安装失败。

### 8.9 子智能体和长任务

保留 Claudian/Claude Agent SDK 子智能体生命周期：

- spawn；
- send input；
- wait；
- resume；
- close；
- 父子关联；
- 独立工具事件；
- 停止传播；
- 重启恢复元数据。

任务不设低固定时限。实际限制来自 Provider、主机资源、管理员调度和显式停止。

### 8.10 Session 和上下文

使用 Claude 原生 JSONL session 保存完整运行历史，PostgreSQL 保存 session 元数据和可重放事件。取消“只保留最近 N 条历史”的产品语义。

上下文策略：

- 目标支持 1,000,000 token；
- 读取 Provider 返回的实际模型能力；
- 不假设所有 Provider 都支持百万上下文；
- 使用 provider-native compaction 或版本化 compaction；
- 保留完整事件和原始 sidecar，压缩只影响送入模型的工作上下文；
- 前端仍可查看压缩前历史。

建议高资源默认值：

| 项目 | 默认 | 可配置上限 |
|---|---:|---:|
| warm sessions | 32 | 256 |
| active sessions | 128 | 由主机容量决定 |
| context target | 1,000,000 | Provider 实际能力 |
|累计文件/证据/网页/工具调用 | 无产品级固定上限 | 无产品级固定上限 |
|任务时限 | 无固定时限 | 管理员可配置 |

这些是调度和容量配置，不重新引入“模型最多只能看若干知识点”的语义限制。

## 9. 前端设计

### 9.1 直接替换 TutorPanel

现有 `TutorPanel` 直接替换为 `AgentPanel`。不保留长期的新旧模式切换，也不发布只有“聊天 + 搜索”的缩水版本。

React 层尽量复用 Claudian 的：

- 纯 TypeScript 状态；
- 事件类型；
- session controller；
- tool result model；
- stream aggregation；
- permission/settings model；
- CSS 行为。

Obsidian DOM renderer 改写为 React 组件，但不随意改变事件语义和交互能力。

### 9.2 会话与上下文

支持：

- 多 session tabs；
- session manager；
- 新建、归档和搜索；
- Stop、Resume、Rewind、Fork；
- 页面刷新恢复；
- WebSocket cursor 重连；
- 当前知识库作为 linked content 起点；
- 用户全部授权知识库的可见和可访问范围；
- context chips；
- `@mention` 文件/目录/知识库；
- 图片和附件；
- 网页上下文；
- 目录上下文。

前端不能通过隐藏知识库名称来代替后端 ACL；所有读取仍由 FastAPI capability 和 Runtime 路径校验保证。

### 9.3 工具呈现

AgentPanel 显示：

- thinking；
- 工具开始、进行中、成功和失败；
- 文件 Read/Write/Edit；
- diff 和路径变化；
- Bash 命令、流式输出和退出码；
- WebSearch/WebFetch 来源；
- MCP server/tool；
- Skill；
- subagent；
- Todo；
- context compaction；
- 大输出 sidecar 的分页预览；
- 索引状态；
- 需要用户输入的 Agent 问题。

支持 Bang Bash、Inline Edit 和 Wiki Links，并尽量保持 Claudian 的快捷操作和视觉结构。

### 9.4 设置

设置页包括：

- Provider 和模型；
- context window；
- permission mode；
- Runtime 状态；
- MCP servers；
- Skills；
- Web tools；
- session/并发容量；
- 命令 shell；
- 审计与数据目录；
- 诊断信息。

Provider key、MCP secret 和敏感环境变量留在 Runtime 的受保护配置中。前端只获取掩码和状态，不读取明文 secret。

### 9.5 旧 Tutor 历史

旧 `TutorConversation` 作为只读 legacy history 展示。用户可以“从此历史创建 Agent Session”，把旧消息作为初始上下文；旧来源数量、证据约束和固定 RAG prompt 不迁移到新 Agent。

### 9.6 API

新增命名空间：

```text
/api/v1/agent/*
```

覆盖：

- sessions；
- turns/messages；
- stop/resume/rewind/fork；
- events/replay；
- WebSocket；
- context attachments；
- settings；
- Provider health；
- MCP；
- Skills；
- Runtime diagnostics；
- audit summary；
- sidecar preview；
- Vault/index status。

## 10. 数据模型

### 10.1 `AgentSession`

记录：

- 用户、工作区和初始知识库；
- Provider、模型、权限模式；
- Claude SDK 原生 session ID；
- 状态：运行中、等待输入、已停止、失败、归档；
- 父 session、fork 来源和 rewind 点；
- 创建、更新时间；
- 最近事件序号；
- Runtime 恢复信息。

当前知识库只是会话入口，实际访问范围由用户 ACL 决定。

### 10.2 `AgentTurn`

记录：

- session；
- 用户消息；
- 回复摘要；
- 开始、结束时间；
- 最终状态；
- 模型和上下文统计；
- resume、retry、rewind 或 fork 来源；
- Claude SDK turn/session 信息。

完整事件以 Claude JSONL 和事件表为准；Turn 用于列表、查询和审计。

### 10.3 `AgentSessionEvent`

保存前端可重放的结构化事件：

- 全局唯一 event ID；
- session 内严格递增 sequence；
- event type；
- 结构化 payload；
- 关联 turn、tool call、subagent；
- 时间和完成状态；
- 大型 payload 的 sidecar 引用。

事件覆盖用户消息、模型文本、thinking、工具生命周期、diff、Bash、Web、MCP、Skill、子智能体、Todo、错误、session 状态、compaction 和索引状态。

### 10.4 `AgentWorkspaceGrant`

短期 capability 至少包含：

- user ID；
- session ID；
- 允许访问的知识库 ID；
- 每个知识库的 read/write/delete 权限；
- 允许的工具类别；
- 允许的 Vault 根目录；
- 签发和过期时间；
- nonce；
- 签名和版本。

它是后端根据现有 ACL 生成的临时授权，不是替代 ACL 的永久权限表。

### 10.5 `AgentAuditEvent`

记录：

- 用户、session、turn；
- 工具和 tool call ID；
- 命令；
- 文件创建、修改、移动、重命名和删除；
- URL；
- MCP server/tool；
- Skill；
- subagent；
- before/after hash；
- 退出码、耗时和结果；
- sidecar 引用；
- 脱敏后的参数摘要。

### 10.6 `VaultFile`

记录：

- 稳定 UUID；
- knowledge base；
- 规范化相对路径；
- 文件类型；
- 内容 hash；
- 大小和时间戳；
- 关联 `MarkdownNote`；
- 同步状态；
- 最近 change set；
- tombstone；
- 最后成功索引版本。

### 10.7 `VaultChangeSet`

把一批变化组织成事务单元，来源包括 Agent、Shell、Git、外部编辑器、API 和初始迁移。记录文件变化、提交/冲突/索引状态、session/turn/tool call、before/after hash、失败和重试信息。

### 10.8 `VaultSyncCursor`

记录每个知识库的 Watcher cursor、数据库同步 cursor、索引 cursor、待处理数量、最近成功时间、最近错误和是否需要全量扫描。

### 10.9 `SemanticIndexPlan`

保存 AI 的结构化索引建议：分块、知识点、术语、别名、标签、内部链接、关联、置信度、模型、schema/prompt 版本、输入 hash、状态和验证错误。

### 10.10 `AgentProviderSetting`

保存 Provider 类型、模型、context、可用工具、endpoint 元数据、secret 引用、启用状态、健康状态和配置版本。明文 secret 不进入普通前端事件。

### 10.11 `AgentUsageRecord`

记录 input/output/cache token、compaction、工具次数、网页请求、文件读取量、命令时间、sidecar 存储量、Provider 错误和 session 持续时间。用途是容量管理和排障，不是固定证据截断。

### 10.12 扩展现有模型

`MarkdownNote` 增加：

- `vault_file_id`
- `vault_relative_path`
- `content_hash`
- `sync_state`
- `last_change_set_id`
- `is_tombstoned`
- `tombstoned_at`

`MarkdownRevision` 增加：

- `change_set_id`
- `agent_session_id`
- `agent_turn_id`
- `tool_call_id`
- `change_source`
- `before_hash`
- `after_hash`

`IndexVersion` 增加：

- `planner_provider`
- `planner_model`
- `planner_schema_version`
- `planner_prompt_hash`
- `source_change_set_id`
- `source_snapshot_hash`
- `activation_status`

旧 Tutor 表暂不删除。

## 11. FastAPI 与 Runtime 协议

### 11.1 会话建立

```text
Web -> FastAPI：创建 AgentSession
FastAPI：检查用户和知识库 ACL
FastAPI：签发短期 capability
FastAPI -> Runtime：启动或恢复 Claude SDK session
FastAPI：保存 Runtime session 映射
FastAPI -> WebSocket：发送持久化事件
```

请求包含 session ID、用户消息、当前知识库、linked contexts、附件引用、Provider/模型、权限模式、capability、idempotency key 和客户端最后 event cursor。

### 11.2 事件信封

每个 Runtime 事件包含：

```text
event_id
session_id
turn_id
sequence
event_type
timestamp
payload
idempotency_key
```

FastAPI 写入事件表后再确认持久化。重复事件按 event ID 和 idempotency key 去重。

### 11.3 WebSocket 重连

前端保存最后处理 sequence，重连时提交：

```text
session_id + after_sequence
```

FastAPI 先从事件表重放缺失事件，再切到实时流，避免刷新、断网或 Runtime 重启后出现重复副作用、缺段回复或永久“运行中”工具卡片。

### 11.4 大输出 sidecar

Bash、网页、MCP 和大文件内容不强行塞进单行事件，也不做短字符静默截断。事件保存：

- sidecar URI；
- 内容 hash；
- MIME；
- 字节数；
- 可预览范围；
- 是否已加入模型上下文。

前端按需分页，模型可通过工具再次读取完整内容。

### 11.5 Stop、Resume、Rewind、Fork

- Stop 中止当前 turn，不删除 session。
- Resume 从 SDK session 和持久事件继续。
- Rewind 创建逻辑分支，不破坏原历史。
- Fork 创建新 `AgentSession`，记录父 session 和分叉点。
- 已经产生文件副作用的 rewind 不静默回滚；前端展示变更并允许显式应用反向 diff。

## 12. ACL、路径和审计

### 12.1 保留现有 ACL

继续使用现有：

- 个人空间 owner；
- 班级 owner/teacher 可写；
- student 只读；
- `get_readable_knowledge_base`；
- `list_readable_knowledge_bases`；
- `get_writable_knowledge_base`。

Agent 扩大可访问范围的含义是“用户所有已授权知识库”，不是“服务器全部知识库”。

### 12.2 路径校验

`Read`、`Write`、`Edit`、`Glob`、`Grep`、`LS` 等工具只能解析到：

- 用户可读/可写知识库；
- 明确允许的 session sidecar；
- 明确允许的 Skills 和 Runtime 目录。

路径安全必须处理：

- `..`；
- 符号链接和 Windows junction；
- 大小写；
- UNC；
- 短路径；
- 绝对路径；
- 路径编码；
- 跨知识库链接。

不能只做字符串前缀比较，必须检查规范化后的真实路径及其知识库归属。

### 12.3 审计和脱敏

默认审计：

- 谁在何时触发；
- session、turn 和 tool call；
- 命令及退出码；
- 文件路径和 before/after hash；
- 外部 URL；
- MCP server/tool；
- Skill；
- subagent；
- 索引和 Revision；
- sidecar 引用。

默认脱敏：

- API key；
- Authorization/Cookie；
- Provider 和 MCP secret；
- 环境变量凭据；
- URL 查询参数常见 token；
- 命令输出中匹配已登记 secret 的内容。

审计提供可追踪性，但不能虚假声称已经消除 `yolo` 宿主机执行风险。

## 13. 故障隔离和恢复

### 13.1 Runtime 不可用

以下功能仍须正常：

- 登录和认证；
- 知识库查看；
- 文档浏览；
- 题库；
- 已有索引搜索；
- 班级和权限管理；
- 其他非 Agent API。

AgentPanel 显示 Runtime 健康错误，不使整个 Workspace 崩溃。

### 13.2 索引失败

- 文件仍可通过文件工具访问；
- 旧 active `IndexVersion` 保持可用；
- 失败计划进入重试队列；
- 前端区分“文件已保存，语义索引待处理”和“文件保存失败”；
- 不得先清空旧索引。

### 13.3 数据库不可用

Runtime 不得继续声称消息、同步、索引或审计已持久化。应安全停止或冻结产生进一步副作用的流程，保存本地恢复状态，数据库恢复后执行 reconciliation。

### 13.4 Runtime 重启

根据 `AgentSession` 元数据、Claude SDK JSONL、事件 cursor、sidecar 和未完成工具状态恢复，不能只依赖 Node 进程内存。

### 13.5 Watcher backlog

- 合并重复变化；
- 按最终 hash 去重；
- 支持全量 reconciliation；
- 暴露 backlog 数量和最旧等待时间；
- 积压不阻止直接打开文件；
- 同一内容不重复索引。

### 13.6 磁盘不足

写入前检查空间并原子写。失败时保留原文件，不更新成功 hash，不激活新索引，记录 change set 失败并向前端返回明确错误。

### 13.7 MCP、Web 和进程故障

- MCP 子进程独立生命周期、超时、重启和 stderr sidecar；
- 单个 MCP 故障不终止 Runtime；
- Web 超时只失败当前工具调用；
- 后台 Shell 进程可重新关联或标记丢失；
- 停止事件应传播到子智能体和当前工具，但不删除历史。

## 14. 测试策略

### 14.1 Claudian 上游一致性

移植适用测试，覆盖 execution、session history、Provider、tool event、permission mode、process、Bash、Skills、MCP、subagent 和 storage adapter。因 Obsidian 边界替换而修改的测试记录在 `PATCHES.md`，不能简单删除失败测试。

### 14.2 Node Agent Runtime

覆盖：

- Provider Registry；
- Claude SDK adapter；
- 工具注册；
- event sequence 和 idempotency；
- sidecar；
- session 恢复；
- process kill；
- Bash streaming；
- MCP stdio/SSE/Streamable HTTP；
- Skill discovery；
- subagent 生命周期；
- million-context 配置；
- context compaction；
- Runtime 重启。

### 14.3 FastAPI

覆盖：

- capability 签发和验证；
- 知识库读写 ACL；
- 跨用户和跨班级隔离；
- session API；
- WebSocket replay；
- 事件去重；
- 审计；
- legacy Tutor 迁移；
- Vault 同步；
- index plan 校验；
- Provider settings；
- Runtime 不可用时其他路由正常。

### 14.4 Vault 和索引

覆盖：

- 创建、修改、重命名、移动和删除；
- tombstone 和恢复；
- 外部编辑器、Bash、Agent 工具产生的变化；
- Git checkout/merge 批量变化；
- 数据库与 Vault 冲突；
- hash 去循环；
- 索引失败；
- 旧索引继续服务；
- 新索引原子激活；
- 大量小文件和超大 Markdown；
- 附件；
- Wiki Links；
- Windows 大小写、junction 和 symlink；
- 跨知识库链接。

### 14.5 Web 安全

覆盖：

- 公共网页；
- 连续多轮检索；
- 重定向；
- DNS rebinding；
- localhost；
- IPv4/IPv6 私网；
- 云 metadata；
- 危险 scheme；
- 超时；
- 大网页 sidecar；
- 不存在 3、10 等累计网页硬上限。

### 14.6 前端

覆盖：

- 多 session tabs；
- streaming 和 thinking；
- 全部工具卡片；
- Bash/Web/MCP/Skills/subagent/Todo；
- diff；
- Stop/Resume/Rewind/Fork；
- WebSocket 断线重连；
- 刷新恢复；
- large output 分页；
- legacy history；
- 当前和跨授权知识库；
- 未授权知识库不可见且不可读取；
- Runtime 故障隔离。

### 14.7 回归基线和 CI

不得降低此前已通过的基线：

- API 约 951 tests；
- Web 134 Vitest tests；
- Ruff；
- TypeScript；
- ESLint；
- Next production build；
- 真实 PostgreSQL/pgvector 集成测试；
- Windows Node.js 24 host smoke；
- Linux Node.js 24 smoke。

CI 新增独立 `agent-runtime` Node.js 24 job。

## 15. 部署和迁移

### 15.1 配置

新增配置预计包括：

```text
AGENT_RUNTIME_SOCKET
AGENT_RUNTIME_SECRET
AGENT_VAULT_ROOT
AGENT_RUNTIME_DATA_ROOT
AGENT_RUNTIME_LOG_ROOT
AGENT_PROVIDER
CLAUDE_CONFIG_DIR
CLAUDE_MODEL
CLAUDE_CONTEXT_WINDOW
AGENT_MAX_WARM_SESSIONS
AGENT_MAX_ACTIVE_SESSIONS
AGENT_WEB_ENABLED
AGENT_MCP_ENABLED
AGENT_SKILLS_ENABLED
```

建议：

```text
CLAUDE_CONTEXT_WINDOW=1000000
```

Runtime 仍以 Provider 报告的实际能力为准。

### 15.2 主机服务安装

提供：

- Windows 安装、启动、停止和升级脚本；
- Windows 服务定义；
- Linux systemd unit；
- Node.js 24 版本检查；
- socket/secret 初始化；
- health check；
- log rotation；
- 诊断命令。

### 15.3 数据迁移

1. 执行只新增兼容字段和表的数据库 migration。
2. 导出现有数据库/MinIO 内容到 Vault。
3. 生成 UUID 和 hash manifest。
4. 校验文件数、大小和 hash。
5. 运行 shadow sync。
6. 对比 Vault、数据库投影和旧搜索结果。
7. 建立新索引但不激活。
8. 完成 ACL、链接和索引一致性检查。
9. 原子切换 Vault 主存储、Agent API 和 AgentPanel。
10. 保留旧数据和旧 active index 作为回滚源。
11. 稳定期结束前不物理删除旧数据。

### 15.4 当前未提交改动

当前分支 `feature/platform-foundation-wip` 上存在上一版“有界 RAG + Wikipedia”未提交改动，共 19 个修改文件和 2 个新增文件。实施时不得 reset、checkout 或删除这些工作。

逐项分类：

- 可复用的 Faro/Provider 抽象；
- 可复用的 API schema、前端交互和测试；
- 需由 Agent Runtime 替代的有界 RAG service；
- 需替换的固定 Wikipedia 搜索；
- 需取消的限制配置；
- 需迁移或重写的测试。

每个既有修改文件在实施计划中必须明确“保留、迁移、替换或删除原因”。

### 15.5 回滚

- 停止 Agent Runtime；
- 前端显示维护状态或临时只读 legacy history；
- 重新指向旧 active index；
- 数据库 migration 保持向后兼容；
- 旧 MinIO/数据库正文继续保留；
- 不得静默删除已经写入 Vault 的新文件；
- 使用 change set manifest 将新数据重新导回旧体系或标记待迁移。

## 16. 验收标准

只有同时满足以下标准才视为完整交付：

1. 不再存在“无教材证据时禁止回答”。
2. 不再要求有教材证据时只能依据教材。
3. 不再限制问题最多 500 字符。
4. 不再只提供最近 10 条历史。
5. 不再限制本地证据为 5 条或 20 条。
6. 不再限制累计知识库、文件、网页、证据或工具调用数量。
7. 不再以固定短网页摘录作为模型唯一可见内容。
8. Agent 能读取用户有权访问的全部知识库。
9. 普通文件工具不能访问其他用户未授权知识库。
10. Agent 能结合知识库、模型通用知识和公开互联网。
11. Agent 能连续执行多轮 WebSearch/WebFetch。
12. Agent 能创建、修改、移动、重命名和删除 Vault 文件。
13. 新文件自动同步数据库并纳入知识库。
14. AI 能按内容生成分块、知识点、术语、标签和关联。
15. 索引失败时原文件和旧索引仍可使用。
16. Agent 能在宿主机执行 Bash/PowerShell 等命令。
17. Agent 能使用 MCP、Skills 和子智能体。
18. Session 在浏览器刷新和 Runtime 重启后恢复。
19. 支持 Stop、Resume、Rewind 和 Fork。
20. 大输出使用 sidecar，不因固定摘录长度静默丢失。
21. Provider 配置支持百万上下文目标并尊重模型实际能力。
22. FastAPI、Web、数据库和构建既有测试保持通过。
23. Runtime 故障不影响登录、知识库浏览、题库和其他功能。
24. 无跨用户、跨班级或跨知识库 ACL 回归。
25. Vault 迁移文件数、大小和 hash 一致。
26. Claudian 上游适用 conformance tests 通过。
27. 保留 Claudian MIT License、原作者版权声明和依据 commit `d190786d11cc0b067475dcffbf8c334ee565d208`。
28. License 信息存在源码、后端和发行包，但不在前端界面显示。
29. 上一版未提交改动得到逐文件处置，不被 reset 或静默覆盖。
30. 不上线只有聊天、固定 RAG 或固定网页搜索的长期缩水实现。

## 17. 可观测性和运维指标

至少暴露：

- Runtime health/version；
- Provider/MCP health；
- 活动、warm、排队 session；
- 事件持久化延迟；
- WebSocket replay 数量；
- 工具调用耗时和错误率；
- Bash/MCP/Web 运行状态；
- sidecar 使用量；
- Watcher backlog；
- index plan backlog；
- 索引成功率和激活延迟；
- Vault/DB hash 冲突；
- session 恢复成功率；
- capability 拒绝；
- SSRF 拒绝；
- 磁盘空间。

日志、指标和审计使用关联 ID：

```text
request_id
session_id
turn_id
tool_call_id
change_set_id
index_version_id
```

## 18. 主要风险及处理

### 18.1 宿主机 yolo 权限风险

这是用户明确选择的能力，不通过 UI 文案伪装为沙箱。通过独立服务身份、审计、secret 脱敏、可选 OS 隔离和清晰设置提示降低风险，但不削弱已确认的功能。

### 18.2 上下文和成本失控

不设置低固定证据上限，但通过 Provider usage、session 调度、compaction、缓存、sidecar 和可观测性管理。管理员容量配置不能改变“Agent 可继续按需读取”的语义。

### 18.3 Vault/数据库双写冲突

通过 Vault 为真、稳定 UUID、原子写、hash 去循环、Revision、change set、shadow sync 和 reconciliation 解决。数据库不能反向静默覆盖更新后的 Vault。

### 18.4 Claudian 上游升级偏差

通过固定 commit、上游文件清单、patch 记录和 conformance tests 控制。后续升级先在独立分支比较上游，不直接覆盖本地 adapter。

### 18.5 Runtime 成为单点故障

通过非 Agent 功能隔离、持久 session/event、重启恢复、健康检查和旧索引保留降低影响。

### 18.6 多租户越权

文件工具必须经过 capability、真实路径和知识库 ACL 三重校验；建立 Windows/Linux 路径逃逸和跨租户集成测试。Bash 的宿主机权限风险单独陈述，不与普通文件工具 ACL 混淆。

## 19. 实施阶段划分原则

正式实施计划应按可验证的垂直切片拆分，但最终切换前不得把缩水版本作为长期产品行为：

1. 上游代码、许可证和 Runtime 脚手架；
2. Provider/session/event 核心；
3. FastAPI capability 和协议；
4. 永久 Vault 与数据库投影；
5. 文件/Bash/Web 工具；
6. MCP、Skills 和子智能体；
7. React AgentPanel；
8. AI 语义索引；
9. 迁移、shadow sync 和切换；
10. 回归、conformance、宿主机 smoke 和发布门禁。

每个切片必须先写或移植测试，并在合并前证明不破坏现有功能。

## 20. 设计结论

采用“Claudian 派生运行时 + 当前项目适配层”：

- 在 `apps/agent-runtime` 中最大程度复用 Claudian；
- 由 FastAPI 保持认证、ACL、capability、事件、修订、索引和审计；
- 使用永久 Vault 作为 Markdown 正文事实来源；
- 使用宿主机 Node.js 24 + Claude Agent SDK 提供完整工作区 Agent；
- 取消固定 RAG 证据和网页累计限制；
- 通过工具循环、sidecar、compaction 和 Provider 实际上下文管理大规模知识；
- 直接以 AgentPanel 替换 TutorPanel；
- 保留现有多租户边界、旧数据和完整回滚路径；
- 以 Claudian 上游一致性测试和项目既有回归基线作为发布门禁。

本文件是实施计划的输入。书面规格再次获用户批准前，不修改实现代码。
