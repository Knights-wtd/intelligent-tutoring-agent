# 智能辅导 Agent：协作开发交接

> 面向新协作者。请先核对仓库真实状态，再开始开发；不要仅凭本文的完成清单直接假设代码可用。

## 1. 仓库与当前基线

- 私有仓库：<https://github.com/Knights-wtd/intelligent-tutoring-agent>
- 默认分支：`main`
- 本交接生成前的实现基线：`ea1705226b93f7dd7eeabc46c132d01722c2e2f3`
- 技术栈：FastAPI / SQLAlchemy / Alembic / PostgreSQL，Next.js 16 / React 19 / TypeScript / Vitest。
- `main` 是协作的唯一事实来源。原开发机有大量未提交、未跟踪的实验性改动，它们没有上传，也不应被视为已实现功能。

先阅读：

- [README.md](README.md)
- [PRODUCT.md](PRODUCT.md)
- [DESIGN.md](DESIGN.md)
- [工作区实施计划](docs/superpowers/plans/2026-08-24-obsidian-workspace-implementation-plan.md)
- [AI 家教计划](docs/superpowers/plans/2026-08-24-contextual-ai-tutor-plan.md)
- [知识图谱计划](docs/superpowers/plans/2026-08-24-knowledge-graph-plan.md)
- [个人学习工作区设计规格](docs/superpowers/specs/2026-08-24-obsidian-personal-study-workspace-design.md)

## 2. 第一原则：先审计，后开发

开始任何实现前，必须完成以下检查并把结果写到 GitHub Issue 或首个 Draft PR：

```powershell
git switch main
git pull --ff-only
git status --short
git log -15 --oneline
git rev-parse HEAD
```

期望：工作树干净，`main` 至少包含本文所列实现基线。然后核对计划中的文件是否真实存在、测试是否真实可复现：

```powershell
pnpm install --frozen-lockfile
pnpm --dir apps/web exec vitest run `
  src/components/workspace/workspace-preferences.test.ts `
  src/components/workspace/workspace-tabs.test.ts `
  src/components/workspace/use-knowledge-library.test.tsx `
  src/components/workspace/knowledge-library-sidebar.test.tsx `
  src/components/workspace/workspace-shell.test.tsx
pnpm --dir apps/web exec tsc --noEmit
pnpm --dir apps/web lint

& 'apps\api\.venv\Scripts\python.exe' -m pytest `
  apps/api/tests/test_knowledge_graph.py `
  apps/api/tests/test_tutor.py `
  apps/api/tests/test_llm_faro.py `
  apps/api/tests/test_schema.py -q -p no:cacheprovider
```

若依赖尚未安装，按 README 安装；不要修改测试来掩盖环境问题。审计报告至少列出：

1. 当前提交 SHA；
2. 通过/失败/无法运行的命令；
3. 已存在的模块与缺失模块；
4. 准备承担的任务和文件范围；
5. 与计划不一致之处。

## 3. 已实现且曾通过验证的功能

以下内容已经提交；仍需由新协作者在自己的环境复验：

### 知识库与关联图

- 租户隔离的候选知识图持久化、查询和 API；
- Web 图谱客户端、确定性布局、可访问图谱面板；
- 已确认图谱切片的 API/Web 集成与复审。

相关提交：`4c15cc3` → `f9cc810` → `6f60258` → `d04b508` → `018627b`。

### AI 家教

- Faro 提供方适配与安全错误封装；
- 租户隔离的导师会话与消息持久化；
- 直接复用知识库 service/query 的来源约束检索，不使用 loopback HTTP；
- 配置状态、创建会话、读取会话和续聊端点；
- Web TutorPanel、引用入口、异步取消与错误状态；
- 500/501 字符边界与会话 `updated_at` 单调推进修复。

相关提交：`082a441`、`9381cb2`、`72f6440`、`d76b030`、`2ac32c4`、`2315780`、`dc1850a`、`e7c67ef`。

最近记录的综合证据：API 目标套件 84 项通过，Web Tutor 13 项通过，Web Lint 与生产构建通过；最终边界修复后联合 API 套件 105 项通过。请重新运行，不要把历史结果当作当前结果。

### 班级、角色与班级知识库（后端已提交；公开前端仍未完整接入）

- 班级后端已在 `main`：创建班级会建立班级空间和 Owner 成员；可用邀请码加入；成员角色包含 `owner`、`teacher`、`student`；Owner 可以管理成员角色，Teacher 可以创建受限邀请码，Student 不能管理成员或创建邀请码。
- 知识库共享的实际模型是“班级空间中的知识库”：全体班级成员可读；仅 Owner/Teacher 可对班级空间和其中知识库写入。它不是把个人知识库直接一键转发到班级的独立分享接口。
- 2026-08-26 已运行 `apps/api/tests/test_classrooms.py` 与 `apps/api/tests/test_spaces.py`，结果为 **10 passed**。
- **重要差异：**公开 `main` 的工作台只保留了一个“创建或加入班级”按钮/示例班级空间；该按钮尚未接到已提交的班级 API。原开发机存在未跟踪的 `apps/web/src/lib/classrooms-api.ts` 和工作台改动，包含创建/加入对话逻辑，但它们不在远程 `main`，未经过单独交接审计，不能直接视为可发布实现。
### 新工作区已完成部分

- Task 1：共享知识库状态、中央标签状态、按空间偏好持久化，提交 `de053e3`；
- Task 2：最左侧知识库栏，提交 `2b0192a`；
- 结构性 Shell 修改前的最小集成契约基线，提交 `ea17052`。

最近记录的证据：Task 1–2 联合 31 项测试通过；基线联合 7 个套件、56 项测试通过；TypeScript 与 ESLint 通过。

## 4. 尚未实现的内容

以[工作区实施计划](docs/superpowers/plans/2026-08-24-obsidian-workspace-implementation-plan.md)为详细规格，剩余 Task 3–7：

1. **Task 3：诚实的“继续学习”仪表盘**  
   使用到期复习项作为首要继续入口；没有持久化阅读游标时不得伪造百分比进度。
2. **Task 4：知识与题库面板改为受控上下文**  
   知识库选择由 Shell 统一拥有，面板不得重复加载/创建/选择知识库。
3. **Task 5：重建桌面 Shell 与中央标签页**  
   完成“左侧知识库 / 中央标签 / 右侧 Tutor”的批准布局，并接入图谱、练习和引用上下文。
4. **Task 6：平板/移动抽屉及 CSS 回归契约**  
   覆盖桌面、平板、紧凑和手机模式，保持选择与 Tutor 会话状态。
5. **Task 7：全量回归、浏览器验收和设计系统固化**  
   完成 Web/API 验证、真实浏览器宽度验收、设计 token 文档与最终独立复审。

### 班级前端接入：单独的审计与实现项

在继续工作区 Task 3 前或作为一个独立小任务，先审计并决定班级 UI 的发布方案：

1. 以已提交的 `/api/v1/classrooms` 和 `/api/v1/spaces` 契约为事实来源，复验角色、邀请码与班级空间知识库读写权限；
2. 检查公开 `main` 中工作台的“创建或加入班级”按钮为何未连接真实 API；
3. 把本机未跟踪的 `classrooms-api.ts` / 工作台改动仅作为**候选参考**，逐文件审计、补测试并通过独立 PR 重建，不可直接整体暂存；
4. 明确是否需要追加“成员列表、角色调整、生成邀请码”的教师 UI；后端有相关 API，但公开前端尚无完整管理界面；
5. 该任务完成后，才可对外声称“班级功能在 Web UI 中完整可用”。
### Task 3 的强制前置审计

计划假定 `apps/web/src/lib/question-bank-api.ts` 和测试已有可修改基线，但远程 `main` 的实现基线没有这些本地未跟踪文件。不要复制原开发机的脏工作树，也不要直接照计划执行 `git add`。

开始 Task 3 前：

1. 检查远程 `main` 是否仍缺少题库客户端；
2. 从后端现有路由/Schema 和已提交测试确认真实 API 契约；
3. 在 Issue/Draft PR 中提出最小客户端基线及测试范围；
4. 获得仓库所有者确认后，再用单独提交建立客户端基线；
5. 随后实施 StudyDashboard。

## 5. 推荐开发顺序

默认按 Task 3 → 4 → 5 → 6 → 7。Task 3 和 Task 4 可以由两人并行，但必须避免同时修改 `workspace-shell.module.css`，并在 Task 5 前全部合并。

每个任务执行：

1. 从最新 `main` 创建短生命周期分支，例如 `feat/workspace-task-3-dashboard`；
2. 先写失败测试并保留 RED 证据；
3. 只实现使测试通过的最小改动；
4. 跑定向测试、TypeScript/ESLint 或 Ruff；
5. 检查 `git diff --check` 和暂存文件清单；
6. 提交并推送分支；
7. 创建 Draft PR，填写测试证据与未覆盖风险；
8. 由另一人或独立 AI 先做规格复审，再做代码质量复审；
9. 审批后合并，下一任务重新从最新 `main` 开始。

禁止直接推送 `main`。禁止使用 `git add .`、`git add apps/web` 等宽范围暂存命令。

## 6. 不能破坏的架构边界

- 知识库链路视为已完成；不得重复实现上传、解析、切分、索引、检索或图谱 API。
- AI 家教在同一 FastAPI 进程内复用 knowledge service/query 与租户权限边界；不得后端 HTTP 自调。
- 前端知识库选择由工作区 Shell 统一管理；面板通过受控 props 接收上下文。
- 不得把 API key、`.env`、密钥文件或模型权重提交到仓库；`.env.example` 只允许占位符。
- 不安装新的 UI 组件库；沿用现有 CSS Modules 与已批准的暖白/柔紫工作台语言。
- Next.js 版本具有破坏性变化。修改 Web 代码前必须阅读 `apps/web/AGENTS.md` 以及 `apps/web/node_modules/next/dist/docs/` 中对应版本文档。
- 不覆盖、清理或提交来源不明的本地改动；发现脏工作树时先停下确认所有权。

## 7. PR 必填内容

- 对应计划任务及不做事项；
- 改动文件清单；
- RED 失败证据与 GREEN 验证命令；
- 租户隔离、权限、错误脱敏和异步取消的影响；
- UI 的键盘、焦点、响应式和 reduced-motion 证据；
- 截图或录屏（涉及可见 UI 时）；
- 尚未解决的风险；
- 确认未提交任何凭据或本地环境文件。

## 8. 完成定义

只有同时满足以下条件，任务才能标记完成：

- 计划验收点全部有测试或浏览器证据；
- 定向测试、相关回归、类型/代码规范检查通过；
- 未修改计划外文件；
- PR 已经另一名协作者审批；
- `main` 合并后重新验证；
- 文档中的“已实现/未实现”状态同步更新。

## 9. 推荐给 AI 开发会话的工作方式

若工具支持，推荐使用：`planning-with-files`、`test-driven-development`、`systematic-debugging`、`verification-before-completion`、`requesting-code-review`。若没有这些技能，也应遵循同等流程：持久计划、先红后绿、根因调试、完成前新鲜验证、独立复审。

首次交付应是“状态审计 Issue 或 Draft PR”，而不是直接提交功能代码。

