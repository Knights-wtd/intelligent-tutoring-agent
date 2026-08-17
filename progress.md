# Progress Log

## Session: 2026-08-14 · Provider and Wallet Planning

- **Status:** complete
- Actions taken:
  - 恢复已通过 Docker/PostgreSQL 验收的认证、班级与 C3 工作台里程碑。
  - 依据已批准的供应商、价格、汇率、钱包与人工充值设计，建立下一里程碑的测试先行实施计划。
  - 锁定边界：本机采用模拟供应商配置，不引入真实密钥、真实模型调用、自动支付、文档导入或 Agent 回答。
  - Task 1 完成并通过规格、代码质量两轮复审：供应商配置严格校验且不回显误填密钥；管理员邮箱字符串、列表与元组均统一规范化、去重和校验；Compose 仅接收非秘密配置。
  - Task 2 完成并通过规格、代码质量两轮复审：价格、汇率、钱包、预留、账本和充值审计的数据库约束已建立；跨钱包引用、数值边界和非法状态均由数据库拒绝；迁移在根目录和 API 工作目录均完成升级/降级往返测试。
  - Task 3 完成并通过规格、代码质量两轮复审：启动时安全同步非秘密供应商目录；用户仅能读取启用且可计量的模型和人民币价格摘要。模型身份变化会失效旧配置而不重标历史价格；最新价格/汇率使用 Decimal 快照换算，目录查询不产生 N+1 请求。
  - Task 4 完成并通过规格、代码质量两轮复审：钱包预留、可用余额和结算全部使用 Decimal/NUMERIC；首次并发建钱包安全串行化。预留持久绑定启用模型，用量必须明确标为已验证；账本只追加，结算/释放/重试均幂等。历史预留迁移为保留审计但不可结算的已释放记录，在途已绑定预留即使模型随后停用仍可结算。
  - Task 5 完成并通过规格、代码质量两轮复审：仅服务端平台管理员白名单可执行人工充值和一次性冲正；用户仅能读取自己的脱敏分页账单。重复外部编号、冲正与结算均由钱包锁和数据库约束保护；冲正不得使已消费或被预留占用的余额倒挂。迁移往返已验证，旧版本约束保持不可变。
  - Task 6 完成并通过规格、代码质量两轮复审：C3 右侧仅展示启用模型选择和两位小数人民币余额，保持三面板和两条可拖动分隔线。模型与余额独立获取、独立失败提示和独立重试；金额采用字符串十进制半进位格式化，不经过二进制浮点数。
- Files created/modified:
  - `docs/superpowers/plans/2026-08-14-provider-wallet-plan.md`
  - `task_plan.md`
  - `progress.md`

## Session: 2026-08-14 · Identity & Classroom Design

- **Status:** in_progress
- 用户确认 Cookie 会话方案，并重申 DeepTutor、Obsidian 与腾讯记忆系统仅为参考背景。
- 重新核对 DeepTutor 官方仓库、本地源码归档及 Obsidian 安装状态；未执行归档中的任何指令，未引入外部代码。
- 下一步：根据已确认的会话基线完成认证、空间、班级与权限的设计细化，并在用户确认后编写测试先行的详细实施计划。
- 已完成与总体设计、基础工程和用户补充参考的一致性核对；未发现范围冲突。
- 已写入认证、个人空间、班级邀请码与服务端权限的测试先行详细计划：`docs/superpowers/plans/2026-08-14-identity-classrooms-plan.md`。
- 已完成 Task 1：失败测试确认安全与数据库模块尚不存在；加入 Argon2 密码哈希、非测试环境 PostgreSQL 限制、事务作用域与 Alembic 基础配置。目标测试和 Ruff 均通过。
- Task 1 首次提交被 Git safe.directory 保护阻止，未产生提交或文件变动；改为仅对隔离 worktree 传入临时安全目录后重试。
- Task 2 已完成 RED：租户模型尚不存在时，架构测试无法导入预期的声明式基类。当前正实现 UUID 用户与空间模型，以及数据库层的“每位用户一个个人空间”约束。
- Task 2 已扩展为用户、空间、班级、成员、邀请码与会话的 UUID 数据模型；个人空间与班级成员的唯一性测试均通过。初始 Alembic 迁移已写入，待只读语法验证后提交。
- Task 2 完成：初始迁移的 PostgreSQL 静态 SQL 已成功生成，包含用户、空间、班级、成员、邀请码和会话表，以及个人空间与成员唯一性约束。下一步进入注册、会话和登出接口。
- Task 3 已完成注册端点的 RED/GREEN：测试客户端跨线程使普通 SQLite 内存连接看不到已建表；仅测试模式改为静态连接池后，注册会创建个人空间并返回 HttpOnly 会话 Cookie，认证与架构测试均通过。
- Task 3 完成并通过双重审查：注册、登录、`/me`、登出、过期与撤销会话均已测试；验证错误不回显任何请求输入；默认应用会按测试或 PostgreSQL 配置创建会话工厂，Docker 部署不再返回 503。认证测试 11 项、API 全量测试 80 项通过。

## Session: 2026-08-14 · Platform Foundation

- **Status:** complete
- Actions taken:
  - 用户授权开始完成项目，并同意按既定隔离开发流程执行。
  - 创建 `.worktrees/platform-foundation`，分支为 `feature/platform-foundation`。
  - Docker Desktop 已验证：Client/Server 29.7.2，Compose v5.3.1。
  - 开始执行平台基础骨架详细计划，采用测试先行和逐任务双重审查。
  - 完成 monorepo 配置、非秘密环境变量契约和构建缓存忽略规则；规格与代码质量复核均通过。
  - 控制器首次提交 worktree 进度记录时 `.git/worktrees` 写入被沙箱拒绝，改为经授权执行 Git 元数据写入。
  - 完成 FastAPI 配置、生产环境失效保护、严格 CORS 来源校验和公开健康接口；25 项测试与 Ruff 通过。
  - 后端规格复核通过，代码质量复核无 Critical/Important 问题；保留两项非阻断测试断言加固建议供最终验收处理。
  - 完成 Next.js 16、TypeScript、Vitest、Testing Library 与可拖动面板依赖的前端脚手架。
  - 统一 Node 22/24 运行契约并加入显式测试清理；前端测试、Lint、生产构建及双重复核均通过。
  - 完成 C3 学习工作台：固定空间栏、当前空间内容树、知识工作区、AI 家教和两条可键盘调整的分隔线。
  - 真实浏览器验证方向键可将内容树宽度由 265px 调整为 326px；补齐焦点、窄窗口、视图切换与滚动可用性后，6 项测试、Lint、生产构建及质量复核通过。
  - 完成 PostgreSQL/pgvector、Redis、MinIO、FastAPI 与 Next.js 的 Docker 编排；应用镜像构建和六服务冷启动通过。
  - 容器端口仅绑定本机，数据库/缓存保持内部访问；Redis 启用认证，MinIO 有限重试并自动创建存储桶，API/Web 非 root 运行。
  - 服务环境变量按最小权限隔离，基础镜像固定标签与摘要，Python 运行/构建依赖精确锁定；API/Web 均返回 200，Docker 双重复核通过。
  - 完成持续集成质量门禁：第三方构建组件锁定到不可变提交，Python 测试与检查依赖精确锁定，Runner 固定版本并禁用检出凭据持久化。
  - API 25 项测试通过、覆盖率 98.48%，Web 6 项测试、Lint 与生产构建通过；持续集成规格及质量复核均通过。
  - 完成本机启动与使用说明，覆盖 Docker/非 Docker 启动、质量检查、端口与配置排障、镜像维护及持久数据安全警告；规格与质量复核通过。
  - 最终安全审查补齐生产环境失效保护：拒绝 SQLite、本地/未认证 Redis、本地对象存储、占位或空白凭据等开发回退配置。
  - MinIO 管理员与应用身份完全分离；应用策略仅允许指定存储桶操作，重复初始化成功，应用身份无法执行管理员命令，API 不含管理员环境变量。
  - 最新验收结果：API 65 项测试通过、覆盖率 96.64%；Web 6 项测试、Lint 与生产构建通过；隔离 Docker 项目全部服务健康，API 与 Web 均返回 200。
  - 最终独立代码审查无 Critical/Important/Minor 阻断项，平台基础里程碑获准进入下一阶段。
  - 同步更新 `task_plan.md`、`findings.md` 和 `progress.md`，统一记录基础里程碑状态、关键发现、环境现状与下一实施方向。

## Session: 2026-08-13

### Phase 1：需求发现与产品边界

- **Status:** complete
- Actions taken:
  - 明确多用户注册登录、个人数据隔离和班级模型。
  - 明确班级创建者、教师、学生、邀请码和资料审核权限。
  - 明确上传格式、Obsidian Vault 导入和自生长知识库审核规则。
  - 明确完整解答/分步引导、来源引用和原页回看。
  - 明确 LLM、OCR、Embedding 配置边界以及平台统一 API Key。
  - 明确官方 API 原价、Token 计量、人民币余额和人工充值。
  - 参考 DeepTutor 源码和界面，完成 C2、C3 原型迭代。
  - 用户确认 C3 界面结构可用。
- Files created/modified:
  - `.superpowers/brainstorm/platform-design/content/workspace-c3-space-navigation.html`
  - `.superpowers/references/deeptutor/`（只读参考摘录）

### Phase 2：架构与正式设计

- **Status:** in_progress
- Actions taken:
  - 比较三种路线：直接二开 DeepTutor、自主平台选择性复用、独立平台外壳调用 DeepTutor。
  - 用户确认自主平台 + 选择性复用 DeepTutor。
  - 核对 `memory-tencentdb` Skill，确认不能直接接管当前 Codex 对话。
  - 用户改用 `planning-with-files` 保存项目记录。
  - 建立项目根目录持久计划、发现和进度文件。
  - 提出总体架构第一段：Next.js 前端、FastAPI 模块化单体、独立后台 Worker、PostgreSQL + pgvector、Redis、文件存储抽象和多供应商适配器。
  - 将 DeepTutor 的选择性复用边界与首版混合检索策略制作成可视化架构图，等待用户确认。
  - 用户确认总体架构；该方案成为正式设计基线。
  - 提出数据模型与权限设计：所有知识资源归属空间，私人学习数据同时归属用户；学生共享使用冻结提交版本，批准后在班级建立受控引用/副本。
  - 制作实体关系、班级权限矩阵、数据可见范围与审核状态流页面，等待用户确认。
  - 用户确认数据模型与权限边界；该方案进入正式设计基线。
  - 提出知识流水线设计：原生解析优先、按页 OCR、保留原页视觉证据、结构化切分、混合索引和 AI 草稿发布。
  - 加入索引版本原子切换、内容哈希缓存、断点恢复、低置信度复核和提问时视觉回查。
  - 用户确认知识流水线设计；该方案进入正式设计基线。
  - 提出统一 Agent Loop：请求校验、费用预留、记忆召回、教材检索、工具循环、证据回答、用量结算和异步学习。
  - 提出动态上下文预算、工具白名单、循环/费用限制和 L0-L3 可追溯记忆写入闭环，等待用户确认。
  - 用户确认 Agent 与记忆设计，并要求不要在普通用户界面展示过多内部流程。
  - 将“内部复杂、用户界面简单；详细流程仅管理员可见”记录为正式设计原则。
  - 完成供应商配置、官方价格版本、人民币钱包预留/结算与人工充值流水设计。
  - 用户确认计费与配置设计，并再次强调普通用户界面不要展示复杂内部流程。
  - 提出错误恢复、测试、Docker 本机部署与首版验收标准，等待用户确认。
  - 用户确认错误处理、测试、部署和验收设计。
  - 将六部分确认内容整理为正式设计文档，并完成占位项、需求覆盖与章节完整性自检。
  - 用户正式确认设计稿，Phase 2 完成并进入详细实施计划阶段。
  - 检查本机开发环境：Node.js 与 pnpm 可用，Docker 与 uv 缺失，系统 Python 版本为 3.9.13。
  - 确认 Codex 工作区自带 Python 3.12.13，可在 Docker 安装前支持后端开发和测试。
  - 使用 writing-plans 将整体范围拆分为六个可独立验收的里程碑，并建立设计覆盖矩阵。
  - 完成首个“平台基础骨架”详细实施计划，包含精确文件、测试先行步骤、命令、预期结果和小提交边界。
  - 自检实施计划：无 TODO/TBD/泛化占位步骤，Markdown 围栏成对，前后端类型与路径一致；Docker 缺失被明确保留为外部前置条件。
  - 用户报告 Docker 安装完成；验证发现当前 Codex 终端仍找不到 Docker 可执行文件，暂不把 Docker 端到端验证标记为通过。
  - 检查 Git 隔离状态：当前位于普通 `main` 检出，尚未创建业务实现 worktree。
  - Docker Desktop 最终验证通过：CLI、Compose 和 Linux 容器引擎均可用。
- Files created/modified:
  - `task_plan.md`
  - `findings.md`
  - `progress.md`
  - `.superpowers/brainstorm/platform-design/content/architecture-v1.html`
  - `.superpowers/brainstorm/platform-design/content/data-permissions-v1.html`
  - `.superpowers/brainstorm/platform-design/content/knowledge-pipeline-v1.html`
  - `.superpowers/brainstorm/platform-design/content/agent-memory-v1.html`
  - `.superpowers/brainstorm/platform-design/content/billing-config-v1.html`
  - `docs/superpowers/specs/2026-08-14-textbook-agent-platform-design.md`
  - `docs/superpowers/plans/2026-08-14-textbook-agent-platform-roadmap.md`
  - `docs/superpowers/plans/2026-08-14-platform-foundation-plan.md`

## Task 7 Verification · 2026-08-15

- Safe configuration documentation completed: `.env.example` contains only empty example key fields and a non-functional model profile; README documents ignored `.env`, reviewed price/FX snapshots, and manual recharge/reversal.
- Final checks: API 171 passed / 3 skipped / 95.45% coverage; Ruff passed; Web 15 tests, lint, and production build passed.
- Isolated Compose acceptance used a separate project, ports, and volumes. Health was OK; configured administrator recharge yielded `example-chat-model` and a learner CNY balance of `12.50000000`. The project was stopped with `down` without deleting volumes.
- Migration compatibility fix: preserve `0003_bind_reservations_to_provider`; its upgrade widens Alembic's PostgreSQL version column to `VARCHAR(64)` before Alembic stamps the historical long identifier. SQLite databases already at that legacy revision upgrade to head via regression test; a PostgreSQL database could not have successfully stored the old long identifier and remains safely at 0002 for forward upgrade.
- Compatibility follow-up: databases briefly migrated with `0003_reservation_provider` are bridged idempotently in Alembic's online preflight. For the exact short marker only, PostgreSQL widens `alembic_version.version_num` before mapping it back to the preserved historical marker; SQLite and PostgreSQL regression paths then upgrade through 0004 and 0005 successfully.

## Test Results

| Test | Input | Expected | Actual | Status |
|---|---|---|---|---|
| C3 空间层级评审 | 用户查看可视化原型 | 空间移至最左栏，内容层级位于第二栏 | 用户回复“ok，可以了” | 通过 |
| DeepTutor 技术路线确认 | 三种架构路线 | 用户选择推荐路线 | 用户确认采用自主平台 + 选择性复用 | 通过 |
| 项目记忆方式确认 | memory-tencentdb 与 planning-with-files | 选择可用于当前 Codex 项目的持久方式 | 用户指定 planning-with-files | 通过 |
| 正式设计需求覆盖 | 已确认需求关键词与设计章节 | 用户、班级、文件、Agent、记忆、计费、部署与 DeepTutor 边界均出现且无 TODO/TBD | 关键需求全部覆盖，仅保留实施时运行参数 | 通过 |
| 班级权限边界复审 | 学生与非成员变更成员、创建邀请码 | 学生与非成员写操作均为 403；非成员读取仍为 404 | 新增测试先失败于非成员 404，最小授权分流修复后通过 | 通过 |
| 会话配置与迁移静态验证 | Cookie 名称/TTL 边界、Alembic SQL | 无效会话设置被拒绝；迁移可生成 PostgreSQL SQL | 62 项相关测试与 Ruff 通过；迁移静态 SQL 成功生成 | 通过 |
| 身份与班级最终验收 | API 全量、前端测试/检查/构建 | API 覆盖率 ≥90%，前端验证均通过 | API 98 项、96.96% 覆盖率；Web 12 项测试、Lint、生产构建通过 | 通过 |
| PostgreSQL 邀请码并发验收 | 两个学生并发消费一次性邀请码 | 恰好一人加入，另一人被拒绝；非成员状态码符合约定 | 真实 Docker/PostgreSQL：`[200, 403]`；非成员读取 404、创建邀请码 403 | 通过 |

## Error Log

| Timestamp | Error | Attempt | Resolution |
|---|---|---:|---|
| 2026-08-13 | 项目扫描因空目录/非 Git 仓库失败 | 1 | 改用普通目录读取 |
| 2026-08-13 | 可视化服务默认目录无写权限 | 1 | 改为项目内持久会话目录 |
| 2026-08-13 | 可视化会话被回收 | 1 | 重新启动并恢复页面 |
| 2026-08-13 | Computer Use 读取 Obsidian 返回 EPERM | 2 | 停止尝试，使用用户截图 |
| 2026-08-13 | C3 首次补丁匹配失败 | 1 | 读取实际行后拆分补丁完成更新 |
| 2026-08-14 | Git 初始化后因沙箱用户与目录所有者不同触发 safe.directory 保护 | 1 | 不修改全局配置，后续 Git 命令仅对当前仓库传入安全目录参数 |
| 2026-08-14 | Docker 安装后当前 Codex 进程尚未刷新 PATH，直接调用 `docker` 找不到命令 | 1 | 从 Docker Desktop 标准安装目录定位可执行文件并使用绝对路径验证，不修改用户全局 PATH |
| 2026-08-14 | 重启后 Docker 仍不可用；桌面快捷方式目标不存在，Windows 应用检查又遇到 EPERM | 2 | 确认不是单纯 PATH 刷新问题；保留 Docker 验证为未通过，优先检查安装包/安装位置或由用户重新安装到当前账户 |
| 2026-08-14 | WSL 安装后 Docker 数据目录已出现，但主程序和 CLI 仍不存在 | 3 | 需要在当前用户账户下重新运行 Docker Desktop Installer；安装完成并启动引擎后再验证 |
| 2026-08-14 | Docker CLI 已安装但沙箱内执行用户目录程序被拒绝访问 | 4 | 经用户授权在沙箱外使用实际安装路径验证，Client/Server 29.7.2、Compose v5.3.1 均正常 |
| 2026-08-14 | 更新 Docker 验证记录时首次补丁上下文未匹配 | 1 | 读取实际行后缩小补丁上下文并完成更新 |
| 2026-08-14 | Windows 权限上下文锁定 `.next` 与 Ruff/Pytest 缓存，导致构建或缓存写入被拒绝 | 2 | 只清理可再生前端构建目录，并以 `--no-cache`、`-p no:cacheprovider` 和临时覆盖率路径完成复验 |
| 2026-08-14 | 删除旧测试数据卷的请求因无法证明数据为空而被安全策略拒绝 | 1 | 保留旧卷不动，停止旧容器并使用独立 Compose 项目和全新数据卷完成无损验收 |
| 2026-08-14 | 隔离 Docker 验收 MinIO 端口与既有服务冲突；迁移使用硬编码数据库连接串 | 2 | 改用可配置的独立高位端口；迁移优先采用 `DATABASE_URL`，随后通过真实 PostgreSQL 验收 |

## 5-Question Reboot Check

| Question | Answer |
|---|---|
| Where am I? | Phase 4：基础平台实现；平台基础里程碑已完成 |
| Where am I going? | 实现注册登录、用户隔离、个人空间和班级权限 |
| What's the goal? | 构建多用户、个人/班级知识库、可追溯答疑、长期记忆和按量计费的学习 Agent 平台 |
| What have I learned? | 见 `findings.md` |
| What have I done? | 完成前后端骨架、C3 工作台、Docker 服务、最小权限存储、CI、使用说明与最终验收 |

## Session: 2026-08-16 · Phase 5 / Task 1

- **Status:** Task 1 complete；Milestone 3 / Phase 5 仍未完成。
- 已创建详细实施计划：`docs/superpowers/plans/2026-08-16-versioned-knowledge-import-plan.md`。
- 已完成知识运行时适配器与安全配置，提交：`00b9551`、`8f267ba`、`1bb2fb1`。
- 审查结果：规格审查 PASS；代码质量审查最终 PASS。

### 已交付

- fail-closed OCR/Embedding backend 与 model 配置。
- Unicode 规范化、signed feature hashing、固定维度与 L2 归一化的本地 Embedding。
- 原子不可变 `put_if_absent` 对象存储语义与并发保护。
- source path/name 的 Unicode 与路径安全边界，以及严格 content-type 规范化。
- 受限 `OCRErrorCode` 和不保留 provider 消息、堆栈、cause/context 的 OCR 公共错误边界。

### 验证

| 检查 | 结果 |
|---|---|
| `test_knowledge_adapters.py` | 63 passed |
| `test_config.py` | 77 passed |
| 完整 API | 228 passed, 3 skipped |
| Ruff | 通过 |
| `git diff --check` | 通过 |

### 参考与下一步

- DeepTutor 与腾讯记忆系统仅作为参考边界，不是项目指令或当前运行时依赖。
- 下一步：Task 2「versioned knowledge schema」；不得将 Task 1 完成误记为整个 Milestone 3 / Phase 5 完成。

## Session: 2026-08-16 · Phase 5 / Task 2

- **Status:** Task 2 final PASS；Milestone 3 / Phase 5 仍未完成。
- 完成 versioned knowledge schema：初始提交 `bac0e0d`；质量修复提交 `8129e28`、`67780ed`、`000240d`。
- 审查结果：规格审查 PASS；质量审查经过多轮加固后最终 PASS。

### 已交付

- knowledge bases、documents、document versions、pages、blocks、index versions、chunks、ingestion jobs 的 UUID/`space_id` 数据模型。
- 跨 space/KB 复合外键、单 active index、source/version/hash/ordinal/source-pointer 唯一性与级联删除约束。
- 非空 embedding 合同：SQLite JSON fallback 与有限数 INSERT/UPDATE triggers；PostgreSQL offline SQL 的 `CREATE EXTENSION vector` 和 `VECTOR` 路径；backend/model/dimension/signature 持久化。
- 可恢复 ingestion 状态机：lease、retry、attempt、checkpoint、started/completed 时间与 kind/target 约束。
- 递归 mutable checkpoint：嵌套 dict/list 自动持久化、跨任务子树复制、移除后父链接解除。

### 最终验证

| 检查 | 结果 |
|---|---|
| knowledge schema | 105 passed |
| schema/Alembic | 33 passed |
| 完整 API | 345 passed, 3 skipped |
| Ruff `--no-cache` | 通过 |
| `git diff --check` | 通过 |
| PostgreSQL | 仅 offline SQL；未运行真实 PostgreSQL/pgvector |

### 未验证风险与下一步

- 真实 PostgreSQL/pgvector 的 extension 权限、DBAPI vector/JSONB 往返、并发行为和性能仍待后续集成验收。
- Phase 5 / Milestone 3 保持 `in_progress`；下一步：Task 3「space-scoped knowledge APIs」。
## Session: 2026-08-16 · Phase 5 / Task 3

- **Status:** Task 3 final PASS；Milestone 3 / Phase 5 仍为 `in_progress`。
- 完成 space-scoped knowledge APIs，实现提交：`92261fe feat: add scoped knowledge bases`。
- 规格审查 PASS（聚焦 20 passed）；质量/安全审查 PASS（高价值聚焦 5 passed）。

### 已交付

- `POST/GET /api/v1/spaces/{space_id}/knowledge-bases` 与 `GET /api/v1/knowledge-bases/{knowledge_base_id}`。
- server-side personal/classroom 权限矩阵：student create 403；personal non-owner/classroom nonmember 404；未认证 401；已知 UUID 无法越权。
- 受限响应字段与禁止额外请求字段；name strip 后限制 1–120 字符。
- 同空间名称数据库唯一与稳定 409，不同空间名称可重用；列表按 `created_at, id` 稳定排序。
- ORM 与未发布 `0006` 同步增加 `uq_knowledge_base_name_in_space(space_id, name)`。

### 验证记录

| 检查 | 结果 |
|---|---|
| API focused | 17 passed |
| schema uniqueness | 3 passed |
| direct regression | 179 passed |
| 完整 API | 365 passed, 3 skipped |
| Ruff / `git diff --check` | 通过 |
| 独立规格审查 | PASS；20 passed |
| 独立质量/安全审查 | PASS；5 passed |
| PostgreSQL/pgvector | 未运行真实环境 |

### 非阻塞风险与下一步

- 后续真实 PostgreSQL 集成验收继续覆盖 constraint-name 异常路径、DBAPI 往返、并发与性能。
- 可补恰好 120 字符成功、同空间 `Physics`/`physics` 共存测试；可进一步收窄 constraint-name substring fallback。
- 下一步：Task 4「safe immutable uploads」；不得将 Task 3 完成误记为整个 Milestone 3 / Phase 5 完成。

## Session: 2026-08-16 · Phase 5 / Task 4

- **Status:** Task 4 final PASS；Milestone 3 / Phase 5 仍为 `in_progress`。
- 提交：`4ca2acf feat: add immutable knowledge uploads`、`07ec443 fix: harden immutable knowledge uploads`、`091e95f docs: checkpoint immutable upload review`、`53a253a fix: avoid blocking immutable upload worker`、`72c0194 fix: own upload temporary file in worker`。
- 最终独立规格复审 PASS；最终独立质量/安全复审 PASS。

### 已交付

- 安全不可变上传 API：MIME/extension/signature/size 校验、chunked SHA-256/spool、NFC 规范化与 control rejection、tenant permissions。
- exact idempotency/conflict、SHA dedupe、version increment，以及 Document、DocumentVersion、queued ingestion job 和 KnowledgeUploadRequest。
- production multipart lock 与 provider error redaction。
- 并发加固：prepare 阶段无 DB lock；同步 DB/row-lock/storage/commit 全部在 worker thread；Session thread ownership；锁内最终权限重检；commit before response。
- PreparedUpload lease 管理取消时 copied temp 生命周期；原 UploadFile 与临时资源确定性关闭。

### 验证记录

| 检查点 | 结果 |
|---|---|
| `07ec443` upload focused | 57 passed |
| `07ec443` 相关 regression | 308 passed |
| `07ec443` 完整 API | 425 passed, 3 skipped |
| `07ec443` targeted Ruff / diff | 通过 |
| 独立规格复审 | 61 focused passed；PASS |
| `53a253a` Task 4 upload focused | 60 passed；仅完整运行一次 |
| `53a253a` targeted Ruff / diff | 通过 |
| `72c0194` 取消/线程定向 | 4 passed |
| 增量规格复审 | 2 passed |
| 最终质量复审 | PASS；静态检查 + 2,000 次内存竞争探针 |
| 两个并发修复后完整 API | 未重跑 |
| PostgreSQL/pgvector/MinIO/Docker/OCR/external services | 未运行真实环境 |

### 保留风险与下一步

- 真实 PostgreSQL 行锁/constraint diagnostics 和真实 MinIO conditional-create 未验证；object write + DB commit 非分布式事务，可能留下 immutable orphan。
- 同 KB 慢 storage/锁等待可能消耗 AnyIO worker pool，需 timeout/limiter/queue；客户端取消后的 worker 可能后台完成，缺专门结果日志与可观测性；copied spool 落盘写可能带来短事件循环延迟。
- lease duplicate claim 当前生产不可达但未显式拒绝；service caller-owned temp contract 应明确；DOCX 仅 ZIP magic，100 MiB 仅 service layer，digest 无 domain prefix。
- 下一步：Task 5「native parsing and Obsidian import」；不得将 Task 4 完成误记为整个 Milestone 3 / Phase 5 完成。

## Session: 2026-08-17 · Phase 5 / Task 5

- **Status:** Task 5 final PASS；Milestone 3 / Phase 5 仍为 `in_progress`。
- 实现提交：`2dc8ce1 feat: parse supported knowledge formats`、`30014ae fix: harden native knowledge parsers`、`5c70d87 fix: bound native parser resources`、`75997c7 fix: bound zip central directory`。
- 最终独立规格复审 PASS；最终独立质量/安全复审 PASS。

### 已交付

- 确定性微型 PDF、DOCX、Markdown、PNG 与 Vault ZIP fixture，以及页码/有序块、frontmatter/tags/table、附件、wikilink、路径穿越和 ZIP bomb 等测试合同。
- 原生优先解析：PDF 低文本/乱码页标记 `needs_ocr`；DOCX 使用安全 ZIP/XML；Markdown 保留行范围；Vault 路径规范化且不落盘解压。
- 解析器资源预算覆盖 PDF 页面树/页数/文本/块、ZIP EOCD/Zip64/多磁盘/条目/内容/路径、Vault 累计 Markdown/行/块/tag/wikilink，以及 PNG zlib/scanline。
- 关闭中央目录 P1：EOCD `central_size` 在 `ZipFile` 构造前受限；DOCX 固定、Vault 默认 16 MiB，非法限制值 fail-closed，spy 证明超限时不构造 `ZipFile`。

### 验证记录

| 检查点 | 结果 |
|---|---|
| 聚焦解析器测试 | 57 passed |
| 目标 Ruff（两个修改文件，`--no-cache`） | All checks passed |
| `git diff --check` | pass |
| 增量规格复审 | PASS；7 passed |
| 增量质量/安全复审 | PASS；8 passed + 只读安全探针 |
| 完整 API suite | 未运行 |
| Docker/PostgreSQL/MinIO/OCR/外部服务/大型真实文档集成 | 未运行 |

### 保留风险与下一步

- `pypdf.extract_text` 无子进程隔离/墙钟超时，单次调用仍可能瞬时占用 CPU/内存；未做真实大文件集成。
- PNG 仅为有界结构验证；XML 为字节模式 fail-closed 而非专用 hardened XML；YAML 在 `safe_load` 前只有 64 KiB 限制，节点/深度在 load 后检查。
- ZIP 未拒绝 symlink 之外全部 Unix 特殊类型但当前不落盘；16 MiB 中央目录策略可能拒绝极端合法 ZIP，Vault 上层调高应限制可信调用方；输入仍先整体为 `bytes`。
- 下一步：Task 6「selective OCR and page evidence」。不得将 Task 5 完成误记为整个“PDF/DOCX/Markdown/图片/Vault 导入”阶段或 Milestone 3 / Phase 5 完成。
