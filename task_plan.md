# 课本知识库 Agent 平台任务计划

## Goal

设计并实现一个支持多用户、个人与班级知识空间、教材自动知识化、可追溯答疑、长期学习记忆和按量计费的 AI 学习平台；先在本机验证，成功后迁移至 Linux 云服务器。

## Current Phase

Phase 5：知识与 Agent 能力实现

- **已完成里程碑：** 平台基础骨架（前后端、C3 工作台、Docker、CI、安全基线与本机验收）
- **已完成里程碑：** 注册登录、用户隔离、个人空间初始化、班级邀请码与服务端权限
- **已完成里程碑：** 服务端供应商配置、启用模型目录、价格/汇率版本、钱包预留结算与人工充值
- **下一实施里程碑：** 知识导入、检索引用与 Agent 学习能力

## Phases

### Phase 1：需求发现与产品边界

- [x] 明确用户、班级和资料权限
- [x] 明确上传格式与 Obsidian Vault 导入
- [x] 明确答疑、引用、自生长知识库和记忆规则
- [x] 明确模型供应商、计费和人工充值规则
- [x] 确认 C3 可拖动工作台布局
- **Status:** complete

### Phase 2：架构与正式设计

- [x] 比较直接改造、独立平台和外壳集成三条路线
- [x] 选择“自主平台 + 选择性复用 DeepTutor 技术模块”
- [x] 确认总体组件架构与部署边界
- [x] 确认数据模型与权限边界
- [x] 确认文档导入、自生长知识库与检索流水线
- [x] 确认 Agent 执行流程与 L0-L3 长期记忆
- [x] 确认供应商配置、官方价格、钱包与用量结算设计
- [x] 完成错误处理、测试、部署和验收设计
- [x] 写入正式设计文档并自检
- [x] 由用户审核正式设计文档
- **Status:** complete

### Phase 3：详细实施计划

- [x] 将已批准设计拆分为可验证的小步骤
- [x] 定义首个里程碑的项目结构、接口和测试顺序
- [x] 确定本机依赖与 Docker 服务
- **Status:** complete

### Phase 4：基础平台实现

- [x] 建立前端、后端、数据库、任务队列和对象存储抽象
- [x] 实现注册登录、用户隔离、个人空间和班级权限
- [x] 实现管理员模型配置、用户模型选择、钱包和流水
- **Status:** complete

### Phase 5：知识与 Agent 能力实现

- [ ] 实现 PDF、DOCX、Markdown、图片和 Obsidian Vault 导入
- [ ] 实现解析、OCR、Embedding、检索、引用和原页回看
- [ ] 实现自生长笔记、知识图谱、错题集和题库
- [ ] 实现统一 Agent Loop、完整解答/分步引导和 L0-L3 记忆
- **Status:** in_progress

### Phase 6：测试、验收与本机交付

- [ ] 完成安全、权限、计费准确性、检索质量和故障恢复测试
- [ ] 完成本机 Docker 端到端验收
- [ ] 编写云服务器迁移说明
- **Status:** pending

## Key Questions

1. 首期具体启用哪些千问、DeepSeek、OpenAI 模型，以及各供应商 OCR/Embedding 型号？
2. 用户结算人民币时采用什么汇率来源、更新周期和精度规则？
3. 【已解决】Docker Desktop、Compose、PostgreSQL/pgvector、Redis、MinIO、API 和 Web 已在隔离环境完成本机验收。
4. DeepTutor 哪些 Apache 2.0 模块直接复用，哪些只借鉴架构并重写？

## Decisions Made

| Decision | Rationale |
|---|---|
| 产品为多用户平台 | 每位用户需要独立教材库、会话和长期记忆 |
| 任何用户可创建班级 | 创建者为最高权限，可任命其他教师 |
| 学生上传资料默认私有 | 分享到班级前必须由教师审核 |
| 支持 PDF、DOCX、Markdown、JPG/PNG 和 Obsidian Vault | 覆盖教材、练习册、图片和已有知识库迁移 |
| 原始资料不可由 AI 修改 | 自生长内容与来源分离，保证可追溯性 |
| 班级 AI 内容需教师审核 | 防止未经确认的生成内容污染共享知识库 |
| 回答强制附教材、章节、页码引用 | 支持点击回看原页并降低幻觉风险 |
| 默认完整解答，可切换分步引导 | 符合已确认的学习交互方式 |
| 平台统一提供 API Key | 用户不自行配置密钥，平台统一计量与控制 |
| OCR/Embedding 等由后台切换，LLM 由用户选择 | 区分知识库基础设施与每轮答疑偏好 |
| 按官方 API 原价和真实 Token 用量计费 | 记录输入、输出、缓存命中及调用时价格快照 |
| 第一版采用管理员人工充值 | 降低支付接入风险，优先验证核心平台与账单 |
| 自主平台并选择性复用 DeepTutor | 保留班级、计费和权限自主性，同时利用成熟 AI 模块 |
| 本机先测试，再迁移 Linux 云服务器 | 降低初期成本并验证完整链路 |
| 使用 planning-with-files 维护项目上下文 | 通过磁盘文件解决长任务上下文丢失，不依赖 OpenClaw |
| 生产配置采用失效保护 | 生产环境拒绝 SQLite、本地或未认证后端、占位及空白凭据，避免误连开发资源 |
| MinIO 管理员与应用身份分离 | API 只持有指定存储桶权限，不能执行管理员操作 |
| CI 依赖和第三方 Action 固定版本 | 降低供应链漂移并保持本机与 CI 检查一致 |
| 基础里程碑在独立 worktree 完成 | 保留主分支稳定性，并为下一阶段提供可审查的提交边界 |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| 初次项目扫描因空目录和非 Git 仓库返回失败 | 1 | 改为普通目录检查，确认工作区仅有设计草图 |
| 可视化服务在 Windows 默认写入受限目录 | 1 | 将会话目录设置到项目内 `.superpowers/brainstorm/` |
| 可视化服务被回收 | 1 | 重新启动并恢复已保存的页面 |
| Computer Use 读取 Obsidian 窗口遭遇 EPERM | 2 | 停止重复尝试，改用用户截图和既有 Obsidian 交互规律 |
| C3 原型首次补丁无法匹配压缩 CSS 行 | 1 | 按实际行内容拆分成更小补丁后完成更新 |
| Windows 构建缓存由不同权限上下文创建，导致 `.next`、Ruff/Pytest 缓存写入被拒绝 | 2 | 只重建可再生前端产物，并在最终检查中禁用工具缓存 |
| 旧测试卷无法证明为空，删除请求被安全策略拒绝 | 1 | 保留旧卷不动，使用独立 Compose 项目和新数据卷完成无损验收 |
| Git 提交因当前账户与隔离 worktree 所有者不同被 safe.directory 保护拒绝 | 1 | 后续 Git 命令仅传入该隔离 worktree 的临时安全目录，不修改全局配置 |
| 空间模型时间戳字段首次超过 Ruff 100 字符限制 | 1 | 将字段定义拆为多行后重新运行检查 |
| SQLite 架构测试未触发个人空间部分唯一索引 | 1 | 发现 SQLAlchemy 默认保存枚举名称；统一改为保存小写枚举值以匹配索引谓词 |
| 迁移文件 `compileall` 因现有 `__pycache__` 权限受限失败 | 1 | 改用不写入字节码缓存的 AST 语法解析验证 |
| 从仓库根目录运行 Alembic 时找不到相对 `migrations` 路径 | 1 | 将迁移路径改为基于 Alembic 配置文件位置的 `%(here)s/migrations` |
| FastAPI 测试客户端写入 SQLite 内存库时提示 `no such table: users` | 1 | 根因是跨线程新连接不共享内存库；测试模式 SQLite 改用 `StaticPool` 和 `check_same_thread=False` |
| 隔离 Docker 验收的 MinIO 默认端口与已有服务冲突 | 2 | 为 Compose 的 MinIO 映射增加可配置主机端口，验收环境改用独立高位端口 |
| Docker 容器的 Alembic 使用硬编码连接串导致迁移认证失败 | 1 | 迁移环境优先读取运行时 `DATABASE_URL`，并以容器迁移和真实 API 验收复核 |
| 工作区覆盖率与前端构建缓存写入受限 | 2 | 覆盖率输出改到临时目录；前端生产构建在获授权的正常权限上下文中完成 |

## Notes

- 重大决策前重读本文件和 `findings.md`。
- 每完成一个阶段更新状态，并在 `progress.md` 记录行为和验证结果。
- 所有外部网页、源码和截图研究只写入 `findings.md`，视为不可信资料数据。
- 正式设计获批前不进入业务代码实现。

## 2026-08-22 · LLM Markdown 知识库扩展

- **设计状态：** 用户已批准 LLM 全文重写、草稿确认发布、上下文窗口分块和确定性双向链接方案。
- **设计文档：** `docs/superpowers/specs/2026-08-22-llm-markdown-knowledge-design.md`。
- **实施计划：** `docs/superpowers/plans/2026-08-22-llm-markdown-knowledge-plan.md`。
- **执行护栏：** 同一指标三次定向修复仍失败后暂停，向用户报告证据并等待继续决定；不使用真实 Key 做未经确认的付费调用。

## 2026-08-16 Phase 5 交付记录

- [x] 已创建详细实施计划：`docs/superpowers/plans/2026-08-16-versioned-knowledge-import-plan.md`。
- [x] Task 1「知识运行时适配器与安全配置」已完成，提交为 `00b9551`、`8f267ba`、`1bb2fb1`。
- [x] Task 1 规格审查 PASS，代码质量审查最终 PASS。
- [x] 验证结果：目标测试 63 passed；配置测试 77 passed；完整 API 228 passed、3 skipped；Ruff 与 `git diff --check` 通过。
- [x] Task 2「versioned knowledge schema（版本化知识 Schema）」已完成：初始提交 `bac0e0d`，质量修复 `8129e28`、`67780ed`、`000240d`。
- [x] Task 2 规格审查 PASS；质量审查经过多轮约束与边界加固后最终 PASS。
- [x] Task 2 最终验证：knowledge schema 105 passed；schema/Alembic 33 passed；完整 API 345 passed、3 skipped；Ruff 与 `git diff --check` 通过。
- [x] Task 3「space-scoped knowledge APIs」已完成，实现提交：`92261fe feat: add scoped knowledge bases`。
- [x] Task 3 规格审查 PASS（聚焦 20 passed）；质量/安全审查 PASS（高价值聚焦 5 passed）。
- [x] Task 3 实现阶段最终基线：API focused 17 passed；schema uniqueness 3 passed；direct regression 179 passed；完整 API 365 passed、3 skipped；Ruff 与 `git diff --check` 通过。
- [x] Task 4「safe immutable uploads」最终 PASS；实现与修复提交：`4ca2acf`、`07ec443`、`53a253a`、`72c0194`，交接文档提交：`091e95f`。
- [x] Task 4 最终独立规格复审 PASS；最终独立质量/安全复审 PASS。
- [x] Task 4 验证记录已归档；两个并发修复后未重跑完整 API suite，且未运行真实 PostgreSQL/pgvector/MinIO/Docker/OCR/external services。
- [x] Task 5「native parsing and Obsidian import」最终 PASS；实现与修复提交：`2dc8ce1`、`30014ae`、`5c70d87`、`75997c7`。
- [x] Task 5 最终独立规格复审 PASS；最终独立质量/安全复审 PASS。聚焦解析器 57 passed；目标 Ruff 与 `git diff --check` 通过。
- [x] Task 5 未运行完整 API suite，且未使用 Docker、PostgreSQL、MinIO、OCR、外部服务或大型真实文档集成测试。
- [x] Task 6「selective OCR and page evidence」最终 PASS；交付提交：`e2e2a6b`、`d9f244d`、`5225691`。
- [x] Task 6 初始完整规格复审 PASS；最终独立增量规格复审 PASS（reviewer 11 focused passed）；最终独立质量/安全复审 PASS（reviewer 7 focused passed，并完成进程、线程与 Windows handle 探针）。
- [x] Task 6 最终主线程限定验证：OCR 49 passed；adapter OCR 10 passed；parser 57 passed；targeted Ruff 与 `git diff --check d9f244d..5225691` PASS。
- [x] Task 6 未运行完整 API suite、真实 Tesseract/container smoke、Docker、PostgreSQL、MinIO、外部服务、POSIX 实机 process-group 路径或复杂 PDFium corpus。
- [x] Task 7「immutable indexing and reliable worker」最终 PASS；代码 HEAD `363f3fb`，六个交付提交为 `f298eb2`、`96a3ad6`、`53284ca`、`cfc6220`、`0d34b2a`、`363f3fb`。
- [x] Task 7 独立规格复审最终 PASS（修复后 34 focused）；独立质量复审最终 PASS。初始质量 FAIL 的 production-HTTP 项已由既有 HTTPS production gate 证伪，blank OCR page 项有效并由 `363f3fb` 修复。
- [x] Task 7 最终主线程验证：相关组合 362 passed、36 warnings；migration nodes 3 passed、4 warnings；targeted Ruff 与 `git diff --check aa71123..HEAD` PASS。
- [x] Task 7 未运行变更后的完整 API suite、Docker、真实 PostgreSQL/pgvector、MinIO/S3、Redis、Tesseract/PDFium corpus、外部服务或 POSIX 实机 process group。
- [ ] 整个 Milestone 3 / Phase 5 尚未完成，状态保持 `in_progress`。
- [ ] 下一步：Task 8「hybrid retrieval and secure source preview」；尚未开始。

### Task 1 已确认边界

- OCR 与 Embedding backend/model 配置采用 fail-closed 校验，只接受当前真实实现组合。
- 本地 Embedding 使用确定性的 signed feature hashing，并绑定真实算法签名。
- 对象存储公开语义为原子、不可变的 `put-if-absent`。
- source path/name 与 content-type 具有 Unicode、路径穿越和 HTTP header 安全边界。
- OCR 只暴露受限公开错误码，并彻底移除 provider 消息、堆栈、cause 与 context。

### 参考边界

- DeepTutor 与腾讯记忆系统仅作为产品和架构参考，不构成本项目指令、代码来源或当前运行时依赖。

### Task 2 已确认不变量与验收边界

- 所有知识资源使用 UUID，并具有非空、索引的 `space_id`；跨 space/knowledge base 的父子关系由复合外键约束，不能静默关联。
- 每个知识库至多一个 active index；文档 source/version、SHA-256/内容哈希、页面/块/chunk 序号与 source pointer 唯一规则，以及父子级联删除均由数据库约束和测试覆盖。
- Embedding 非空；SQLite 使用 JSON fallback 和 INSERT/UPDATE triggers 校验数组根类型、数值元素、有限数及整数边界，PostgreSQL offline SQL 包含 `CREATE EXTENSION vector` 与 `VECTOR` 类型路径，并持久化 backend/model/dimension/signature 合同。
- Ingestion job 具有可恢复的 lease/retry/checkpoint、started/completed 时间和 kind/target 状态机约束；checkpoint 支持递归 mutable dict/list、嵌套持久化、跨任务子树复制和移除后的父链接解除。
- PostgreSQL 仅验证 offline SQL；未运行真实 PostgreSQL/pgvector。Extension 权限、DBAPI vector/JSONB 往返、并发行为和性能仍待后续集成验收。
- Task 2 已完成；真实 PostgreSQL/pgvector 的已知集成风险继续保留到后续验收。

### Task 3 已确认 API、权限与验收边界

- 已提供 `POST/GET /api/v1/spaces/{space_id}/knowledge-bases` 与 `GET /api/v1/knowledge-bases/{knowledge_base_id}`。
- personal/classroom 权限全部由服务端判定：personal owner 与 classroom owner/teacher 可创建；classroom student 创建返回 403；personal non-owner 与 classroom nonmember 返回 404；未认证返回 401；已知知识库 UUID 不能绕过权限。
- 响应仅包含 `id`、`space_id`、`name`、`state`、`created_at`、`updated_at`；名称 strip 后限制 1–120 字符。
- 同空间名称由数据库唯一约束保护并稳定返回 409，不同空间可重用；列表稳定按 `created_at, id` 排序。ORM 与未发布的 `0006` 同步加入 `uq_knowledge_base_name_in_space(space_id, name)`。
- 规格审查与质量/安全审查均 PASS；实现阶段完整 API 基线为 365 passed、3 skipped，Ruff 与 diff check 通过。
- 未运行真实 PostgreSQL/pgvector。非阻塞后续项：补充恰好 120 字符成功、同空间 `Physics`/`physics` 共存测试；可进一步收窄 constraint-name substring fallback。
- Phase 5 / Milestone 3 仍为 `in_progress`；下一步是 Task 4：safe immutable uploads。

### Task 4 已确认上传、安全与并发边界

- 安全不可变上传 API 已覆盖 MIME/extension/signature/size 校验、分块 SHA-256 与 spool、文件名 NFC 规范化和控制字符拒绝、租户权限、exact idempotency/conflict、SHA 去重与版本递增。
- 成功路径创建 Document、DocumentVersion 与 queued ingestion job；请求边界使用 KnowledgeUploadRequest，生产 multipart 路径带锁，provider 错误保持脱敏。
- 文件 prepare 阶段不持有数据库锁；同步数据库访问、行锁、对象存储与 commit 全部进入同一 worker thread，保证 Session thread ownership，并在锁内做最终权限重检且 commit before response。
- PreparedUpload lease 接管 copied temporary file 的生命周期：客户端取消时 worker 可安全继续，原 UploadFile 与临时资源确定性关闭。

### Task 4 验证边界与保留风险

- `07ec443` 基线：upload focused 57 passed；相关 regression 308 passed；完整 API 425 passed、3 skipped；targeted Ruff 与 diff check 通过。
- 独立规格复审：61 focused passed。`53a253a` 后 Task 4 upload focused 60 passed（仅完整运行一次），targeted Ruff 与 diff check 通过。
- `72c0194` 后取消/线程定向 4 passed；增量规格复审另 2 passed；最终质量复审完成静态检查与 2,000 次内存竞争探针。两个并发修复后没有重跑完整 API suite。
- 未运行真实 PostgreSQL/pgvector/MinIO/Docker/OCR/external services。
- 保留风险：真实 PostgreSQL 行锁/constraint diagnostics 与真实 MinIO conditional-create 未验证；object write + DB commit 非分布式事务，可能留下 immutable orphan。
- 同 KB 慢 storage/锁等待可能消耗 AnyIO worker pool，后续需 timeout/limiter/queue；客户端取消后已接管 worker 可能后台完成，尚缺专门结果日志与可观测性；copied spool 落盘写仍可能造成短事件循环延迟。
- PreparedUpload lease duplicate claim 当前生产不可达但未显式拒绝；service caller-owned temp contract 后续应明确。DOCX 当前仅校验 ZIP magic，100 MiB 上限仅在 service layer，digest 尚无 domain prefix。
- Task 4 已完成，但 Phase 5 / Milestone 3 仍为 `in_progress`；下一步是 Task 5：native parsing and Obsidian import。

### Task 5 已确认解析、安全与验收边界

- 原生优先解析已覆盖确定性微型 PDF、DOCX、Markdown、PNG 与 Obsidian Vault ZIP；保留 PDF 页码与有序块、DOCX 段落/标题/表格顺序、Markdown 行范围与 frontmatter/tags/table、Vault 规范化路径、附件与 wikilink；低文本或乱码 PDF 页标记为 `needs_ocr`。
- DOCX/Vault ZIP 采用 fail-closed 预检与资源预算，覆盖 traversal、bomb、Zip64、多磁盘、路径深度/字节、条目/内容/行/块/tag/wikilink 等限制；PNG 执行有界 zlib/scanline 结构验证；解析错误保持稳定且脱敏。
- 已解决质量/安全复审唯一剩余 P1：经典 EOCD 的 `central_size` 在构造 `zipfile.ZipFile` 前受限；DOCX 固定、Vault 默认使用 16 MiB 中央目录预算，Vault 可注入但必须是严格正整数。真实 ZIP metadata 测试和 spy 证明超限时不会构造 `ZipFile`。
- 实现提交链：`2dc8ce1 feat: parse supported knowledge formats`、`30014ae fix: harden native knowledge parsers`、`5c70d87 fix: bound native parser resources`、`75997c7 fix: bound zip central directory`。最终独立规格复审 PASS；最终独立质量/安全复审 PASS。
- 验证：聚焦解析器 57 passed；目标 Ruff（`parsers.py` 与 `test_knowledge_parsers.py`，`--no-cache`）通过；`git diff --check` 通过；增量规格复审 7 passed；增量质量/安全复审 8 passed，并完成只读安全探针。未运行完整 API suite，也未使用 Docker、PostgreSQL、MinIO、OCR、外部服务或大型真实文档集成测试。
- 保留风险：`pypdf.extract_text` 没有子进程隔离或墙钟超时，单次调用仍可能瞬时消耗 CPU/内存；未做真实大文件集成；PNG 是有界结构验证而非完整一致性实现；XML 是字节模式 fail-closed 而非专用 hardened XML；YAML 在 `safe_load` 前只有 64 KiB 限制，节点/深度预算在 load 后执行。
- 继续保留：ZIP 当前未拒绝 symlink 之外的所有 Unix 特殊类型，但解析器不落盘解压；16 MiB 中央目录策略可能拒绝极端合法 ZIP，若 Vault 上层允许调高应仅限可信调用方；解析器输入仍先整体进入 `bytes`。
- Task 5 已完成，但“实现 PDF/DOCX/Markdown/图片/Vault 导入”阶段仍包含选择性 OCR 与原页证据等后续工作；Phase 5 / Milestone 3 保持 `in_progress`，下一步是 Task 6：selective OCR and page evidence。

### Task 6 已确认 OCR、页证据与生命周期边界

- OCR 只作用于 PNG 与 `needs_ocr=True` 的 PDF 页；PDFium 子进程按需渲染，Tesseract adapter 负责 OCR，默认 backend 保持 disabled。Dockerfile 在 non-root `USER` 前安装 English 与 Simplified Chinese Tesseract runtime 包。
- 页证据、checkpoint 与 result 为 immutable；保留页码、block 顺序和 source pointer，允许 partial failure，并对 provider 错误做稳定映射与脱敏。
- 资源边界同时覆盖 page pixel、language、单次 input/output/time，以及 document-level page/evidence/text/deadline 累计预算；subprocess stdout 有界。
- 子进程生命周期采用统一的 `Popen` 后清理边界；Windows 使用 suspended process + Job containment，Job 分配失败 fail-closed 且不再使用不安全 PID-tree fallback；POSIX 使用 process-group 静态路径。进程、pipe、I/O thread 与 Windows handle 均进行确定性清理。
- `d9f244d` 关闭首轮质量复审指出的 subprocess 输出/后代清理与文档累计资源预算问题；`5225691` 又关闭第二个 `Thread.start` 失败泄漏、Windows Job 失败 fallback、非 Tesseract adapter 突破 document deadline、stdin-only descendant deadline 错误映射四项 Important。
- 所有 adapter 使用 `timeout_seconds/remaining` 合同；legacy adapter 在进入 adapter body 前 fail-closed；stdin-only descendant deadline 映射为 `TIMEOUT`。
- 验证：`d9f244d` 后 OCR 44 passed、adapter OCR 10 passed、parser 57 passed；最终 `5225691` 后 OCR 49 passed、adapter OCR 10 passed、parser 57 passed，targeted Ruff 与 `git diff --check d9f244d..5225691` PASS。最终独立规格复审 PASS（11 focused passed），最终独立质量/安全复审 PASS（7 focused passed）；10 次真实 BrokenPipe 均为 `PROCESSING_FAILED`，Windows Job handle 精确关闭 1 次，预热后成功 3×20 与 timeout 3×10 调用 handle 稳定且 OCR I/O threads 归零。
- 未运行完整 API suite、真实 Tesseract/container smoke、Docker、PostgreSQL、MinIO、外部服务、POSIX 实机 process-group 路径或复杂 PDFium corpus。
- 非阻塞残余风险：主动 `setsid`/改组的 POSIX descendant 可逃离；PDFium child 无 OS 级地址空间上限；每个 PDF OCR 页仍 spawn 并复制完整 PDF bytes，且输入整体以 `bytes` 进入；安全预算可能拒绝极端合法页面；executable 必须是可信配置。
- deadline-aware adapter 是受信任 port 合同，声明支持却忽略 timeout 的 adapter 无法由当前调用方强制终止；Windows Job Assign 依赖 CPython `Popen._handle` 私有属性，需随 Python 版本复核。强制 SIGKILL 位于第一次 bounded join 后，理论上 daemon I/O thread 可能极短暂存活，但无持久或线性泄漏证据。
- Task 6 final PASS 不代表整个导入阶段或里程碑完成；Phase 5 / Milestone 3 保持 `in_progress`，下一步为 Task 7：immutable indexing and reliable worker。

### Task 7 已确认不可变索引与可靠 worker 边界

- build target 不可变并绑定 embedding backend/model/dimension/signature 合同；heading-aware chunking 有严格大小/重叠边界，相同内容 hash 可精确复用。
- building index 持久化 source page/block pointer、lexical terms、vector、model/dimension/signature 与 hashes；成功前旧 active index 保持不变，校验与激活原子完成。
- ingestion job 使用 lease、PostgreSQL `FOR UPDATE SKIP LOCKED`、stale recovery、bounded retry 与 restart-safe idempotency；Compose worker 复用 API 镜像。
- S3 路径限制 redirect 与对象大小，非本地 production storage 必须 HTTPS；parse terminal state 与 started/completed timestamps 完整落库。
- OCR 保持 fail-closed；`363f3fb` 仅允许 completed OCR page 为空且整份文档仍保留内容的情况，避免空白页错误终止有效文档。
- READY snapshot 采用 knowledge-base lock ordering 串行化；adapter contract drift 会 terminalize 旧的未激活 target，并幂等创建或复用绑定当前合同的 replacement job。
- 交付提交顺序：`f298eb2 feat: build knowledge indexes reliably`、`96a3ad6 fix: close reliable indexing gaps`、`53284ca fix: harden reliable indexing delivery`、`cfc6220 fix: serialize ready index snapshots`、`0d34b2a fix: requeue changed embedding contracts`、`363f3fb fix(api): allow blank OCR pages`。
- `0d34b2a` 时独立规格复审已 PASS。初始质量复审 FAIL 的两项中，production-HTTP 为只读误报，因 `config.py` 已要求 nonlocal production storage 使用 HTTPS；blank OCR page 为有效问题并在 `363f3fb` 修复。修复后独立规格复审 PASS（34 focused），独立质量复审 PASS。
- 最终验证：Task 7 相关八个测试文件组合 362 passed、36 warnings；migration nodes 3 passed、4 warnings；targeted Ruff all checks passed；`git diff --check aa71123..HEAD` PASS。
- 非阻塞残余：长 external handler 执行期间仍持有 transaction/job lock；bounded S3 PUT 会最多缓冲到配置的最大对象大小。历史 Windows OCR combined run 曾有两个 1 秒 PID-file timing failure，但精确两项与完整 OCR 文件分别通过，最终 362 项 combined focused run 通过，质量复审判定为非阻塞 timing observation。
- 未运行 Task 7 变更后的完整 API suite、Docker、真实 PostgreSQL/pgvector、MinIO/S3、Redis、Tesseract/PDFium corpus、外部服务或 POSIX 实机 process group。
- Task 7 final PASS 不代表 Milestone 3 / Phase 5 完成；状态继续为 `in_progress`，下一步是 Task 8，且本次未开始 Task 8。

### Task 8 已确认检索与安全预览边界

- Task 8 最终代码提交：`e219bdf feat: add cited knowledge retrieval`、`11f1aa4 fix: persist cited page previews`、`13c9d15 fix: preserve reliable retrieval recall`。
- 搜索仅面向授权知识库的 ACTIVE immutable index；lexical/vector 候选经确定性 RRF 融合，query/result/excerpt/candidate 均有界。
- embedding adapter 与 ACTIVE index 的 backend/model/dimension/contract signature 必须完全一致才启用 vector recall；不一致时确定性降级为 lexical-only，避免混用不兼容向量。
- 候选选择遍历完整 ACTIVE index，同时以有界 top-1000 heap 保留 lexical/vector 候选，修复了先截断前 1000 行导致的确定性漏召回。
- 正常上传→解析流程持久化不可变、有界的页面预览对象；opaque citation 校验、租户授权、ACTIVE-index membership 与文档状态检查均先于对象读取，Range 和 provider 错误保持有界、脱敏。
- 最终独立规格复审 PASS；最终独立质量/安全复审 PASS。最终修复后 retrieval/source/indexing 聚焦组合 31 passed，targeted Ruff 与 `git diff --check` PASS。
- 非阻塞风险：完整索引扫描内存有界，但 CPU/数据库行工作随 ACTIVE index 线性增长；生产规模 benchmark 与数据库原生 top-k 留待后续优化。
- Phase 5 / Milestone 3 仍为 `in_progress`；下一步为 Task 9「C3 knowledge panel」。

## 2026-08-18 · Task 9 C3 knowledge workspace

- **Status:** Task 9 final SPEC PASS and QUALITY PASS; Phase 5 / Milestone 3 remains `in_progress`.
- **Code commits:** `7a03e5c feat: connect knowledge workspace`, `27fa8f5 fix: correct knowledge workspace states`, `3f81af4 fix: cancel stale knowledge workspace requests`.
- **Delivered:** space-scoped KB panel and switching; bounded KB creation and uploads; learner-facing processing/failed/searchable states; explicit `知识库 → 教材/练习 → 文件` hierarchy; search and opaque cited-page preview; generic error messages and independent model/balance/knowledge retries.
- **Reliability:** stale create/upload/search/preview work is cancelled and sequence-guarded; uploads are single-active per panel, retry with their original idempotency key, and cannot clear a later selected file.
- **Verification:** focused Web 7 files / 34 tests PASS; lint PASS; production build PASS; final independent specification PASS and quality/security PASS.
- **Residual risks:** no document-status/list endpoint exists for client polling, so accepted ingestion state is the upload-response snapshot; add deeper stale-completion and object-URL cleanup regression tests later. Task 10 remains the real PostgreSQL/pgvector and Compose vertical-slice gate.
## 2026-08-18 · Task 10 verification record

- **Status:** Task 10 is incomplete and environment-blocked; Milestone 3 / Phase 5 remains `in_progress`.
- **Feasible verification:** Web full test (7 files / 34 tests), lint, and production build passed. API Ruff passed with `--no-cache`; the full coverage run ended at 590 passed, 3 skipped, 2 failed, with 88.08% coverage against the 90% gate. The two failures were Windows OCR descendant-timeout PID-file assertions; no product source was changed during this documentation-only pass.
- **Format evidence:** deterministic in-memory PDF, DOCX, Markdown, JPEG, PNG and Obsidian ZIP parser inputs exist, and upload tests cover each accepted suffix including `.jpg` and `.jpeg`; no binary fixtures are tracked.
- **Blocked gates:** Docker CLI/Desktop and local PostgreSQL tools were absent, so no isolated PostgreSQL/pgvector migration round-trip or Compose register → KB → Markdown/PDF upload → READY → search → cited-page slice was run.
- **Limits/provider posture:** 100 MiB knowledge upload, 5,000 Vault members, 500 MiB uncompressed Vault data, disabled-only OCR, and deterministic `hash / feature-hash-v1 / 384` embeddings. No remote OCR or embedding provider is configured, and there are no real model-invocation credentials or enabled remote model calls; DeepTutor remains research-only.
- **Next:** obtain a usable container/pgvector runtime and resolve the full API coverage/test gate before final Task 10 delivery. See `docs/superpowers/handoffs/2026-08-18-task10-verification-blocked.md`.

## 2026-08-21 · MVP 主链路收口实现批次

- **Status:** in_progress
- **范围：** 诚实移除未实现的 AI Tutor/模型/余额/费用界面；接入最小题库学习者 UI；新增仅含公开处理状态的资料状态读取并在知识库面板提供刷新。
- **约束：** 仅 feature worktree；不启动 Docker/Compose/Alembic、全量测试、coverage、真实外部 API/LLM；不 stage/commit/reset/stash/checkout；API 测试仅使用 `apps/api/.venv/Scripts/python.exe -B` 及 `PYTHONDONTWRITEBYTECODE=1`。
- **验证计划：** 新增/紧邻 API 上传测试、三项工作台 focused Vitest、targeted Ruff/ESLint/tsc；完成后再一次性进行 SPEC 与 QUALITY/SECURITY 审查。

## 2026-08-21 · Obsidian 风格工作台接入

- **Status:** implementation complete; focused Web verification passed; production build remains environment-blocked by `.next/trace-build` permission denial.
- **范围：** 将 `.superpowers/brainstorm/platform-design/content/workspace-c3-space-navigation.html` 的视觉骨架迁移到 Next.js `WorkspaceShell`，保留现有知识库和题库面板，不恢复未实现的 AI Tutor/模型/费用承诺。
- **验证：** Web 8 files / 35 tests passed；ESLint passed；TypeScript non-incremental check passed。
- **待处理：** 需要在可写的 Next.js 构建目录中重新执行 production build；本次未改动 API、未执行 Docker/Alembic/full API suite。

## 2026-08-21 · 登录入口视觉收口

- **Status:** complete; browser preview confirmed styled login page; Web tests pass.
- **范围：** 为匿名登录/注册入口补齐与工作台一致的深色卡片视觉，保留原有登录/注册语义和接口行为。
- **验证：** Web 8 files / 35 tests passed；ESLint and TypeScript passed。浏览器预览确认 CSS 已生效。

## 2026-08-21 · 注册链路故障修复

- **Status:** complete.
- **根因：** FastAPI 未运行；同时 Web API client 忽略了 `NEXT_PUBLIC_API_BASE_URL`，相对路径错误地请求到 3000 端口。
- **修复/验证：** API client 改为读取配置 origin；FastAPI 8000 健康检查 200；Web 8 files / 36 tests、ESLint、TypeScript 均通过。

## 2026-08-21 · 旧 Worker 更新

- **Status:** complete; the stale Compose Worker was rebuilt and recreated from the current worktree.
- **目标：** 更新 `mvp-phase6-20260821-worker-1`，不删除数据库、Redis 或对象存储数据卷。
- **验证：** current API image rebuilt; Worker container recreated and started successfully; container exit code is 0 and recent logs contain no error output。

## 2026-08-21 · 注册失败第二次修复

- **Status:** complete; rebuilt the stale Web image with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8010` and recreated only the Web container.
- **根因：** API 日志没有任何注册请求；Web 容器仍是旧镜像，未加载当前 Compose 环境中的 API 端口。
- **验证：** Web build passed; `/register` returns 200; Web container is running and healthy。

## 2026-08-22 · 注册链路永久修复

- **Status:** complete; browser API calls are now same-origin and proxied by Web at runtime.
- **根因：** `NEXT_PUBLIC_API_BASE_URL` 被编译进浏览器包；API 端口变化或 Web 镜像未重建时，注册请求会静默发往旧地址，API 完全收不到请求。
- **修复：** 新增动态 `/api/[...path]` 代理；浏览器只请求 Web 同源地址；Compose 通过运行时 `API_INTERNAL_URL=http://api:${API_PORT}` 连接 API。
- **验证：** Web 9 files / 37 tests、ESLint、TypeScript、production build 均通过；Compose 全栈重建后，真实注册 201，随后 `/auth/me` 200。

## 2026-08-22 · 注册 422 提示修复

- **Status:** complete; the reported request reached API and failed validation because the password was shorter than 12 characters.
- **修复：** 注册页常驻展示“至少 12 位”，短密码提交时明确提示“密码至少需要 12 位”，且不发送无效请求。
- **验证：** TDD regression passed; Web 9 files / 38 tests、ESLint、TypeScript and Docker production build passed；Web container recreated。

## 2026-08-22 · 工作台功能面板样式恢复与对接核查

- **Status:** complete; Web verification and local browser smoke passed.
- **根因：** Obsidian 工作台视觉迁移替换了共享 CSS Module，却遗漏 `KnowledgePanel` / `QuestionBankPanel` 仍引用的 19 个样式类；功能 DOM 与 API 调用存在，但退化为原生文字和控件。
- **修复：** 补回知识库、上传、搜索、预览、题库、答题和复习状态的完整样式，并增加 CSS Module 合同回归测试。
- **联调：** 本地登录后已验证创建知识库、空库搜索、题库切换与空状态。外壳上的创建班级、全局/空间搜索、更多、空间设置和展开按钮仍为原型占位；后端题目创建端点尚无前端出题入口，记录为后续功能缺口。
- **最终验证：** Web 10 files / 39 tests、ESLint、TypeScript、Docker production build 均通过；Web/API/PostgreSQL/Redis 健康，Worker 与 MinIO 正常运行。

## 2026-08-22 · 浅色工作台排版优化

- **Status:** complete; focused visual and full Web verification passed.
- **范围：** 保留三栏和现有功能流，将工作台调整为暖白、浅灰、柔紫与薄荷绿；移除 emoji、字符图标、简单装饰图形及无功能原型按钮。
- **响应式：** 移除固定工作区最小宽度；1023px 以下收起右侧说明，767px 以下再收起内容树，中心区优先展示表单和学习内容。
- **回归：** 新增纯文字导航/原型控件清理测试与浅色 CSS token/响应式合同测试。
- **最终验证：** Web 10 files / 41 tests、ESLint、TypeScript 和 Docker production build 通过；341px 浏览器无页面级横向溢出，内容树/说明栏折叠且知识库/题库切换正常；Web、API、PostgreSQL、Redis healthy。

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

<!-- ACTIVE-AI-TUTOR-RECOVERY:START -->
## Completed Recovery Task — 2026-08-30：AI 助教恢复 Faro / Gemini

### Objective

保留现有 `AgentPanel → /api/v1/agent → Agent Runtime` 架构，将唯一活跃聊天供应商从 Claude 切换为 Faro OpenAI-compatible 中转站的 `gemini-3.7-flash-tiered`；主界面只保留聊天，“会话记录 / 服务设置”收纳到统一风格的设置浮层。

### Work Items

- [x] 定位根因：Agent Runtime 原来只注册 Claude，Faro 配置虽存在却未进入 Agent 聊天链路；API/数据库旧 provider 设置还可能继续覆盖为 Claude。
- [x] 新增 Faro Runtime provider 并将 Runtime 注册表切为 Faro；API/Compose 默认切为 `faro / gemini-3.7-flash-tiered / 32000`。
- [x] Web：完成聊天主视图 + 设置浮层二级页签，服务页固定只读 Faro/Gemini，并更新交互测试。
- [x] Runtime：补 Faro provider 单测、代理/超时/错误处理和 session history/fork 行为，完成 test/typecheck/build。
- [x] API：只接受并应用 provider=faro 的固定设置，拒绝错误 provider/model/context，补齐聚焦测试和旧 Claude 会话退休保护。
- [x] 定向修正本机 `.env` 中非敏感 AGENT_PROVIDER / AGENT_MODEL / AGENT_CONTEXT_WINDOW 值，未读取或输出密钥。
- [x] 重启 Agent Runtime 与 API/Web/Worker，验证 diagnostics 仅有 provider=faro，并通过 Agent API 完成两次真实最小对话。
- [x] 完成 Web test/lint/build、Runtime test/typecheck/build、API 聚焦 pytest，并记录验证结果。

### Constraints Preserved

- 未输出 `.env` 全文、API Key、Runtime Token 或 Capability Secret。
- 未执行 `git reset`、`git clean`、Docker 卷删除或提交操作。
- 未恢复已退休 Tutor 写接口；活跃 AI 助教继续走 Agent API，唯一 Provider 为 Faro。
- UI 保持现有暖白/浅紫、细边框、圆角、轻阴影；AI 助教区域不再常驻设置卡片。

### Final Status

- 工作区：`E:\项目\知识库课本\.worktrees\platform-foundation`
- 分支：`feature/platform-foundation-wip`
- Host Runtime：PID `35704`，`/v1/diagnostics` 为 `ok`，仅注册 `faro`，详情为 `Faro · gemini-3.7-flash-tiered`。
- Docker：API/Web/PostgreSQL/Redis 健康，Worker 与 MinIO 正常运行；API `/api/v1/health` 返回 `ok`，Web `http://127.0.0.1:3100` 返回 `200`。
- 真实 Faro 验收：两次均通过；事件包含 `turn_started`、`user_message`、`model_text_delta`、`session_state`，最新模型文本非空。
- 测试：API `119 passed`；Web `35 files / 232 tests passed`、ESLint 与 production build 通过；Runtime `25 suites / 86 tests passed`、typecheck 与 build 通过。
<!-- ACTIVE-AI-TUTOR-RECOVERY:END -->

## 2026-08-30 · 最终稳定性收尾（当前执行）

### 目标

在不回归 Faro/Gemini AI 助教、知识库检索上下文、知识候选生成、UUID 标签隐藏和消息正文隔离的前提下，完成以下最终缺陷：

- [x] 上传后“当前任务”处理状态与数据库权威 workspace 状态自动同步，手动刷新不受缓存影响。
- [x] 真实 PDF 处理失败的 DataError/invalid_format 根因修复或明确、安全地呈现终态。
- [x] AI 助教会话记录可实际切回历史聊天；四个会话操作不再是无效控件。
- [x] 服务设置 Capabilities 四项可操作且有明确持久化语义，不改变固定 Faro/Gemini 供应商约束。
- [x] 知识库提供安全删除入口，包含权限、活动任务、关系数据和对象存储处理边界。
- [x] 完成知识候选生成与 AI 助教连接的真实回归，并运行 Web/API/Runtime 自动化验证。

### 执行策略

1. 先为每个可复现缺陷补回归测试，再做最小修复。
2. Web AI 助教、API PDF Worker、数据库删除审计分开并行，避免写集冲突。
3. 每批修改后先跑聚焦测试，最后集中跑全量 Web、API 聚焦/全量可行集、Runtime 全量与真实浏览器验收。
4. 不切换 Claude，不暴露密钥，不删除用户数据做试验，不使用强推。

### 状态

- **Status:** in_progress

## 2026-08-30 · 最终交付验收

- [x] Runtime stop/rewind/fork mutation 合同与 204 空响应处理完成；用户确认分叉非必需，不再继续扩展。
- [x] 知识库刷新、候选生成、Faro/Gemini AI 助教、会话切换/归档/停止、Capabilities 与删除功能完成回归。
- [x] 隔离用户真实 Vault 删除 E2E：删除接口 204、Worker 首次轮询即清理目录、详情接口 404。
- [x] Web、API、Agent Runtime 自动化测试及构建通过，Compose 服务健康，迁移位于 0018 head。
- [x] 完成最终差异审查，并提交推送到 github-collab/feature/platform-foundation-wip。

- **Status:** complete
## 2026-08-30 · 发布前质量门禁豁免与分支核对

- 按用户要求，本次发布不以 Quality workflow 全绿为前提；失败项仅作为后续质量改进记录，不阻断当前功能发布。已知 API 失败为覆盖率 89.74% 未达到 90% 门槛；本轮没有因该门禁修改产品代码。
- 远程 `github-collab/feature/platform-foundation-wip` 与本地稳定提交一致，均为 `f2a0acf37b0aee07f53ec91cd7408b967f03e1fa`。
- 仇勇旺（qyw211）远程 `feature/aiopc-upgrades` 的提交 `c53f459` 未被当前稳定分支包含，本次明确不合并；远程 `feature/add-AIOPC` 的 `117fe2b` 仅为既有 `progress.md` 验证记录，已在稳定分支历史中，不含其后续导师/支付/题库大改动。
- 远程 `main` 当前为 `3347c6f`，是稳定分支 HEAD 的祖先；发布目标可采用非强制 fast-forward 到 `f2a0acf`。
