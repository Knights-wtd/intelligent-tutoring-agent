# Progress Log

## Session: 2026-08-27 · Knowledge Index Build Fix & Persistence Verification

- **Status:** complete
- Actions taken:
  - 诊断“PDF 上传后一直显示上传中”：解析（parse_document）实际成功，卡在 build_index 重试 3 次后终态失败。真实根因经容器内回放探针定位：本 PDF 解析出 104 个纯标点碎片块（如 `} }]`），嵌入器 `_normalize_text` 将其判为空文本抛 ValueError，而 `build_index` 捕获一切异常并以 `from None` 吞掉细节统一报 `index_build_failed`，worker 又固定写 `last_error_detail=None`。
  - 修复：以 `is_embedding_blank` 作为嵌入空白判定的唯一标准（embeddings.py 抽取共享规则）；索引构建加载块阶段过滤空白块（indexing.py），纯标点文档改报稳定的 `index_source_empty`；worker 失败时向 stderr 打印完整堆栈（数据库仍只保留脱敏公开错误码）。
  - 测试先行：新增 2 个回归测试（含标点碎片的构建必须成功、无可嵌入文本须报 index_source_empty），RED→GREEN；test_knowledge_indexing 22/22、知识库相邻套件全绿、ruff 通过。基线对照证明仓库现存 4 个与本改动无关的失败：schema 迁移往返 ×2（question_versions 元数据/迁移漂移，属题库 WIP）、OCR tesseract 超时杀进程 ×2（本临时容器环境确定性失败，两变体均复现）。
  - 部署与恢复：重建 api/worker 镜像并滚动替换；将两条失败的 build_index 任务重置为 queued（attempt_count=0、清租约），修复后一次尝试即完成，两个知识库索引激活、各 12958 chunks；`search_knowledge("智能体的规划和记忆模块")` 端到端返回带页码引用命中（p154/p147/p16）。
  - 持久化核实：文档元数据/pgvector 向量存于 `ita_repo_postgres-data` 卷；11MB PDF 原件与每份 306 个页文本对象经应用存储适配器从 MinIO 卷完整读回。命名卷跨重启/重建持久；需防 `docker compose down -v`。UI 层状态映射本身区分 FAILED，缺的是任务状态轮询接口（后续项：GET 文档/任务状态端点 + 前端轮询）。
- Files created/modified:
  - `apps/api/src/tutor_api/knowledge/embeddings.py`
  - `apps/api/src/tutor_api/knowledge/indexing.py`
  - `apps/api/src/tutor_api/knowledge/worker.py`
  - `apps/api/tests/test_knowledge_indexing.py`
  - `progress.md`

## Session: 2026-08-27 · Auth Fixes, Rate Limiting & Web API Base Repair

- **Status:** complete
- Actions taken:
  - 实现需求缺口「用户名或邮箱登录」：`LoginRequest` 改为 `identifier` 字段（`AliasChoices` 兼容旧 `email` 字段与前端存量调用），含邮箱 casefold 与用户名格式校验。
  - 修复用户名仿冒缺陷：注册时用户名统一 casefold，`TEACHER-E2E` 与 `teacher-e2e` 现在冲突返回 409。
  - 新增登录失败限流 `identity/rate_limit.py`（进程内滑动窗口）：已知账号按 user_id 计数（邮箱/用户名变体无法重置计数），未知标识符按 identifier@IP；默认 5 次失败锁 15 分钟，返回 429 + Retry-After；成功登录清零计数。配置项 `LOGIN_MAX_ATTEMPTS`/`LOGIN_LOCKOUT_SECONDS` 可调，fail-open 防止内存表膨胀影响可用性。
  - 新增过期/撤销会话清理：登录时以 `SESSION_PURGE_PROBABILITY`（默认 5%）概率清除过期会话与撤销超 7 天的会话。
  - 修复部署级缺陷：前端所有 fetch 使用相对路径但 Next 无转发配置，`NEXT_PUBLIC_API_BASE_URL` 构建变量从未被使用，浏览器端所有 API 请求 404。新增 `lib/api-base.ts` 统一前缀，5 个 lib 文件全部接入。
  - 修复 Web CI 失败根因：`workspace-shell.tsx` 引用的 `@/lib/classrooms-api` 在 `2d30f6f` 中被引用但文件从未提交；按 `knowledge-api.ts` 模式补建（create/join + 类型对齐 `SpaceSummary`）。
  - lint 清零：ruff 16 项错误清零（部分由远端 `2d30f6f` 修复，剩余 import 排序自动修复，自引 B905 手工修复）。
  - 测试：`test_auth.py` 新增 6 个场景（用户名登录/大小写归一、非法标识符、锁定与解锁、成功清零计数、会话清理），17/17 通过；前端新增 identifier 用例，111/111 通过；全量后端 655 passed（4 个预存失败：2 Windows OCR + 2 迁移漂移，与本次无关）。
  - 已验证运行栈：用户名/大写用户名/旧字段登录均 200；限流 429 + Retry-After 生效且账号级封锁无法用邮箱变体绕过；Web 镜像重建后登录页渲染「邮箱或用户名」字段。
  - 部署注意：后端 CORS 仅允许 `WEB_ORIGIN`（默认 `http://localhost:3000`），用 `127.0.0.1:3000` 访问会被浏览器 CORS 拦截。
- Files created/modified:
  - `apps/api/src/tutor_api/identity/schemas.py` `router.py` `rate_limit.py`（新）
  - `apps/api/src/tutor_api/core/config.py` `apps/api/src/tutor_api/main.py`
  - `apps/api/tests/test_auth.py`
  - `apps/web/src/lib/api-base.ts`（新）`api.ts` `classrooms-api.ts`（新）`knowledge-api.ts` `tutor-api.ts` `question-bank-api.ts`
  - `apps/web/src/components/auth/auth-form.tsx` `auth-form.test.tsx`
  - `progress.md`

## Session: 2026-08-27 · Compose E2E Acceptance & pgvector Index Fix

- **Status:** complete
- Actions taken:
  - 对运行中的 Compose 栈执行端到端验收：注册/登录（HttpOnly Cookie）、个人空间、班级创建、受限邀请码（有效期/次数）、学生加入、知识库创建、PDF 与 Markdown 上传（需 `Idempotency-Key` 头）、异步入库、带引用检索、引用令牌原页/源文件预览（206）、越权访问返回 404、模型目录与账单读取，全部通过。
  - 发现并修复阻塞级缺陷：pgvector `vector` 列以 float32 存储，`HashEmbeddingAdapter` 输出 float64，`_validate_persisted_index` 用 `!=` 严格比较回读向量，128/128 个非零分量必然失配，导致 `build_index` 任务重试 3 次后 `index_validation_failed`、事务回滚、chunks 为 0、检索永远返回空。修复为按 float32 精度（`math.isclose`，abs_tol=1e-6）比较（`apps/api/src/tutor_api/knowledge/indexing.py`）。
  - 修复后重新排队失败任务：两个 `build_index` 完成、索引版本 active、5 个分块入库、检索按相关度正确返回 PDF 首位结果。`tests/test_knowledge_indexing.py` 20/20 通过。
  - 已知限制（与 README 一致）：tutor 会话返回 `tutor_provider_unavailable`（`/api/v1/tutor/status` 显示 `configured: false`，未配置真实 LLM 凭据）；知识图谱端点返回空（测试数据无跨文档链接）；Markdown 上传要求客户端显式发送 `text/markdown` 内容类型，curl 默认 `application/octet-stream` 会被拒绝；Worker 容器无任何日志输出，失败原因只能查库（`last_error_detail` 为空），可观测性待改进。
- Files created/modified:
  - `apps/api/src/tutor_api/knowledge/indexing.py`
  - `progress.md`

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

## Session: 2026-08-17 · Phase 5 / Task 6

- **Status:** Task 6 final PASS；Milestone 3 / Phase 5 仍为 `in_progress`。
- 交付提交：`e2e2a6b feat: add selective page OCR`、`d9f244d fix: bound selective OCR resources`、`5225691 fix: close OCR lifecycle gaps`。
- 初始完整规格复审 PASS；最终独立增量规格复审 PASS；最终独立质量/安全复审 PASS。

### 已交付

- 选择性 OCR：仅 PNG 与 `needs_ocr=True` PDF 页进入 OCR；PDFium 子进程按需渲染，Tesseract adapter 处理页面，默认 backend disabled。
- immutable evidence/checkpoint/result，保留 page number、block order 与 source pointer；支持 partial failure checkpoint，并对 provider error 做稳定映射和脱敏。
- 单页 pixel/language/per-call output/input/time 上界，以及 document-level page/evidence/text/deadline 累计预算；subprocess stdout 有界。
- 统一 `Popen` 后清理边界；Windows suspended + Job containment/fail-closed，移除 PID-tree fallback；POSIX process-group 静态路径；进程、pipe、I/O thread 与 handle 确定性清理。
- 所有 adapter 使用 `timeout_seconds/remaining` 合同，legacy adapter body 前 fail-closed；stdin-only descendant deadline 映射为 `TIMEOUT`。
- Dockerfile 在 non-root `USER` 前安装 English 与 Simplified Chinese Tesseract runtime 包。

### 验证记录

| 检查点 | 结果 |
|---|---|
| `d9f244d` 后 OCR / adapter OCR / parser | 44 / 10 / 57 passed |
| `5225691` 后 `test_knowledge_ocr.py` | 49 passed |
| `test_knowledge_adapters.py -k ocr` | 10 passed |
| `test_knowledge_parsers.py` | 57 passed |
| targeted Ruff | PASS |
| `git diff --check d9f244d..5225691` | PASS |
| 最终独立增量规格复审 | PASS；reviewer 11 focused passed |
| 最终独立质量/安全复审 | PASS；reviewer 7 focused passed |
| 生命周期探针 | 10× BrokenPipe 均 `PROCESSING_FAILED`；Windows Job handle 精确关闭 1 次；预热后 success 3×20 / timeout 3×10 handle 稳定、OCR I/O threads 归零 |
| 完整 API suite | 未运行 |
| 真实 Tesseract/container smoke、Docker、PostgreSQL、MinIO、外部服务 | 未运行 |
| POSIX 实机 process-group、复杂 PDFium corpus | 未运行 |

### 保留风险与下一步

- 未运行真实 Tesseract/container smoke；POSIX process-group 路径未在实机执行，主动 `setsid`/改组 descendant 可逃离。
- 未运行复杂 PDFium corpus；PDFium child 无 OS 级地址空间上限。每个 PDF OCR 页仍 spawn 并复制完整 PDF bytes，输入仍整体以 `bytes` 进入。
- 安全预算可能拒绝极端合法页面；executable 必须为可信配置。
- deadline-aware adapter 属于受信任 port 合同；若 adapter 声明支持但忽略 timeout，当前调用方无法强制终止。
- Windows Job Assign 依赖 CPython `Popen._handle` 私有属性，需要随 Python 版本复核。
- POSIX 强制 SIGKILL 位于第一次 bounded join 后，daemon I/O thread 理论上可能极短暂存活，但未观察到持久或线性泄漏。
- 下一步：Task 7「immutable indexing and reliable worker」。不得将 Task 6 完成误记为整个导入阶段或 Milestone 3 / Phase 5 完成。

## Session: 2026-08-18 · Phase 5 / Task 7

- **Status:** Task 7 final PASS at code HEAD `363f3fb`; Milestone 3 / Phase 5 remains `in_progress`.
- Delivery commits: `f298eb2 feat: build knowledge indexes reliably`, `96a3ad6 fix: close reliable indexing gaps`, `53284ca fix: harden reliable indexing delivery`, `cfc6220 fix: serialize ready index snapshots`, `0d34b2a fix: requeue changed embedding contracts`, `363f3fb fix(api): allow blank OCR pages`.
- Prior independent specification review at `0d34b2a` PASS. Initial quality review FAIL had one disproved production-HTTP concern and one valid blank OCR page issue; `363f3fb` repaired the valid issue. Post-fix independent specification PASS (34 focused) and independent quality PASS.

### 已交付

- immutable contract-bound build targets；heading-aware bounded chunks 与 exact hash reuse。
- building index 持久化 source page/block pointers、lexical terms、vectors、embedding model/dimension/signature 与 hashes。
- atomic validation/activation；replacement 成功前保留 old active index，失败构建不会中断现有 active。
- database leases、PostgreSQL `FOR UPDATE SKIP LOCKED`、stale recovery、bounded retry、restart-safe idempotency，以及复用 API image 的 Compose worker。
- S3 redirect/object bounds 与 nonlocal production HTTPS gate；parse terminal state 和 started/completed timestamps。
- OCR fail-closed；允许 blank completed OCR page 的唯一例外是 document 仍保留内容。
- READY snapshot knowledge-base lock ordering；adapter contract drift terminalize stale unactivated target，并幂等创建或复用 current-contract replacement job。

### 验证记录

| 检查点 | 结果 |
|---|---|
| Task 7 相关八文件 combined focused set | 362 passed, 36 warnings |
| migration nodes | 3 passed, 4 warnings |
| targeted Ruff | All checks passed |
| `git diff --check aa71123..HEAD` | PASS |
| 独立规格复审 | `0d34b2a` PASS；`363f3fb` 后 PASS，34 focused passed |
| 独立质量复审 | 初始 FAIL；production-HTTP 项证伪，blank OCR page 项修复后最终 PASS |
| Windows OCR timing observation | 历史 combined run 两个 1 秒 PID-file timing failure；精确两项和完整 OCR 分别 PASS；最终 362 combined PASS，非阻塞 |
| 完整 API suite after Task 7 | 未运行 |
| Docker / real PostgreSQL-pgvector / MinIO-S3 / Redis | 未运行 |
| Tesseract-PDFium corpus / external services / live POSIX process group | 未运行 |

### 保留风险与下一步

- transaction/job lock 在 long external handler 运行期间保持；这是非阻塞质量残余，后续可缩短事务或拆分 handler 生命周期。
- bounded S3 PUT 最多缓冲到配置的最大对象大小；有界但仍可能产生较高单请求内存峰值。
- 当前验证不替代真实 PostgreSQL/pgvector、对象存储、队列、容器和 OCR corpus 集成验收。
- 下一步为 Task 8「hybrid retrieval and secure source preview」；Task 8 尚未开始。不得将 Task 7 final PASS 误记为 Milestone 3 / Phase 5 完成，也不在本记录中创建最终 handoff。

## Session: 2026-08-18 · Phase 5 / Task 8

- **Status:** Task 8「hybrid retrieval and secure source preview」最终 PASS；Milestone 3 / Phase 5 仍为 `in_progress`。
- **代码提交：**`e219bdf feat: add cited knowledge retrieval`、`11f1aa4 fix: persist cited page previews`、`13c9d15 fix: preserve reliable retrieval recall`。
- **复审：**初始规格 FAIL（真实 ingestion 未生成 preview object）后修复；复审规格 PASS。初始质量 FAIL（embedding contract 混用、首 1000 行截断漏召回）后修复；最终独立规格 PASS、质量/安全 PASS。
- **验证：**页面预览修复聚焦组合 45 passed；最终检索可靠性修复后 retrieval/source/indexing 组合 31 passed；targeted Ruff PASS；`git diff --check` PASS。
- **交付：**ACTIVE-only hybrid RRF、embedding 合同安全降级、完整索引有界候选 heap、opaque citation、真实解析预览持久化、授权先于对象读取、bounded Range 与 provider error redaction。
- **保留风险：**完整 ACTIVE index 流式扫描的内存有界，但 CPU/数据库行读取线性增长；尚未运行 production-scale benchmark、真实 PostgreSQL/pgvector top-k、Docker vertical slice。
- **下一步：**Task 9「C3 knowledge panel」。不得将 Task 8 完成误记为 Phase 5 完成。

## Session: 2026-08-18 · Phase 5 / Task 9

- **Status:** Task 9「C3 knowledge panel」final PASS; Phase 5 / Milestone 3 remains `in_progress`.
- **Commits:** `7a03e5c`, `27fa8f5`, `3f81af4`.
- **Review loop:** initial independent spec review found premature searchable state and missing explicit `文件` hierarchy; both repaired. Initial quality/security review found nonfunctional cancellation and duplicate-upload/file-selection races; repaired. Final independent SPEC PASS and QUALITY PASS.
- **Verification:** focused Web test command passed 7 files / 34 tests; `pnpm lint:web` PASS; `pnpm build:web` production compile, TypeScript, and static generation PASS; diff checks PASS.
- **Next:** Task 10 end-to-end verification and delivery records. Do not mark Phase 5 complete until deterministic fixture coverage and isolated Docker vertical slice both pass.
## Session: 2026-08-18 · Phase 5 / Task 10 verification

- **Status:** incomplete / environment-blocked. Milestone 3 / Phase 5 remains `in_progress`; no completion checkbox or final delivery commit is claimed.
- **Feasible Web checks:** `pnpm test:web` PASS (7 files / 34 tests); `pnpm lint:web` PASS; `pnpm build:web` PASS (production compile, TypeScript, static generation) after the sandbox-only `.next\trace` permission denial was removed.
- **Feasible API checks:** `ruff check --no-cache src tests` PASS. Full coverage command (with coverage file in `%TEMP%` and pytest cache disabled) ran 595 tests: **590 passed, 3 skipped, 2 failed**; total coverage **88.08%**, below the configured 90% gate. Both failures were Windows OCR descendant-timeout PID-file assertions; no unrelated source change was made. `alembic heads` reports `0008_embedding_contract (head)` only.
- **Runtime gates:** Docker CLI/Desktop and local PostgreSQL tools (`psql`, `pg_isready`, `initdb`) are absent. Consequently the isolated PostgreSQL/pgvector migration round-trip and the required Compose flow (register → KB → Markdown/PDF upload → READY → search → cited page) were not run.
- **Format evidence / limits:** Tests use deterministic in-memory PDF, DOCX, Markdown, JPEG, PNG, and Obsidian ZIP inputs; upload tests cover all accepted suffixes including `.jpg` and `.jpeg`, but no binary fixtures are checked in. Safe defaults are 100 MiB upload, 5,000 Vault files, 500 MiB decompressed Vault data, disabled-only OCR, and `hash / feature-hash-v1 / 384` embeddings; no remote provider is configured.
- **Next blocker:** provide a usable Docker Desktop/Compose runtime (or an isolated real PostgreSQL/pgvector environment) and stabilize or otherwise resolve the two full-suite OCR timing failures plus the 90% coverage gate before rerunning Task 10. See `docs/superpowers/handoffs/2026-08-18-task10-verification-blocked.md`.
- **Documentation self-review:** corrected the Compose wording to the actual knowledge-override mapping behavior and distinguished the OCR_LANGUAGES default from the runtime OCR helper allowlist; completion state is unchanged.

## 2026-08-21 · MVP 主链路收口实现批次

- **Status:** in_progress
- **范围：** 诚实移除未实现的 AI Tutor/模型/余额/费用界面；接入最小题库学习者 UI；新增仅含公开处理状态的资料状态读取并在知识库面板提供刷新。
- **约束：** 仅 feature worktree；不启动 Docker/Compose/Alembic、全量测试、coverage、真实外部 API/LLM；不 stage/commit/reset/stash/checkout；API 测试仅使用 `apps/api/.venv/Scripts/python.exe -B` 及 `PYTHONDONTWRITEBYTECODE=1`。
- **验证计划：** 新增/紧邻 API 上传测试、三项工作台 focused Vitest、targeted Ruff/ESLint/tsc；完成后再一次性进行 SPEC 与 QUALITY/SECURITY 审查。
## 2026-08-21 · MVP 复审窄修复

- **Status:** implementation and focused verification complete; no Docker/Compose/Alembic/full-suite run.
- **Upload response boundary:** `KnowledgeUploadResponse` and upload route expose only `document_id`, `document_version_id`, `source_name`, and `created_at`. The learner-facing processing state stays behind the authorised document-status endpoint; the Web DTO and focused API/Web tests no longer use internal job/hash/space/knowledge-base/state fields.
- **Question-bank races:** active submit/history requests are aborted and sequence-invalidated before a question or knowledge-base change; both loading flags reset at that boundary. The client retains one idempotency key for the same knowledge-base/question/trimmed answer retry, and invalidates it when the question, knowledge base, or answer changes.
- **Knowledge status refresh:** refresh controllers are now tracked per upload entry. Different files refresh concurrently; replacing one entry refresh cannot clear or strand the other entry's loading state. A context change aborts and clears all visible refresh flags safely.
- **Focused verification:** API upload tests `61 passed`; targeted Ruff PASS; Web focused Vitest `3 files / 22 tests` PASS; target ESLint PASS; TypeScript `tsc --noEmit --incremental false` PASS; `git diff --check` PASS. The only test-run note was Vite's existing future config-loader warning.
- **Git hygiene:** no `git add`, `commit`, `reset`, `stash`, checkout, Docker, Alembic, external API, coverage, or full test suite was run. Existing unrelated worktree changes remain preserved.

## 2026-08-21 · MVP 复审最后窄修复

- 修复题库答题成功后 `review-items` 刷新失败会提前清空幂等键的问题：答案与 `(knowledge_base_id, question_version_id, normalized_answer)` 对应的 key 会保留到 review 刷新成功；用户在未修改答案时重试会复用原 key。
- 提交成功但 review 刷新失败时，界面保留成功评估和答案，并显示准确提示“答案已提交，但待复习列表刷新失败，请稍后重试。”；不再误报为提交失败。
- focused regression 覆盖“提交成功 → review-items 失败 → 再次提交复用同一 key”。
- 验证：question-bank-panel focused 4 passed；目标 ESLint PASS；TypeScript 非增量检查 PASS。未运行 Docker、Alembic 或全量测试。

## 2026-08-21 · Obsidian 风格工作台接入

- 将高保真 C3 原型的品牌侧栏、空间列表、顶部栏、内容树、三栏可调布局、上下文面板和底部状态栏接入 `apps/web/src/components/workspace/workspace-shell.tsx` 与对应 CSS。
- 中间区域继续复用现有 `KnowledgePanel` 和 `QuestionBankPanel`；右侧改为诚实的 MVP 上下文说明，没有重新引入未实现的 AI Tutor、模型余额或费用承诺。
- 初次 focused 测试因 Tab 增加副标题导致可访问名称变化；通过显式 `aria-label` 修复，最终 Web 8 files / 35 tests、ESLint、TypeScript 均通过。
- 生产构建失败：Next.js 无法写入 `apps/web/.next/trace-build`，错误为 Windows `EPERM`；这是当前生成目录权限问题，尚未删除目录或改变权限。

## 2026-08-21 · 登录入口样式修复

- 浏览器预览确认实际页面处于匿名状态，`AuthForm` 原先没有任何样式，因此显示为浏览器默认 HTML；为其新增 `auth-form.module.css`，接入与工作台一致的深色登录卡片。
- 初次视觉改造将标题改为“欢迎回来”，导致既有匿名页测试无法找到“登录”标题；已恢复“登录/注册”语义标题，并保留欢迎说明作为副标题。
- 最终 Web 全量验证：8 个测试文件、35 个测试通过；ESLint、TypeScript 通过；浏览器刷新后 CSS 正常显示。

## 2026-08-21 · 注册链路故障修复

- 诊断确认 `127.0.0.1:8000` 未运行，且 Web `api.ts` 使用相对 `/api/v1/...` 路径，导致请求落到 Next.js 3000 端口并返回 404。
- 已让 API client 读取 `NEXT_PUBLIC_API_BASE_URL`，并以 `http://127.0.0.1:8000` 启动本地 Web；FastAPI health 200、Web 200。
- 最终 Web 验证：8 个文件 / 36 个测试通过；ESLint、TypeScript 通过。

## 2026-08-21 · 旧 Worker 更新

- 发现 `mvp-phase6-20260821-worker-1` 使用旧的 `textbook-tutor-api:local` 镜像，已依据该 Compose 项目配置从当前 worktree 重建镜像并仅重建 Worker。
- 更新后容器已启动，状态为 `Up`，新镜像摘要以 `sha256:e3af3a...` 开头，退出码为 0；最近 90 秒无错误日志。

## 2026-08-21 · 注册失败第二次修复

- API 日志确认用户点击注册时没有到达注册端点；旧 Web 容器使用了过期构建，未把 API 地址编译为 `http://localhost:8010`。
- 已根据 `.env.identity-test` 重建并替换 Web 容器；构建通过，注册页返回 200，Web 容器状态为 healthy。

## 2026-08-22 · 注册链路永久修复

- 以失败测试复现“浏览器依赖构建期 API 地址”的缺口，再实现 Web 运行时同源代理；会话 `Set-Cookie` 通过代理保持完整。
- 删除 Web 镜像中的 `NEXT_PUBLIC_API_BASE_URL` 构建参数，Compose 改为运行时内部服务地址，避免端口变化和旧前端镜像再次破坏注册。
- 验收账号 `codex_reg_0822121130` 在本地 identity-test 数据库注册成功（201），同会话读取当前用户成功（200）。

## 2026-08-22 · 注册 422 提示修复

- 用户截图对应请求已在 API 日志中定位为 `POST /api/v1/auth/register 422`；不是代理失败，也不是账号重复（409）。
- 用户名 `wtd` 和邮箱 `wtd00005@163.com` 满足规则；密码不足后端要求的 12 位。
- 先添加失败回归测试，再实现短密码前端拦截和可见规则提示；重建 Web 容器后生效。

## 2026-08-22 · 工作台面板样式与功能核查

- 新增回归测试，自动核对三个工作台组件引用的 CSS Module 类均有定义；测试先以 19 个缺失类失败，补齐后通过。
- 重建 Web 容器并在真实登录会话中确认：知识库表单和按钮恢复卡片化样式；创建知识库成功；空库搜索返回正确空状态；题库标签与空状态正常。
- 核查前后端映射：知识库列表/创建/上传/状态/搜索/来源预览、题库列表/答题/复习项/历史均已有调用；后端创建题目尚无前端入口。
- 发现工作台外壳的创建班级、全局搜索、更多操作、空间内搜索、空间设置、上传快捷入口和展开工作区仍是无事件处理的视觉占位。
- 最终验证：Web 10 files / 39 tests、ESLint、TypeScript、Docker production build 均通过；Compose 六项服务均运行，Web/API/PostgreSQL/Redis 报告 healthy。

## 2026-08-22 · 浅色工作台排版优化

- 采用确认的“暖白 + 柔紫”方案：白色中心内容、浅灰紫侧栏、柔紫选中/主操作、薄荷绿服务与连接状态。
- 移除工作台的 emoji、字符图标和无事件处理的原型按钮；保留知识库、上传、搜索和题库的真实控件。
- 移除 `.panelGroup` 固定最小宽度；341px 浏览器实测无页面级横向溢出，内容树和说明栏会收起，题库/知识库切换仍通过。
- TDD：图标清理测试和 CSS 合同测试均先失败再通过；Web 全量 10 files / 41 tests、ESLint、TypeScript 通过，Docker production build 通过。

## 2026-08-22 · LLM Markdown 知识库设计

- 用户确认采用 LLM 全文重写导入模式：Word/PDF/图片/Vault 先由现有解析器/OCR 提取，再由 Faro Gemini 生成 Markdown 草稿。
- 用户确认草稿必须预览、编辑并确认后发布；原始文件永不覆盖。
- 用户要求章节长度不作为严格失败条件；后续只按上下文窗口分块，异常检查仅识别空响应、明显截断和模型错误文本。
- 用户要求多次修复失败时暂停：同一指标最多三次定向修复，第三次仍失败必须交由用户决定是否继续。
- 已完成设计文档：`docs/superpowers/specs/2026-08-22-llm-markdown-knowledge-design.md`。
- 已完成实施计划：`docs/superpowers/plans/2026-08-22-llm-markdown-knowledge-plan.md`。
- 本阶段尚未修改业务代码、未使用真实 Faro Key、未调用外部付费模型。

## 2026-08-23 Markdown data-layer verification pause

Acceptance metric: `apps/api/tests/test_knowledge_markdown_models.py`.

Three targeted repair attempts were made after introducing Markdown note/revision/link models:
1. Fixed a literal newline escape introduced while rewriting the new test; test collection then advanced.
2. Added the missing `KnowledgeBase` import; test collection then advanced.
3. Ran the focused suite; all three cases now fail because the helper's `MarkdownNote` construction still omits required `knowledge_base_id`.

Per the user-approved three-strike rule, stop here before a fourth repair and request direction. No schema or architecture change is proposed; the next repair would only correct the test helper's required scope field.
## 2026-08-23 Textbook acceptance extension

The user authorized using the provided wireless-communications DOCX as the platform's real acceptance sample. The review workflow must propose (not auto-publish) chapter/section hierarchy plus concept, formula, property, method, and example notes. Repeated specialized terms should resolve to one canonical candidate note with context-aware candidate backlinks. Formula occurrences must link to definition, derivation/conditions, and examples when supported by source context. Raw source remains immutable; all candidate wikilinks require user confirmation before publication.

Observed sample facts: DOCX parsed locally with 6,728 blocks / 502,860 characters / stable source pointers; no OCR is needed. Safe DOCX bounds were raised to 4,096 archive entries, 64 MiB expanded archive, 32 MiB member/XML sizes; parser security suite passed. The original PDF has no extractable text layer and requires OCR.
## 2026-08-29 · AI 助教 Faro/Gemini 恢复任务

- 已读取 `systematic-debugging`、`subagent-driven-development` 与 `planning-with-files` skill 指引。
- 已确认工作区/分支和 Docker 服务状态，并检查关键 Tutor/Agent 文件与 Git HEAD 参考实现。
- 已向两个已有子代理请求最新结果：Faro 调用链只读调查、TutorPanel UI 实现。
- 已形成单一根因假设并由代码证据支持：活跃 UI/API 已被切到 Claude Agent，Faro Tutor 写链路被退休，故“连不上”不是单纯外部 API 超时。
- Web 基线命令完成：`pnpm --dir apps/web exec vitest run src/lib/tutor-api.test.ts src/components/workspace/workspace-shell.test.tsx src/components/workspace/agent-cutover.test.tsx` → 3 files / 21 tests passed（仅表示当前行为自洽）。
- API 基线命令启动：`pytest apps/api/tests/test_tutor.py apps/api/tests/test_llm_faro.py -q`；运行过程中被用户中断，只有部分通过标记，需重新执行。
- `session-catchup.py` 首次因系统没有全局 `python` 命令失败；改用 `apps/api/.venv/Scripts/python.exe` 后成功、无额外输出。
- 下一步：等待并审查 TutorPanel 子代理结果；语义合并恢复 Faro Tutor 后端与 Web API；切回 TutorPanel；运行完整聚焦测试、类型检查、构建与 Docker 实测。

## 2026-08-30 · AI 助教 Faro/Gemini 并行修复恢复

- 恢复上下文后确认继续采用 AgentPanel → Agent API → Agent Runtime 架构，不再恢复已退休 Tutor 写接口。
- 已启动 Web、Runtime、API 三个互不冲突的子代理；主线程负责环境修正、服务重启和真实连接验收。
- 安全检查只判断配置是否存在：Faro API key 已设置；本机非敏感 Agent provider/model/context 仍为旧值。
- 当前 8765 Runtime 健康但运行的是重启前构建，必须在代码和测试完成后重启。
## 2026-08-30 · AI 助教 Faro/Gemini 修复完成

### 已交付

- Runtime 新增并唯一注册 Faro OpenAI-compatible provider，模型固定为 `gemini-3.7-flash-tiered`，上下文窗口固定为 `32000`；不再注册或回退 Claude。
- Agent API 固定新会话与设置为 `faro / gemini-3.7-flash-tiered / 32000`，拒绝错误 provider/model/context；旧 Claude/Fable 会话保留历史但写操作返回 `409 agent_session_provider_retired`。
- Web 的 AI 助教默认区域只保留聊天主界面；右上角设置按钮打开统一风格弹层，二级页签为“会话记录”和“服务设置”。服务配置只读展示 Faro/Gemini/32000，不显示密钥。
- 旧 Claude/Fable 会话在 Web 中标为只读，不建立实时连接，不允许继续、停止、回退、分叉或发送；仅有旧会话时自动创建新的 Faro 会话。
- 本机 `.env` 仅定向更新非敏感 Agent provider/model/context；Runtime 与 Docker API/Web/Worker 已按新构建重启。

### 验证记录

- API 聚焦测试：`119 passed`。
- Web：`35 test files passed / 232 tests passed`；ESLint 通过；Next production build 通过。
- Runtime：`25 test suites passed / 86 tests passed`；typecheck 通过；build 通过。首次与 Web build 并行时仅 `tests/package.test.ts` 触发 5 秒资源竞争超时，取消并行后全套通过，无需业务代码修复。
- Host Runtime PID：`35704`。本轮再次运行 `scripts/smoke-agent-runtime.ps1` 通过：Node `24.18.0`、pnpm `11.19.0`、protocol `1.0`。
- 鉴权 diagnostics：`status=ok`，providers 仅含 `faro`，状态 `ok`，详情 `Faro · gemini-3.7-flash-tiered`；未出现 Claude provider。
- API `/api/v1/health` 返回 `{"status":"ok","service":"textbook-tutor-api"}`；Web 返回 HTTP `200`；Docker API/Web/PostgreSQL/Redis healthy，Worker 与 MinIO running。
- 真实 Agent API → Runtime → Faro 对话连续两次通过：POST turn 返回 `202`，事件序列包含 `turn_started`、`user_message`、`model_text_delta`、`session_state`，cursor 匹配，最终 Runtime 状态 `completed`；最新 `model_text_delta` 非空。

### 结论

AI 助教“连接不上”的根因已修复。当前实际聊天链路为 `AgentPanel → /api/v1/agent → Agent Runtime → Faro → Gemini 3.7 Flash`，并已由真实模型响应验证，不再使用 Claude。

## 2026-08-30 · 最终稳定性收尾启动

- [x] 恢复 planning-with-files 上下文并确认工作树仅有既存 `.tmp/` 未跟踪文件。
- [x] 真实复现正常 Markdown 上传状态链路；确认前端 workspace 与当前上传任务状态不同步。
- [x] 获取只读子代理报告，确认状态 URL/字段合同正确，建议补 snapshot 同步与 no-store 测试。
- [x] 将会话历史/Capabilities、PDF Worker、知识库删除与最终回归审计拆成不冲突并行任务。
- [ ] 主线程：实现上传状态同步与 no-store 回归测试。
- [ ] 主线程：依据删除审计实现安全知识库删除。
- [ ] 集成 AI 助教设置修复和 PDF Worker 修复。
- [ ] 重建并完成真实页面、候选生成、AI 连接和全量测试回归。

## 2026-08-30 · 上传处理状态前端修复

- [x] 先新增 2 个失败测试，分别覆盖 workspace 权威状态自动同步为 `searchable` 与 `failed`，证实旧实现会让“当前任务”永久停留在“处理中”。
- [x] `knowledge-panel.tsx` 按 `document_id + document_version_id` 将 workspace snapshot 合并到当前知识库的 accepted upload entry；不会影响无 response 的上传中任务或其他知识库。
- [x] 手动刷新采用单调终态合并，避免迟到的 `processing` 响应把已确认的 `searchable/failed` 回退。
- [x] workspace/status GET 与 Next 同源代理 GET/HEAD 显式使用 `cache: no-store`，代理响应写入 `Cache-Control: no-store`。
- [x] 聚焦 Web 回归：3 files / 28 tests passed。

## 2026-08-30 · 最终收尾续跑记录

- AI 会话/Capabilities 子代理已完成：历史选择后关闭设置并回到聊天；归档改用 DELETE；停止按 204 处理；分叉按 checkpoint 合同调用；继续/回退在当前 Faro 合同不支持时明确禁用并说明；Capabilities 改为按知识库保存在当前浏览器，固定 Faro/Gemini/32000 不变。
- Web 聚焦回归：6 files / 61 tests passed（会话、设置、AgentPanel、上传状态、knowledge API、Next API proxy）。
- Parser + Worker 并行聚焦测试中 Parser/绝大多数 Worker 用例通过，但 `test_successful_semantic_sibling_does_not_overwrite_failed_change_set` 失败；运行时后端删除子代理正在改 apps/api，stderr 显示临时 IntegrityError，故该结果不作为稳定基线，待代理结束后串行重跑并诊断，避免重复并发测试。
- 已启动两个互不冲突子代理：后端安全硬删除/outbox；前端删除确认与状态清理。
- 2026-08-30：第一次通过 PowerShell 管道调用 `apply_patch` 因补丁参数编码不是 UTF-8 失败；改用项目 Python 以 UTF-8 定向替换，未重复同一失败方式。
- Agent Runtime 全量回归串行通过：25 suites / 92 tests；typecheck 通过；build 通过。
- 同时修正 `apps/web/src/lib/agent-api.ts` 的遗留 REST 合同：归档改为真实 DELETE，stop/resume/rewind 正确处理 204，branch payload 改为 `checkpoint_id`；对应 Agent API/会话/AgentPanel 3 files / 42 tests passed。

## 2026-08-30 · 最终收尾主线程复核（续）

- 恢复工作树并确认分支 `feature/platform-foundation-wip`、HEAD `06189d0`，既存 `.tmp/` 保留未动；初始 `git diff --check` 通过。
- Web 聚焦回归：10 files / 113 tests passed。
- API 聚焦回归（删除、outbox、Parser、Worker、知识库、schema、vault watcher）：225 tests passed；先前并发失败的 Worker 用例本次串行通过。
- Web 全量：35 files / 261 tests passed；Next production build passed。ESLint 仅发现会话侧栏 2 个未使用参数 warning，已交由前端专项审查消除。
- Agent Runtime：25 suites / 92 tests passed；typecheck、build passed。
- API 全量首次直接运行受本机真实 `.env` 影响，health 测试尝试连接 Docker 内部主机名；用显式非敏感 development 测试覆盖后 `test_health.py` 5 passed。另发现 compose 安全测试仍期待旧 context window `1000000`，与当前固定 `32000` 合同不符，已交由后端专项审查修正。未读取或改写 `.env`。
- 修改文件 Ruff 聚焦检查通过；Docker 旧构建当前 API/Web/PostgreSQL/Redis healthy，Worker/MinIO running，待代码审查完成后重建。

## 2026-08-30 · 最终收尾继续

- 已复核真实浏览器分叉失败日志和 Runtime server 合同，确认当前关键路径为修复 API stop/rewind/fork mutation 元数据与 fork ID 一致性。
- 已将测试文件的并行补强交给现有子代理，生产代码由主任务独立修改，避免写入冲突。
- 错误记录：当前 PowerShell 环境未提供全局 `python` 命令；已改用项目虚拟环境 `apps/api/.venv/Scripts/python.exe` 完成同一编辑与语法检查，未再依赖全局 Python。
- Runtime mutation 生产代码已完成：Client 发送 mutation headers，fork 请求携带预生成 UUID，Runtime 返回 UUID 受模型校验且必须与请求一致，DB fork session 使用同一 UUID；stop/rewind/fork 路由均签发绑定源会话的 workspace capability。
- Ruff lint 通过；格式检查首次指出 RuntimeClient 单行签名格式，已用 Ruff formatter 修复。
- API 聚焦测试 32 项通过；API 全量 pytest 通过，Ruff lint 通过。
- Runtime 25 suites / 92 tests、typecheck、build 全部通过。
- 额外执行全仓 `ruff format --check` 时发现 69 个既有文件不符合当前 formatter（与本轮改动无关）；为避免制造大范围无关 diff，没有全仓自动格式化。本轮 Agent 相关 12 个文件的 Ruff format check 已通过。
- 浏览器真实分叉已成功：从主会话创建 `a1aae3a9-2207-4316-a170-c268f8522a38`，URL 切换到新会话，且新会话可经 Faro 返回 `FORK_OK_20260830`。
- 第一次用全局“分叉”按钮定位触发 strict-mode 多匹配错误；改为按当前 session test id 精确定位后成功。
- 运行中停止仍出现 HTTP 500。结合 Runtime stop 的 204 合同，怀疑 RuntimeClient 对 204 空响应仍强制 `response.json()`，需要日志确认并补修，防止把已成功的空响应误报为失败。
- API 日志确认 stop 500 是 `json.decoder.JSONDecodeError`：Runtime 已按合同返回 204，但 RuntimeClient 对所有成功响应都强制解析 JSON。
- 已修复 RuntimeClient：204 直接返回空对象；其他成功响应若不是有效 JSON/dict，则稳定转换为 `runtime_response_invalid` 502，避免裸异常成为 500。
- mutation client 测试已改用真实状态码：stop/rewind=204、fork=201；聚焦 32 项测试、Ruff lint/format 均通过。

## 2026-08-30 · Vault 删除真实验收完成

- 按用户最新优先级停止继续扩展分叉功能；现有分叉修复和测试结果保留。
- 首次 E2E 注册因测试用户名超过接口允许长度返回 422；已改用短用户名继续，未修改产品校验。
- 隔离 E2E 账号成功创建个人知识库 d99c4390-efc5-4280-a1e5-ee2bf3ccb322，在 Worker 实际 Vault scope 创建证明文件后执行删除。
- 真实结果：删除 HTTP 204；Vault 目录在第一次轮询时已不存在；知识库详情 HTTP 404。未删除或修改用户现有知识库。
- 最终已知验证基线：API Agent 聚焦 32 passed、API 全量 pytest 与 Ruff lint 通过；Runtime 25 suites / 92 tests、typecheck、build 通过；Web 35 files / 267 tests、ESLint、production build 通过。
- Compose 当前 API/Web/PostgreSQL/Redis healthy，Worker/MinIO running；数据库迁移为  018_object_deletion_outbox (head)。
- 项目修复提交 db9e1b9 fix: complete knowledge and tutor stability 已成功推送至 github-collab/feature/platform-foundation-wip；.tmp/ 保留在本地且未提交，未暂存 .env 或密钥文件。
