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
- [ ] 整个 Milestone 3 / Phase 5 尚未完成，状态保持 `in_progress`。
- [ ] 下一步：Task 7「immutable indexing and reliable worker」。

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
