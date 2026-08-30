# Progress Log

## Session: 2026-08-16 · 规划记录同步

- **Status:** complete
- 同步根目录三份持久记录，使其反映已完成的 Phase 4 与当前进行中的 Phase 5。
- 已完成平台基础、认证与班级权限、供应商模型目录、Decimal 钱包预留/结算、管理员充值/冲正以及 C3 模型与余额接线。
- 最终验收：API 172 项通过、3 项依赖外部 PostgreSQL 的并发测试跳过、覆盖率 95.45%；Ruff 通过；Web 15 项测试、Lint 与生产构建通过；隔离 Docker/PostgreSQL 完成管理员充值、模型目录和学习者余额验证。
- 下一阶段：知识导入、检索引用与 Agent 学习能力。

## Session: 2026-08-14 至 2026-08-15 · 平台实现

- **Status:** complete
- 平台基础骨架、认证/个人空间/班级权限、供应商与钱包里程碑均完成，并进行了测试先行实现、规格复审和质量复审。
- 遇到的关键环境问题：Windows 缓存权限、Docker 端口冲突、Alembic 迁移版本标识长度及短期旧标识兼容；均已记录测试并修复。

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

## Test Results

| Test | Input | Expected | Actual | Status |
|---|---|---|---|---|
| C3 空间层级评审 | 用户查看可视化原型 | 空间移至最左栏，内容层级位于第二栏 | 用户回复“ok，可以了” | 通过 |
| DeepTutor 技术路线确认 | 三种架构路线 | 用户选择推荐路线 | 用户确认采用自主平台 + 选择性复用 | 通过 |
| 项目记忆方式确认 | memory-tencentdb 与 planning-with-files | 选择可用于当前 Codex 项目的持久方式 | 用户指定 planning-with-files | 通过 |
| 正式设计需求覆盖 | 已确认需求关键词与设计章节 | 用户、班级、文件、Agent、记忆、计费、部署与 DeepTutor 边界均出现且无 TODO/TBD | 关键需求全部覆盖，仅保留实施时运行参数 | 通过 |

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

## 5-Question Reboot Check

| Question | Answer |
|---|---|
| Where am I? | Phase 2：架构与正式设计 |
| Where am I going? | 完成设计文档、用户审核、实施计划、实现与验收 |
| What's the goal? | 构建多用户、个人/班级知识库、可追溯答疑、长期记忆和按量计费的学习 Agent 平台 |
| What have I learned? | 见 `findings.md` |
| What have I done? | 完成需求确认、DeepTutor 调研、C3 界面确认和技术路线选择 |

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

- **Status:** Task 7「immutable indexing and reliable worker」最终 PASS；Milestone 3 / Phase 5 仍为 `in_progress`。
- **代码提交：**`f298eb2 feat: build knowledge indexes reliably`、`96a3ad6 fix: close reliable indexing gaps`、`53284ca fix: harden reliable indexing delivery`、`cfc6220 fix: serialize ready index snapshots`、`0d34b2a fix: requeue changed embedding contracts`、`363f3fb fix(api): allow blank OCR pages`。
- **交付文档提交：**`8f22c2d docs: record reliable indexing delivery`。
- **复审：**初始完整规格 PASS；初始质量 FAIL 后核验并最小修复 blank OCR page；post-fix 独立规格 PASS（34 focused）及最终独立质量/安全 PASS。production-HTTP 质量项由现有 production HTTPS 启动门禁证伪。
- **最终验证：**Task 7 相关八文件组合 362 passed、36 warnings；迁移回归 3 passed、4 warnings；targeted Ruff PASS；`git diff --check aa71123..HEAD` PASS。完整 API suite after Task 7、Docker 与真实外部基础设施未运行。
- **保留风险：**long handler 持有 transaction/job lock；有界 S3 PUT 仍会在配置对象上限内缓冲；真实 PostgreSQL/pgvector、MinIO/S3、Redis、Tesseract/PDFium corpus、external services 与 live POSIX process-group 均待后续集成验收。
- **Windows OCR：**历史大组合有两个 1 秒 PID-file 等待时序失败；精确两项、完整 OCR 文件和本次最终 362 组合均通过，独立质量审查判为非阻塞。
- **下一步：**Task 8「hybrid retrieval and secure source preview」；本会话到此停止，不开始 Task 8。
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

## Session: 2026-08-18 · Phase 5 / Task 10 blocked verification review

- **Purpose completed:** reviewed the existing Task 10 verification record without reimplementing code or rerunning the full suites; feature-worktree documentation commits are `2d48a47`, `d880d0d`, and `a0f6bb7`.
- **Review loop:** initial independent spec review found an incomplete Task 10 Files list and imprecise provider wording; a fresh fix commit corrected only those points, then SPEC PASS. Initial quality review found only a missing terminal LF in the handoff; a fresh one-line fix and final independent QUALITY/SECURITY PASS followed.
- **Result:** maintain `Task 10: incomplete` and `Milestone 3 / Phase 5: in_progress`. Known blockers are full API coverage at 88.08% versus 90% (two Windows OCR timing failures) and unavailable Docker/PostgreSQL/pgvector runtime, which leaves real migration round-trip and Compose vertical slice unexecuted.
- **Root protection:** these three root planning files intentionally remain uncommitted. No reset, stash, or root commit was used.
- **Next session:** install/provide a usable Docker Desktop/Compose or equivalent isolated PostgreSQL/pgvector runtime; fix or stabilize the full coverage failures; rerun Task 10 gates before any final delivery record.
## Session: 2026-08-18 · New task — Milestone 4 planning preparation

- **Transition:** root records were updated incrementally without committing them. Task 10 remains documented as incomplete/environment-blocked; no completion status was changed.
- **Current work:** recover the approved Milestone 4 design against the actual feature worktree, then prepare a reviewable detailed plan for AI tutor, cited answers, question/wrong-answer flows, and L0–L3 memory.
- **Do not skip:** no production Agent implementation starts until the design describes provider/model and verified-usage posture, teaching-mode transitions, private-data ownership, citation authorization, and memory controls. The existing model dropdown and wallet/knowledge services are reusable inputs, not an Agent delivery.
- **Next:** finish the design evidence matrix and present the concrete Milestone 4 design choices for user confirmation; retain all Task 10 runtime gates for later live acceptance.
## Session: 2026-08-18 · New task continuation — Milestone 4 design decision gate

- **Purpose / scope / risk:**恢复并更新跨会话项目记录，核对 Task 10 阻塞状态与 Milestone 4 实际代码边界；仅做只读规格复核和根目录规划文档增量更新，不实现功能、不重跑完整测试。主要风险是把受限基础设施的 Task 10 误记为通过，或在真实 usage/计费条件未确定前开始 Agent 实现。
- **状态核对：**根目录仅保留预期的未提交 `task_plan.md`、`findings.md`、`progress.md`；feature worktree `feature/platform-foundation` 干净，HEAD 为 `a0f6bb7 docs: terminate Task 10 handoff`。根目录记录 diff check 通过；未运行任何测试。
- **独立规格复核：**新子代理确认现有 provider catalog、wallet reserve/settle/release、授权知识检索/来源回看与 C3 视觉壳可复用；真实 Provider/LLM 调用、用量核验、Tutor 编排、学习数据模型、回答级引用、题库/错题和 L0–L3 记忆均尚未实现。
- **门禁：**先由用户确认首个具体 Tutor ProviderProfile 与可核验 usage/生产计费姿态。此项未确认前，不产生可批准的 Milestone 4 实施设计、不调用 writing-plans，也不开始实现。
- **Task 10 保留结论：**coverage 88.08% 低于 90%，Docker/PostgreSQL/pgvector runtime 不可用，真实 migration round-trip 与 Compose vertical slice 未执行；Milestone 3 / Phase 5 继续为 `in_progress`。
- **Next:**按 brainstorming 一次询问一个问题；先确定具体供应商、模型与可核验 usage 的选择，再形成 2–3 条实现路径供用户选择。
## Session: 2026-08-18 · Task 10 environment handoff finalized

- **Purpose / scope / risk:** converted the previously reviewed but uncommitted environment-resumption handoff into a truthful committed recovery point. Work was limited to that feature-worktree document and incremental root planning records; no code, `.env`, containers, volumes, tests, or root commits were created. The key risk was calling `a0f6bb7 + an uncommitted document` clean after the document itself was committed.
- **Environment evidence:** Docker Desktop daemon is live. Verified CLI: `C:\Users\asus\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`; Engine client/server `29.7.2`; Compose `v5.3.1`. Docker operations need controlled elevated invocation in this sandbox. No additional local PostgreSQL, pgvector, Redis, MinIO, `psql`, `pg_isready`, or `initdb` installation is required for the Compose route.
- **Document assurance:** a fresh fix subagent made the recovery language generic and post-commit truthful; a fresh independent specification review returned `SPEC PASS`; a distinct quality/security review returned `QUALITY/SECURITY PASS`. The resulting one-file dedicated feature commit is `5a242dc docs: prepare Task 10 environment handoff`; feature worktree is clean.
- **Still pending:** Task 10 migration round-trip and mandatory Compose vertical slice need explicit permission for a Git-ignored local `.env`, a uniquely named isolated disposable project, image pull/resource use, redacted evidence capture, and later project-scoped cleanup. The full API coverage gate is still 88.08% versus 90% with two Windows OCR descendant-timeout test failures; no test or threshold was weakened.
- **Root protection:** only `task_plan.md`, `findings.md`, and `progress.md` remain intentionally uncommitted in the root worktree. No reset, stash, stage, or root commit occurred. Next action after authorization is the reviewed isolated Docker procedure; then the coverage root-cause fix, before any Phase 5 completion claim.

## Session: 2026-08-19 · Task 10 coverage recovery resumed

- **Purpose / scope / risk:**恢复 Task 10 coverage gate，先核实子代理与 Git 状态，再在互斥测试文件中补强有价值的失败边界；不重跑完整测试、不触碰 Docker gate。风险是会话恢复后失去旧代理句柄，或把 88.13% coverage 误记为通过。
- **State evidence:** root worktree 继续仅有预期未提交的 `task_plan.md`、`findings.md`、`progress.md`；feature HEAD 仍为 `5a242dc`，且仅有未提交生产改动 `apps/api/src/tutor_api/knowledge/ocr.py`（13 insertions、1 deletion）。无测试文件变更、无额外 git worktree。旧代理昵称无法作为有效工具 ID 查询，因此没有将其假定为完成。
- **Verified gate:** 最新正式全量 API coverage 为 `592 passed, 3 skipped, 88.13%`，功能零失败但低于 90%。Task 10、Milestone 3、Phase 5 保持 `in_progress`。Docker Desktop 已验证 Engine `29.7.2` / Compose `v5.3.1`，但真实 migration/vertical slice 尚未获授权运行。
- **Current work:** 已重新派发四个新鲜独立测试子任务，文件写入范围严格互斥：`test_knowledge_adapters.py`、`test_knowledge_worker.py`、`test_knowledge_ocr.py`、`test_knowledge_retrieval.py`。每项完成后必须新鲜独立 SPEC PASS 再 QUALITY/SECURITY PASS；失败时由新鲜 fix agent 修复并重启链。
- **Next:**收取四项报告、核对每项仅改指定文件、逐项复审；全部通过后才进行一次官方 full API coverage gate。根目录三份规划文件继续保持未提交，不 reset/stash/stage/commit。

## Session: 2026-08-19 · OCR coverage test group accepted

- **Purpose / scope / risk:** 处理先前代理异常后唯一实际落地的 OCR 测试补强，严格执行“修复 → 新鲜 SPEC → 新鲜 QUALITY/SECURITY”链条。风险包括把仅在当前平台 skip 的 Windows mock 测试误称为实机 Windows 验收，或把窄测试通过误称为全量 coverage 达标。
- **Implementation/verification:** `test_knowledge_ocr.py` 最终新增 OCR child coverage-env 过滤和 parent-env 保留、POSIX Popen 前 deadline、Windows secure startup 后 deadline、assignment/resume 失败 cleanup 的回归测试。窄验证为 `52 passed, 1 skipped`；Ruff `--no-cache` 与 diff check PASS。`.pytest_cache` 的 WinError 5 警告为既有缓存权限问题，不改变测试 PASS。
- **Independent review:** 最终 fresh SPEC reviewer `SPEC PASS`；随后 fresh QUALITY/SECURITY reviewer `QUALITY/SECURITY PASS`。此前 reviewer 指出的私有实现耦合、Windows终止竞态、CloseHandle 覆盖缺失、裸 suspended 常量和标准库全局污染均已在每轮后由新鲜修复代理处理，并重启 review 链。
- **Current state:** feature 仍只含未提交的 `ocr.py` 与 `test_knowledge_ocr.py`；root 仍只保留三个规划记录未提交。Task 10 / Milestone 3 / Phase 5 仍 `in_progress`：总 coverage 尚未重跑且旧结果 88.13% < 90%，Docker migration 与 Compose vertical slice 仍未执行。
- **Next:** 以单代理、单文件方式推进 `test_knowledge_adapters.py` 的存储 range fail-closed 覆盖；该组通过 review 后继续 worker/retrieval 组，全部审查通过才运行一次 full coverage gate。

## Session: 2026-08-19 · Task 10 S3 adapter coverage group closed

- **Purpose / scope / risk:** 对 S3 range fail-closed 覆盖补强进行独立复审闭环；范围只含 feature worktree 的 storage.py、`test_knowledge_adapters.py，不重跑 full API、不触碰 Docker。风险是 HTTP 200 fallback 与 206 range 的 header/body 不一致可能泄露错误类型或留下资源清理问题。
- **Review/fix chain:** 初始 SPEC 指出缺少正向 200 fallback 真实 urllib 用例，最小测试修复后 107 passed；第二次 SPEC 指出两条范围读取分支对超长 body 泄露 ObjectSizeLimitError，最小生产+测试修复后 109 passed。随后全新 SPEC 返回 PASS，独立 QUALITY/SECURITY 返回 PASS。
- **Accepted implementation:** 只在 get_object_range() 两个 response-read 位置将 range-response overflow 归一化为 ObjectRangeNotSatisfiableError from None；测试证明 206 Content-Range 与 200/no-Content-Range 的成功路径和 fail-closed 边界，且 server 与 response 清理有界。
- **Verification:** python -m pytest -p no:cacheprovider tests/test_knowledge_adapters.py --disable-warnings -q → 109 passed；targeted Ruff 和 feature git diff --check PASS。未执行 coverage total、迁移或 Compose。
- **State / next:** root 仍只保留 `task_plan.md、`findings.md、progress.md 三个刻意未提交记录；Task 10 / Milestone 3 / Phase 5 仍 in_progress，旧正式 coverage 仍为 88.13%。下一项为独立的 worker/retrieval coverage 组，审查完成后再运行一次官方 full coverage gate。
## Session: 2026-08-19 · Task 10 worker coverage group closed

- **Purpose / scope / risk:** 为 full coverage gate 补强 immutable worker 的高风险边界，仅改 feature worktree 的 `test_knowledge_worker.py。风险是 SQLite 租约竞争模拟可能将连接/事务工件误判为生产 race，或陈旧成功而非失败路径的覆盖不完整。
- **Implementation/review chain:** 新增对象 hash/content-type mismatch、tampered BUILD_INDEX checkpoint、terminal parse isolation、lease loss 覆盖。初次 QUALITY/SECURITY 指出缺少陈旧 `fail_job() 路径；补测一度失败并被独立生产检查证伪为 StaticPool 共享事务的错误模型。新鲜测试代理改为 explicit NullPool 独立连接与已提交 claim，成功/失败陈旧收尾均断言 worker_lease_lost 和 replacement 字段不变。随后重启 fresh SPEC PASS → fresh QUALITY/SECURITY PASS。
- **Verification:** python -m pytest -p no:cacheprovider tests/test_knowledge_worker.py --disable-warnings -q → 22 passed；targeted Ruff 与 feature diff check PASS。未改 production、DB factory 或 root records 外的文件，未运行 full suite、迁移或 Compose。
- **State / next:** root 仍只含三份刻意未提交规划记录；Task 10 / Milestone 3 / Phase 5 仍 in_progress，旧正式 total coverage 仍 88.13%。下一项为 retrieval coverage 组，然后才进行一次官方 full API coverage gate。
## 2026-08-19 · Task 10 retrieval coverage group closed

- **Purpose / scope / risk:** 补强检索和 cited-preview 的 fail-closed 覆盖，仅修改 feature worktree 的 `apps/api/tests/test_knowledge_retrieval.py`。重点风险是 embedding 无效输出可能绕过检索边界，或未授权、retired index、archived document 的 citation preview 在对象存储读取后才被拒绝。
- **Implementation/review chain:** 新增 embedding provider exception、错误维度、bool/NaN/infinity fail-closed，no-ACTIVE-index 不调用 embedding，以及 source/page preview 的未授权、retired/archived 与 storage-diagnostic redaction 回归。两轮 SPEC 分别发现 page 分支没有可读 preview key 的证据缺口；每次均由新鲜代理作最小测试修复并重启复审。最终 fresh SPEC PASS → fresh QUALITY/SECURITY PASS。
- **Verification:** `python -m pytest -p no:cacheprovider tests/test_knowledge_retrieval.py --disable-warnings -q` → `19 passed`；targeted Ruff 与 feature `git diff --check` PASS。未运行完整 coverage、迁移或 Compose，未填写 API key。
- **State / next:** adapters、worker、OCR 与 retrieval 四组覆盖补强均已通过独立 review 链；现在可运行一次官方完整 API coverage gate。旧正式总 coverage 仍为 88.13%，在新 gate 结果出现前 Task 10 / Milestone 3 / Phase 5 仍 in_progress。Docker Compose 的本地运行环境以 `.env.example` 和 `compose.yaml` 为准；真实外部 OCR/Embedding/LLM provider key 目前未配置且非本地 coverage gate 的前置条件。

## 2026-08-19 · Task 10 full API coverage gate (not yet passed)

- **Gate command/result:** 从 feature worktree `apps/api` 使用现有 `.venv`、`-p no:cacheprovider` 与 worktree 外 `COVERAGE_FILE` 执行 `python -m pytest --cov=tutor_api --cov-report=term-missing --cov-fail-under=90`；功能结果为 `652 passed, 4 skipped, 40 warnings`，无测试失败，但总 coverage 为 **89.18%**（`4777` statements、`517` missed），因此被强制 `--cov-fail-under=90` 正确拒绝。
- **Interpretation:** 相比此前正式 gate 的 88.13% 已上升 1.05 个百分点，但仍差 0.82 个百分点；不得将功能零失败或四组覆盖 review 通过误称为 Task 10/Phase 5 完成，也不得降低阈值、增加 skip/xfail、削弱 cleanup/timeout 断言或使用 `pragma: no cover`。
- **Environment/API-key status:** 当前 gate 不需要也未使用外部 provider API key。`compose.yaml` 默认 `PROVIDER_PROFILES_JSON=[]`，并未把 `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` 传给 api/worker；Task 10 后续隔离 migration/Compose 验收需要本地 PostgreSQL、Redis、MinIO 与应用/对象存储密钥，不需要真实 LLM/OCR/embedding provider 密钥。真实 Tutor provider key 留待 Milestone 4 的供应商、模型、可核验 usage 和计费决策批准后配置。
- **Next:** 选择单一、高价值 coverage-only 测试组（优先 indexing 的未覆盖 fail-closed/一致性分支），由新鲜实现代理完成最小补测；随后必须重新进行独立 SPEC PASS 和 QUALITY/SECURITY PASS，才可再次运行完整 90% coverage gate。

## 2026-08-19 - Task 10 indexing coverage review and gate

- Restored Task 10 context and preserved the expected root planning-file modifications and feature-worktree changes.
- Added/validated high-value indexing coverage for boolean chunk bounds, immutable source validation, empty source cleanup, malformed embeddings preserving the ACTIVE index, and bounded long source pointers.
- Directed indexing verification passed: 32 tests; Ruff and diff check passed.
- Fresh independent reviewers returned SPEC PASS, then QUALITY/SECURITY PASS.
- Official API coverage gate ran once after the reviewed group: 664 passed, 4 skipped, 40 warnings, 89.41% total. It exited nonzero solely because the former 90% fail-under condition was not met.
- User approved moving forward without chasing the final 0.59 percentage points. Next pending work is isolated migration and Docker Compose vertical-slice acceptance, which still requires explicit authorization for resource creation and destructive disposable-environment cleanup.
## 2026-08-19 · Task 10 final Docker acceptance stopped

- **Purpose/scope:** 重建隔离 Compose 项目的 API/worker 镜像并验证真实 PostgreSQL/pgvector ingestion、Markdown/PDF 检索和 PDF citation page。
- **Code evidence:** `indexing.py` 的 float32/SQLite 兼容修复；35 个 indexing tests passed；targeted Ruff 与 diff check passed；SPEC review PASS。质量复审后修正了跨 binade regression 常量，但未再增加集成测试基础设施。
- **Docker evidence:** API/worker 成功重建并 healthy；migration current 为 `0008_embedding_contract (head)`；垂直脚本仍以 `status=200, results=0` 超时；最近 `index_versions` 为 `failed`。因此 Task 10 未完成。
- **Decision:** 按用户要求的能力止损线停止，不再重复运行脚本或继续猜测式修复。coverage 89.41% 的用户例外仍有效，但不能抵销 Docker vertical slice 失败。隔离环境随后按既有授权清理。

## 2026-08-19 · Context saved for new Phase 5 window

- 已保存 Task 10 最终状态、Docker 失败证据、float32 修复证据、工作区保护规则和下一窗口执行顺序。
- 交接文件：`E:\项目\知识库课本\.worktrees\platform-foundation\docs\superpowers\handoffs\2026-08-19-phase5-task10-context-handoff.md`。
- 当前没有活动 Docker 环境、`.env` 或垂直验收脚本；不要假定旧容器/数据库仍存在。
- 下一窗口从读取交接文件和三份规划文件开始，不重复已完成的 focused review；Phase 5 未完成。

## 2026-08-19 · DeepTutor 复用审查进行中

- 已恢复 Phase 5/Task 10 handoff，确认 Task 10 blocked/abandoned、Phase 5 仍 in_progress，并保留根目录规划文件与 feature worktree 未提交修改。
- 对 C:\Users\asus\Downloads\DeepTutor-main\DeepTutor-main 完成只读初步审查：许可证/第三方 notices、解析/RAG/记忆/Agent/题库目录、依赖与存储边界已核对。
- 当前判断不是“直接复制粘贴即可”：DeepTutor 是文件目录 + 自有 Agent runtime；当前项目是多租户 SQLAlchemy + PostgreSQL/pgvector + Redis worker + MinIO。下一步等待独立子代理复审后形成最终复用矩阵和最小适配建议。

- 已创建 DeepTutor Phase 5 复用审查文档（feature worktree：docs/superpowers/reviews/2026-08-19-deeptutor-phase5-reuse-review.md）；未复制业务代码、未改依赖、未启动 Docker、未运行测试。下一步不应整库粘贴，而是先为 Phase 5 第 3 项设计原生 SQL schema/API（笔记、题目尝试、错题和来源），随后在确认边界后可选择性迁移纯辅助算法。

## 2026-08-20 · DeepTutor Phase 5 full reuse review completed

- 按用户要求完成只读复审，范围扩展到 DeepTutor `learning`、`mastery`、`book`、`memory/consolidator` 与 `agentic_pipeline`，并核对 Apache 2.0 LICENSE 与第三方 notices。
- 独立子代理完成第二次只读规格复审，结论一致：DeepTutor 的课程学习业务层高度相关，但不应整体复制为当前项目底座。
- 正式结论：优先迁移/重写掌握度、确定性评分、下一学习目标、间隔复习和标准答案服务端隔离；`learning/storage.py`、完整 `mastery` runtime、`book/compiler.py`、文件化 memory consolidator 和 `agentic_pipeline.py` 必须在当前 PostgreSQL/SQLAlchemy、多租户、引用、worker、Provider/Billing 边界内重写或仅作架构参考。
- 已新增正式报告：`.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-20-deeptutor-full-phase5-review.md`。
- 本轮没有复制代码、没有改依赖、没有启动 Docker、没有运行测试；根目录既有规划文件与 feature worktree 未提交修改均保留。
- Task 10 仍 blocked/abandoned；Phase 5 仍 in_progress。下一实施工作应先定义原生 SQL 学习域不变量，再实现不依赖 LLM 的答题—掌握度—复习闭环。


## 2026-08-20 · Learning Foundation first-slice outcome

- Restored the Task 10/Phase 5 handoff and preserved every pre-existing root and feature-worktree change. No Docker/Compose, full test suite, coverage gate, staging, commit, reset, or stash was performed.
- Added the focused `tutor_api.learning` implementation plus focused tests. Final local checks: **30 passed**, targeted Ruff passed, focused `git diff --check` passed. Pytest cache warning remains non-functional (`WinError 5` writing `.pytest_cache`).
- Fresh independent SPEC review: PASS after one targeted correction.
- Fresh independent QUALITY/SECURITY review: initial failures were corrected once; re-review remained FAIL with one Minor, same frozen-contract immutability rule for OPEN `expected_answer` accepting an arbitrary mutable value.
- Applied the user-approved stop rule: no third repair. Saved detailed evidence at `E:\项目\知识库课本\.worktrees\platform-foundation\docs\superpowers\reviews\2026-08-20-learning-foundation-review.md`.
- Phase 5 remains in progress; Task 10 remains blocked/abandoned and untouched. The next activity must be a separately scoped Phase 5 item.

## 2026-08-20 19:38 · Question Bank Foundation Task 1 started

- Restored planning context and verified eature/platform-foundation at 5a242dc; the known Task 10 edits remain untouched.
- Scope is limited to a tenant-aware ORM/migration schema for questions, question_versions, and question_attempts; no API, scoring, LLM, Docker, full suite, or coverage gate.
- A fresh independent implementation subagent was assigned TDD work. Required constraints: composite space/knowledge-base foreign keys, immutable DocumentVersion anchor, idempotent attempts, and no FK to the rebuildable chunks table.
- Stop rule remains initial implementation plus at most one targeted correction per acceptance rule.

## 2026-08-20 20:16 · Question Bank Foundation Task 1 completed

- Added the minimal tenant-aware persistence schema only: questions, question_versions, and question_attempts, plus migration  009_question_bank_foundation from  008_embedding_contract and Alembic metadata import.
- Contracts now enforce KB/space composite ownership, immutable DocumentVersion anchoring, per-question version uniqueness, tenant-aware attempt links, and (user_id, question_version_id, request_key_hash) idempotency.
- Each version retains a chunk provenance *snapshot* only; it has no chunks foreign key or ORM relationship, so reindex worker cleanup remains independent.
- Focused red test initially confirmed missing 	utor_api.question_bank. Final focused verification: 11 passed; Ruff passed using a temporary cache; target diff check passed (only pre-existing env.py line-ending notice).
- Independent SPEC review passed after one formatting-only correction. Independent QUALITY/SECURITY review initially found ORM/migration JSON-vs-JSONB drift; one targeted correction aligned the ORM with the migration and added dialect-resolution regression coverage. Quality/security re-review: PASS, no P0/P1/P2 findings.
- No Docker/Compose, Alembic upgrade, full suite, coverage gate, staging, committing, reset, stash, or protected Task 10/Learning file modification occurred.
- Task 2 (safe author/read/attempt APIs) is next; Phase 5 remains in progress and Task 10 remains blocked/abandoned.

## 2026-08-20 · Question Bank Foundation Task 2 complete

- Continued Phase 5 without revisiting blocked Task 10. Implemented only the authorized Question Bank API files and router registration; existing root records and protected Task 10/Learning changes were preserved.
- Initial focused API verification reached 18 passes. Independent spec review exposed the overlong-citation 422/404 mismatch and missing outsider-attempt direct coverage; one targeted correction resolved both, and a fresh spec review passed.
- Independent quality/security review then exposed one P1 resource issue (unbounded keyword aggregate plus public ORM overfetch). One targeted correction added bounds, `load_only`, and regression tests. The final independent quality/security re-review passed.
- Controller re-ran the limited verification: **20 passed**, targeted Ruff pass, targeted diff-check pass. The only warning was the existing FastAPI/Starlette TestClient deprecation warning.
- Created `docs/superpowers/reviews/2026-08-20-question-bank-foundation-task2-review.md`. Task 3 is not started because it requires a separate quality-approved learning-domain transaction contract; Phase 5 remains in progress.

## 2026-08-20 · Question Bank Task 3 assessment-contract plan

- **Status:** planned; implementation begins with Task 3A only. This is a native deterministic assessment ledger, not a revival of the stopped `tutor_api.learning` runtime.
- **Explicit v1 policy:** `choice`/`short` and open-without-keywords use normalized exact server-side matching; open-with-keywords uses normalized keyword phrase coverage; scores are integer basis points. Per-user/per-question-version assessment evidence is the limit of mastery scope.
- **Transaction target:** first idempotent submission must atomically write the attempt and one assessment; replay returns that stored evidence without recomputation or answer replacement. No teacher analytics, LLM grading, Agent work, course-level mastery, or dedicated review UI is in scope.
- **Plan:** `docs/superpowers/plans/2026-08-20-question-bank-assessment-plan.md`.

## 2026-08-20 · Question Bank Task 3A

- Controller re-ran the permitted focused verification: `20 passed`, targeted Ruff passed, and targeted whitespace checks passed (only LF/CRLF warnings).
- Independent quality/security re-review: FAIL/P2 because the AST import guard still misses `from tutor_api import learning`.
- Stop rule applied: one targeted correction had already been made for the ImportFrom isolation rule; no third patch will be attempted. Review evidence saved in the feature worktree.
- Task 3A is functional/spec-passing but **not** quality/security-passing; Task 10 remains blocked/abandoned and untouched.

## 2026-08-20 · Question Bank Task 3B

- Implemented the additive immutable assessment schema and migration with focused verification: `35 passed`, targeted Ruff and diff checks passed.
- Independent SPEC review passed. Quality/security first review found an incomplete private-field test gate; its permitted test-only correction was applied and re-verified.
- Quality/security re-review still found the same P2 at the ORM-vs-migration physical-column boundary. Stop rule applied: no third correction. Task 3B is functional/spec-passing but not fully quality/security-passing; current schema contains no prohibited private source/answer fields.
- Task 10 remains blocked/abandoned and untouched. Next independent scope: Task 3C atomic submit/replay API.

## 2026-08-20 · Question Bank Task 3C completed

- The controller resumed the original Task 3C implementer for the single allowed correction to a P1 consistency defect. The repair added a deterministic PostgreSQL transaction-scoped advisory lock per user and question version before idempotency replay lookup and historical assessment reads, preventing different-key concurrent submissions from persisting stale mastery or streak snapshots.
- Controller-focused verification: `15 passed`; targeted Ruff and the four-file diff check passed. Only the existing Starlette TestClient deprecation warning appeared.
- An independent read-only quality/security re-review found no P0/P1/P2 and confirmed transaction lifetime, lock order/scope, replay semantics, atomic rollback, private response boundaries, hidden 404/zero-write paths, and client assessment-field rejection. Review record: `.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-20-question-bank-assessment-task3c-review.md`.
- No Docker/Compose, Alembic, full suite, coverage, staging, commit, reset, stash, checkout, Task 10 file change, or `tutor_api.learning` change occurred. Real PostgreSQL concurrent E2E remains unrun by authorization boundary.
- Task 3C is complete/SPEC PASS/QUALITY PASS. Task 3A and 3B retain their prior P2 stop-rule records; Task 10 remains blocked/abandoned. Phase 5 remains in progress.
## 2026-08-20 · Next Phase 5 slice planned

- Persisted the narrow Task 4 owner review-queue contract before implementation. It uses current immutable assessment evidence only, requires both readable-KB authorization and an owner-only user filter, and defines safe projection, bounded keyset pagination, and no-write acceptance tests.

## 2026-08-20 · Question Bank Task 4 owner review queue completed

- Restored the Task 4 handoff and completed the independent read-only QUALITY/SECURITY review after the SPEC review had passed.
- The review found no P0/P1/P2: owner and tenant predicates are enforced, latest-assessment selection is stable, due filtering is UTC-based, keyset pagination is bounded, and private fields are excluded both from the response and ORM projection via `load_only(...)`.
- Controller verification remained limited to `tests/test_question_bank.py` (**20 passed**), targeted Ruff, and the four-file `git diff --check`; all passed.
- Review evidence is recorded at `E:\项目\知识库课本\.worktrees\platform-foundation\docs\superpowers\reviews\2026-08-20-question-bank-review-items-task4-review.md`.
- No Docker/Compose, Alembic, full suite, coverage, real PostgreSQL concurrency/performance, external provider, commit, reset, stash, or checkout was performed. Existing deprecation warnings are non-blocking.
- Task 4 is complete for its scoped contract. Task 10 remains blocked/abandoned; Task 3A and 3B keep their P2 stop-rule limitations; Phase 5 remains `in_progress` and requires a new separately scoped next task.
## 2026-08-21 · Question Bank Task 5 attempt-history plan

- Planned the next independent Phase 5 slice: a bounded owner-only read endpoint for all immutable assessment history of one question version.
- Scope is migration-free and read-only. It reuses readable knowledge-base authorization, filters by current user and tenant, uses `QuestionAttempt.created_at` for newest-first keyset pagination, and exposes only the already-approved safe assessment projection.
- It deliberately excludes answer keys, submitted answers, rubrics, provenance, identities, request hashes, Task 10, LLM/Agent work, and changes to `tutor_api.learning`.
- Plan: `.worktrees/platform-foundation/docs/superpowers/plans/2026-08-21-question-bank-attempt-history-plan.md`.
## 2026-08-21 · Question Bank Task 5 complete

- Completed the migration-free, read-only owner attempt-history slice at `GET /api/v1/knowledge-bases/{knowledge_base_id}/question-versions/{question_version_id}/attempt-history`.
- The endpoint authorizes readable KB access before the version lookup, keeps inaccessible/cross-tenant resources hidden as 404, limits history to the caller, uses the actual attempt time, and exposes only the planned safe DTO fields.
- Independent SPEC review passed. The reviewer’s only P2 was missing equal-timestamp paging coverage; one minimal test correction fixed that coverage without changing production logic. Independent QUALITY/SECURITY review then passed with no P0/P1.
- Evidence: focused question-bank test file `23 passed`; targeted Ruff `All checks passed!`; untracked four-file `git diff --no-index --check` emitted no whitespace diagnostics.
- Review record created: `.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-21-question-bank-attempt-history-task5-review.md`.
- No Docker/Compose/Alembic/full-suite/coverage/external APIs/Git staging or commit were run. Phase 5 remains in progress; Task 10 remains blocked/abandoned.

## 2026-08-21 · MVP 收口 / Phase 6 验收策略生效

- 用户决定停止以完成原 Phase 5 全部高级功能为当前目标，正式切换为：**MVP 主链路收口 → 一次集中审查 → Phase 6 客户验收 → 客户回款后扩展高级能力**。
- 已将“真实资料链路 Gate、学习闭环可见化、MVP 演示证据”合并为一个批次；批次完成后只做一次 focused verification、一次独立 SPEC 审查和一次独立 QUALITY/SECURITY 审查，不再为相邻小任务重复分别审查。
- 已明确延期：知识图谱、自生长笔记/教师治理、L0-L3 记忆、多 Agent、真实 LLM Tutor/流式对话/调用计费联动、生成式题目、教师分析、性能压测和非关键 coverage 优化。
- 新权威计划：`E:\项目\知识库课本\.worktrees\platform-foundation\docs\superpowers\plans\2026-08-21-mvp-closeout-phase6-acceptance-plan.md`。
- 未启动 Docker/Compose、Alembic、全量测试或重复历史测试；未改动任何业务代码；根目录和 feature worktree 的既有未提交状态均保留。

## 2026-08-21 · 新独立 MVP 范围审计纳入计划

- 新的只读子代理完成范围审计：知识库工作台可操作；题库闭环当前仅有 API/Swagger 可演示能力；“AI 家教”是未接真实 LLM、模型选择和费用结算的展示壳。
- 为避免客户误解，本期合并 MVP 批次增加三项客户可见收口：将 AI 家教展示壳降级/移除误导性承诺、接入最小题库学习者前端、让资料处理状态可持续刷新/显示。真实 LLM Tutor 保持延期。
- 审计未修改文件、未启动 Docker/Compose、未运行测试；结论已写入 MVP 权威计划。

## 2026-08-21 · MVP 主链路收口批次已开始

- 已按新计划派出一名唯一实现子代理处理一个合并批次：诚实降级未实现的 AI 家教展示壳、题库学习者 UI、资料处理状态的安全刷新/可见性及相称的 focused tests。
- 本批次不接真实 LLM、不伪造费用结算、不修复或重复 Docker Task 10；完成后才进行一次集中验证和一次独立 SPEC + QUALITY/SECURITY 审查。

## 2026-08-21 · MVP 收口实现因执行额度阻塞

- 唯一实现子代理已开始合并批次，并完成/写入部分前端与相关资料状态工作；没有启动 Docker/Compose、Alembic、全量测试、coverage 或真实 LLM/API。
- 子代理在继续写入收尾 CSS/测试时收到执行平台 `403 Forbidden：预扣费额度失败`。这是 Codex 执行额度问题，不是项目代码、Docker、API key、硬件或开发环境缺失。
- 当前只得到不完整的 focused 前端结果：21 tests 中 18 passed、3 failed；失败涉及新安全状态读取后的断言调整、一个 Testing Library 面板断言和题库面板 CSS 收尾。未将其标为通过，未启动集中审查。
- 按子代理驱动开发约束，不由 controller 重做已委派实现；待额度恢复后优先恢复同一子代理，限定完成已列出的收尾、focused tests、目标 lint/typecheck、API focused tests/self-review，随后才进入一次集中验证与双审查。

## 2026-08-21 · MVP 收口实现批次完成（进入集中审查）

- 原实现子代理已完成本批次：工作台移除误导性 AI 家教/模型/余额/费用承诺；接入题库练习学习者 UI；增加安全资料处理状态刷新；补齐相关前端测试与样式。
- Controller 复跑 focused verification：3 个前端测试文件 **21 passed**；目标 ESLint **PASS**；`tsc --noEmit --incremental false` **PASS**；目标改动 `git diff --check` 无诊断。
- 独立 SPEC 初审发现并已处理：根记录过时状态已由本条覆盖；MVP 历史范围收窄为最近一页；上传兼容响应字段不在 UI 展示，完整 DTO 收紧登记为后续契约优化。
- 当前状态：实现批次完成，等待一次集中 QUALITY/SECURITY 审查和 SPEC 复审；Phase 6 真实 Docker 资料链路仍未验收。

## 2026-08-21 · MVP 集中复审结果与修复闭环

- 独立 SPEC 复审：MVP 边界、题库最小闭环、资料状态刷新和延期清单通过；发现记录同步问题、上传响应 DTO 契约风险，以及完整历史分页 UI 缺口。历史 UI 已按本期“最近一页”口径延期，记录同步问题进入本次修复。
- 独立 QUALITY/SECURITY 复审：未发现 P0；跨租户授权、题库答题归属、后端 Idempotency-Key/事务、状态 endpoint IDOR、私密答案/rubric/提交内容和不可信文本渲染均通过。发现 P1 上传响应暴露内部 job/hash/空间字段，以及题库和资料刷新请求的异步取消竞态。
- 当前唯一修复批次：收紧上传响应和前端 DTO；修复题库切换/取消时 loading 与旧结果污染；让同一答题重试复用同一幂等键；修复不同上传项状态刷新互相取消后的状态卡死。未重开 Task 5/Task 10，不运行全量测试或 coverage。
- 当前仍不能声明 Phase 6 通过：真实 PostgreSQL/pgvector 资料导入→索引→检索→来源/原页链路仍待新鲜隔离环境实证。

## 2026-08-21 · MVP 复审闭环完成，准备 Phase 6 真实验收

- 最终独立窄复审：PASS，P0=0、P1=0、P2=0。
- 关闭项：上传响应内部字段边界；题库切题/切换知识库/取消请求竞态；题库 loading 卡死；答题网络重试幂等键复用；提交成功后复习列表刷新失败时的幂等键保留；多个上传项状态刷新互相取消。
- 最新 focused 证据：API 上传相关 61 passed；Web focused 3 files / 22 tests passed；题库面板回归 4 passed；目标 Ruff/ESLint/TypeScript 通过；差异检查通过。
- 当前进入 Phase 6：只剩新鲜隔离环境的真实资料导入→处理→检索→来源/原页证据、题库 UI/API 演示记录和客户验收包。真实 Docker/pgvector 仍未通过，不能改写旧失败事实。

## 2026-08-21 · Phase 6 首次尝试：环境阻塞

- MVP 窄复审已 PASS（P0/P1/P2 均为 0），随后按计划尝试新鲜隔离 Compose 验收。
- 当前 Codex PowerShell 中 `docker version` 失败：`docker` 不是可识别的 cmdlet、函数、脚本文件或可运行程序；因此未启动 Compose、未执行 Alembic、未清理任何容器/数据卷。
- 这不是代码验收 FAIL，也不能被解释为真实链路 PASS；Phase 6 的 Docker/pgvector Gate 仍为 environment-blocked，旧的 2026-08-19 Task 10 FAIL 事实继续有效。
- 已准备下一会话交接：`E:\项目\知识库课本\.worktrees\platform-foundation\docs\superpowers\handoffs\2026-08-21-mvp-phase6-entry.md`。

## 2026-08-21 · Phase 6 新鲜隔离环境真实资料 Gate 结果

- 已找到并授权使用 Docker CLI：`C:\Users\asus\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`；Docker Server `29.7.2`，Compose `v5.3.1`。
- 在 `E:\项目\知识库课本\.worktrees\platform-foundation` 使用 `.env.identity-test` 启动全新隔离项目 `mvp-phase6-20260821`；PostgreSQL/pgvector、Redis、MinIO、API、Worker、Web 启动成功，API/Web 健康，Alembic 当前为 `0010_question_attempt_assessment (head)`。
- 真实请求已完成：注册临时用户 → 创建个人知识库 → 上传 `acceptance.md`（唯一 token）成功，上传响应仅含 `document_id`、`document_version_id`、`source_name`、`created_at`。
- 真实资料 Gate 未通过：状态由 `processing` 变为 `failed`；数据库 `ingestion_jobs` 显示 `parse_document=completed`，`build_index=failed`，`attempt_count=3/max_attempts=3`，`last_error_code=index_validation_failed`。本次观察到 `pages=1`、`chunks=0`、`index_versions.state=failed`；搜索和来源/原页预览因此未执行为 PASS。
- 结论：服务健康、数据库迁移和上传链路通过；真实资料“解析后构建索引→检索→来源预览”仍是 FAIL。结合 2026-08-19 旧环境同类失败，按 stop-rule 不再无依据反复调参，不把 focused tests 或服务健康写成端到端通过。
- 未修改代码，未运行重复全量测试；现有未提交记录保持不变。隔离 Compose 项目暂保留用于客户/后续故障复盘。

## 2026-08-21 · Phase 6 一次性索引根因诊断（只读/事务回滚）

- [x] 在保留现有 Compose 项目和数据的前提下，对失败的单 chunk build_index 做逐字段诊断；诊断事务已回滚，未写入验收数据库。
- [x] `ordinal`、空间/知识库/版本/page/block、source pointer、content、SHA、lexical terms、dimension、index signature 全部一致。
- [x] 唯一失败字段为 embedding：PostgreSQL/pgvector 返回的 Python float64（如 `-0.15858996`）与 expected 的 float4 canonical Python 值（如 `-0.15858995914459229`）表示同一 float4，但现有精确比较器误判。
- [ ] 仅授权一次窄修复：两侧均按 float4 量化后严格比较，并补最小回归；修复后只做目标验证。
- **Stop-rule：**若该窄修复后的目标验证或真实链路仍失败，不再继续调参；真实资料检索 Gate 保持 FAIL。

## 2026-08-21 · Phase 6 索引校验窄修复完成

- 根因已确认：PostgreSQL/pgvector 返回的 float4 十进制文本解析为 Python float64 后，旧比较器使用 Python 列表精确相等，误判同一 float4。
- 窄修复仅涉及 `apps/api/src/tutor_api/knowledge/indexing.py` 与 `apps/api/tests/test_knowledge_indexing.py`：按 float4 的 IEEE-754 32 位表示比较，保留长度、有限性、溢出和类型的 fail-closed 约束；新增 signed-zero（`+0.0`/`-0.0`）拒绝回归测试。
- 独立子代理完成修复且未执行 Git staging/commit/reset/stash/checkout。
- 最小验证：`persisted_embedding` 相关测试 9 passed；目标 Ruff 通过；`git diff --check` 通过；未运行全量测试、coverage 或外部服务。
- 该结果只证明代码层比较器修复，不证明真实 Docker/PostgreSQL/pgvector 资料链路已通过。

## 2026-08-21 · Phase 6 真实资料链路修复后唯一重验通过

- 使用已知 Docker CLI `C:\Users\asus\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`，保留隔离 Compose 项目 `mvp-phase6-20260821` 及其数据卷；仅重建 `api`/`worker`，未清理容器或卷。
- Docker Server `29.7.2`、Compose `v5.3.1`；服务健康；Alembic `0010_question_attempt_assessment (head)`。
- 新临时用户/知识库/Markdown 上传成功；上传部件明确使用 `text/markdown`，避免验收客户端 multipart 类型误报。
- 修复后真实状态：`processing` → `searchable`；唯一 token 搜索 `results=1`；citation source preview `206 Partial Content / text/markdown; charset=utf-8`；page preview `206 Partial Content / text/plain; charset=utf-8`。
- 结论：Phase 6 真实资料导入→处理→检索→citation/source/page preview Gate **PASS**。2026-08-19 和本次修复前的 `index_validation_failed` 保留为历史失败事实，不与本次 PASS 混淆。
- 未使用 OCR/Embedding/LLM 外部 API key；本次验证走现有本地确定性 embedding 配置。
- MVP 验收记录已更新；高级 LLM Tutor、OCR/远程 embedding、知识图谱、长期记忆、多 Agent、生成式题目、教师分析、性能压测和非关键 coverage 仍延期。

## 2026-08-30 · AI 助教与知识候选组件级恢复

- 修改 `apps/web/src/components/workspace/agent-panel.tsx`：failed/archived 会话不再可写，旧 Claude/Fable provider 历史不再恢复。
- 为 URL、localStorage、最近会话、仅失败/归档/旧 provider 历史补充 AgentPanel 回归测试。
- 修改 `apps/api/src/tutor_api/knowledge/candidates.py`：支持空/单个/多个公式校验列表；多公式、变量映射与状态无损聚合；跨块同 key 候选合并 markdown、公式、来源、source pointers。
- 修改 `apps/api/src/tutor_api/knowledge/worker.py`：持久化安全稳定的候选校验错误码，继续清空 error detail。
- API 知识候选相关回归退出码 0；Ruff 通过；Web 3 files / 32 tests passed；ESLint 通过；`git diff --check` 通过。
- 真实 AI 助教 smoke：注册/知识库/会话成功，turn=202，事件包含 turn_started、user_message、model_text_delta、session_state，最终 `E2E_RESULT=pass`。
- 数据库复核：知识候选 job completed、attempts=6/6、last_error_code 为空；batch needs_review、29 notes、0 links。
- Docker 当前 api/web/postgres/redis healthy，worker/minio running。

## 2026-08-30 · Web 代理 AI 助教回调修复

- 新增 `Settings.agent_runtime_callback_url`，默认 `http://127.0.0.1:8000/api/v1/agent/runtime/events`。
- `agent/router.py` 的 turn callback 改为读取可信配置，不再使用 `request.url_for()`。
- `.env.example` 与 Compose 的 API/Worker 环境增加 `AGENT_RUNTIME_CALLBACK_URL`；未输出或修改任何密钥。
- 新增回归：即使请求 Host 为 `web:3000`，Runtime payload callback 仍为可信配置且不包含 `web:3000`。
- API 镜像重建并重启 API/Worker；服务健康。
- 经 Web 代理 `http://127.0.0.1:3100` 完整 E2E：turn 202、accepted sequence 1、事件包含 model_text_delta、最终 completed/waiting_input、E2E pass。
- 真实 UI 会话 `3bfc987d-1bd0-4a68-9bd5-f69c48d41587` 数据库证据：`turn_started,user_message,model_text_delta:UI_QA_OK_20260830,session_state:completed`，session waiting_input，cursor 4。
- 聚焦 Agent + 知识候选 API 测试通过；Web 32 tests 通过；Ruff/ESLint/diff check 通过。
- 全 API 套件曾额外运行但存在 10 个与本补丁无关的既有基线失败：测试仍期待旧 context window/旧迁移 head，以及本地 `.env` 令 health 测试尝试解析 Docker DNS `postgres`。聚焦修改范围回归全部通过。

## 2026-08-30 · 组件级 UI 最终验收与提交前验证

- 真实 Web 页面 `http://127.0.0.1:3100` 已刷新并读取可见 DOM；知识候选审核区显示 3 条候选及“确认并生成层级知识库”按钮。
- 同一真实 UI 会话已显示 Gemini 返回文本 `UI_QA_OK_20260830`；这不是 Faro health 检查，而是 Web → API → Runtime → Faro/Gemini → callback/event → UI 的最终画面证据。
- 提交前新鲜验证：API 聚焦回归全通过；Web 全量 35 files / 238 tests 通过；ESLint 与目标 Ruff 通过；`git diff --check` 无错误（仅 CRLF 提示）。
- 远程 `github-collab` fetch 连续 3 次因本机到 github.com:443 连接失败而未完成；本地远程跟踪引用与提交前 HEAD 均为 `666535a`。后续使用普通非强制 push，若远程已前进会安全拒绝，不会覆盖协作者提交。

## 2026-08-30 · GitHub 提交完成

- 本地提交：`a568c12 fix: restore candidate generation and proxied agent turns`，11 个文件，336 additions / 12 deletions。
- 常规 Git HTTPS 因当前 DNS 路径上的 `github.com:443` 不可达而失败；改用已认证的 GitHub Git Data API，先验证远端分支仍停在父提交 `666535a`，再逐 blob/tree/commit 上传。
- API 创建的 tree 与 commit SHA 均与本地 Git 对象完全一致，随后以 `force=false` 更新远程分支。
- GitHub API 二次读取确认远程 SHA 为 `a568c12e1bbf63660f1262901b76a31407f15d1d`；本地 remote-tracking ref 已同步，`HEAD...github-collab/feature/platform-foundation-wip = 0/0`。

## 2026-08-30 · 组件级二次审计发现 WebSocket 代理缺口

- 最终 UI DOM 虽已显示持久化的 `UI_QA_OK_20260830`，但连接状态仍为“正在重连（第 5 次）”。
- 根因是浏览器默认连接 `ws://127.0.0.1:3100/api/v1/agent/ws/...`，而当前 Next catch-all route 仅实现 HTTP fetch proxy，不代理 WebSocket upgrade。
- 这意味着先前的 Web HTTP E2E 与刷新后消息回放均通过，但“发送后无需刷新即可实时看到回复”的 UI 链路仍有缺口；不能仅凭 Faro health、HTTP poll 或数据库事件宣称组件完全恢复。
- 正在为同源 Next HTTP 代理模式增加事件轮询 fallback，同时保留显式 API base 下的 WebSocket 路径。

## 2026-08-30 · AI 助教 UI 实时连接缺口完成修复

- 二次审计确认 Next 的 HTTP catch-all 不能代理 WebSocket upgrade，导致 UI 虽能刷新回放模型结果，却持续显示“正在重连”。
- `apps/web/src/lib/agent-api.ts` 已在同源 Next HTTP 代理模式自动使用 500ms HTTP polling；显式 API base/WebSocket 实现仍保留。
- polling 支持 cursor 推进、事件分发、401/403 停止、指数退避、Abort 和 timer cleanup；新增对应回归测试。
- 新鲜验证：Web 全量 35 files / 243 tests 通过；ESLint 通过；Next production build 成功；Web 容器重建并 healthy。
- 真实页面刷新后稳定显示 `已连接 · cursor 4`，同时保留可见 Gemini 回复 `UI_QA_OK_20260830`，不再显示“正在重连”。
- 最终提交 `b99879f fix: poll agent events through web proxy` 已以非强制方式同步到 GitHub；远程 API 再确认同 SHA，本地与远程 `0/0`。

## 2026-08-30 · AI 助教真实故障修复进行中

- 已确认三个独立根因：UUID 显示兜底错误、user_message 字段合同不一致、linked_contexts 被 API 静默丢弃。
- 三个子代理按 Web / API / Runtime 不重叠写集并行实现 focused 修复；主线程负责审查集成、重建服务、真实 UI 验收和 GitHub 同步。

## 2026-08-30 部署与验收
- [x] 重建并替换 API/Web 容器，均 healthy。
- [x] 使用仓库脚本安全重启 Agent Runtime；health=ok，protocol=1.0，Node=24.18.0。
- [x] 浏览器验证知识库标签不显示 UUID。
- [x] 浏览器验证用户消息显示完整原始提问，且不泄露内部检索上下文。
- [x] 浏览器验证 Faro 返回基于真实知识库片段的答案，不再出现 provider_execution_failed。
- [x] 刷新后事件历史仍可恢复，连接 cursor 正常增长。
- [x] Runtime：25 suites / 92 tests passed，typecheck/build passed。
- [x] Web：35 files / 246 tests passed，lint/build passed。
- [x] API focused：47 tests passed，Ruff passed。

## 2026-08-30 · Phase 7 started

用户确认接入 qyw211 商讨后的支付、账户面板、欢迎页等低冲突功能；明确不接入 qyw 的 AI 助教、知识检索、题库生成和 workspace 主布局改动。当前稳定 HEAD 为 7dcbc5b，工作树只有未跟踪 .tmp/。已派发两个 disjoint 子任务：Web 独立页面/账户面板与 API 支付基础移植；待回收后进行手工整合与回归验证。

## 2026-08-30 · qyw211 Web 账户/欢迎页选择性移植

- 按用户范围只提取 `c53f459` 的 Web 账户面板、billing API、欢迎页及欢迎页样式；未修改 API、AI 助教、知识库核心或 `workspace-shell` 主布局。
- 账户面板改为独立 `account-panel.module.css`，保持可复用组件形式并避免依赖/覆盖工作台主 CSS。
- 为账户面板的二维码渲染加入 Web 工作区 `qrcode` 与 `@types/qrcode` 依赖；未接入 qyw 的 API 支付后端，避免引入迁移冲突。
- 下一步：运行 Web 测试、lint、类型检查和生产构建，核对 diff 后再决定提交。

- Web 回归完成：账户面板定向测试 7/7；全量 Web 测试 36 个文件、274 项通过；`tsc --noEmit`、ESLint、Next 生产构建均通过。
- 构建确认新增 `/welcome` 静态路由；工作台主布局文件未被本次选择性移植修改。
- 本次新增文件仅限账户面板组件/独立样式/测试、billing API、欢迎页及欢迎页样式；`apps/web/package.json` 与 `pnpm-lock.yaml` 仅为二维码依赖变更。

## 2026-08-30 · qyw211 支付后端选择性接入收尾

- 完成范围：仅接入 `apps/api/src/tutor_api/billing/` 的支付 gateway、订单模型、service、router、schemas；保留人工充值、钱包 reservation/settle/release、冲正与 ledger 路径。
- 新增迁移：`apps/api/migrations/versions/0019_recharge_orders_payment.py`，严格从 `0018_object_deletion_outbox` 继承；修正 SQLite/PostgreSQL 下 Enum 重复 CHECK 约束，改由显式稳定约束负责校验。
- 新增支付回归：`apps/api/tests/test_billing_payments.py`、`apps/api/tests/test_wechat_gateway.py`；同步更新 `apps/api/tests/test_schema.py` 中当前 head 断言为 `0019_recharge_orders_payment`。
- 验证：支付测试 20 passed；人工充值/钱包/Schema 聚焦组通过；完整 API 测试除一个既有 Compose worker 环境等价性断言外，其余通过。该失败来自现有 `compose.yaml` 与 API 新增支付环境变量未同步，本轮按用户要求未修改 compose。
- 迁移验证：fresh SQLite `upgrade head → downgrade 0018 → upgrade head` 通过，最终 head 为 `0019_recharge_orders_payment`；离线 SQL 中 provider/state CHECK 各出现一次。
- 根目录生成的 `.tmp_*` 审计临时文件已逐一删除，`.tmp/` 验收资料目录保留。

## 2026-08-30 · 选择性接入支付/账户/欢迎页最终回归

- qyw211 的大杂糅提交未整体 merge/cherry-pick；未接入其 AI 助教、Faro、知识库检索、题库生成或 workspace 重构。
- 已接入支付后端：mock 默认模式、支付宝/微信网关边界、充值订单、回调验签、金额不匹配保护、幂等入账和现有钱包流水/人工充值/冲正复用。
- 已接入账户面板与工作台“账户与充值”入口；账户面板可查看余额/流水、创建 mock 充值订单并完成本地确认。真实支付密钥为空时不会阻塞 mock 本地启动。
- 已接入独立 `/welcome` 欢迎页与登录/注册入口，不改变 AI 助教和知识库主页面布局。
- 迁移从当前稳定 `0018_object_deletion_outbox` 线性延伸至 `0019_recharge_orders_payment`，避免 qyw 分支迁移编号冲突。
- 验证结果：支付/网关/管理员充值 34 passed、Web 全量 36 files / 274 tests passed、API 全量 1164 passed / 8 skipped（修复 Compose worker 环境同步后）、目标 Ruff passed、TypeScript passed、ESLint passed、Next production build passed、Alembic `upgrade head --sql` passed。
- `compose.yaml` 的 api/worker 环境变量已保持一致，避免 worker 回归失败；未提交 `.env`、密钥、`.tmp/` 或迁移检查临时文件。

## 2026-08-30 · 选择性功能已提交并推送

- 功能提交：`4cb8e31 feat: add account recharge and welcome experience`。
- 已通过普通非强制 Git push 同步到 `github-collab/feature/platform-foundation-wip`；未触碰 main，避免覆盖其他分支内容。
- 远程分支可供队友下载审查；`.env`、密钥和 `.tmp/` 未纳入提交。