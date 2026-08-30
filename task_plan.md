# 课本知识库 Agent 平台任务计划

## Goal

设计并实现一个支持多用户、个人与班级知识空间、教材自动知识化、可追溯答疑、长期学习记忆和按量计费的 AI 学习平台；先在本机验证，成功后迁移至 Linux 云服务器。

## Current Phase

MVP 收口（Phase 5 基础能力冻结）→ Phase 6 客户验收准备

- **当前目标：** 不再以完成原 Phase 5 的全部高级能力为前提；优先完成“可追溯知识库 + 题库学习闭环”的最小客户验收。
- **实施方式：** 将真实资料链路 Gate、学习闭环 UI/API 可见化、验收证据作为一个合并批次；批次后仅做一次集中验证、一次 SPEC 审查和一次 QUALITY/SECURITY 审查。
- **高级功能状态：** 知识图谱/自生长笔记、L0-L3 记忆、多 Agent、真实 LLM Tutor、生成式题目、教师分析、性能压测和非关键 coverage 全部延期至客户验收/下一笔资金后。
- **诚信约束：** 2026 年 8 月 19 日 Task 10 的真实 Docker 导入检索失败仍是未通过事实；在新的隔离验收成功前，禁止声称 PostgreSQL/pgvector 导入、检索、citation 原页真实链路已经通过。
- **权威详细计划：** `.worktrees/platform-foundation/docs/superpowers/plans/2026-08-21-mvp-closeout-phase6-acceptance-plan.md`
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

### Phase 5：MVP 基础能力收口（原高级范围已延期）

- [x] 已有多租户身份、空间/班级权限、供应商目录、钱包及基础工作台。
- [x] 已有知识库与题库学习的实现基础：知识库创建/上传/搜索/引用端点，以及题目、作答、确定性评估、复习队列、答题历史端点。
- [x] 完成一个合并 MVP 批次：题库学习前端/处理状态可见化、移除误导性 AI 家教展示承诺；真实资料链路 Gate 与客户演示证据转入 Phase 6。
- [x] 批次后完成复审闭环：focused verification、SPEC、QUALITY/SECURITY 及索引校验窄修复复审均已完成。
- **Status:** redirected_to_mvp_closeout
### Phase 6：MVP 集中验收与客户交付

- [x] 在新鲜隔离环境完成一次最小真实资料导入 → 处理 → 检索 → citation/source/page preview 端到端证据；历史失败与修复后 PASS 均已记录。
- [x] 完成知识库资料链路证据、题库答题/复习 API/UI focused 证据，并复核权限与私密字段边界。
- [x] 形成客户验收包：范围说明、演示步骤、已知限制、延期高级功能和资金到位后的扩展清单。
- **Status:** complete — MVP ready for customer acceptance; advanced features deferred
## Key Questions

1. 【延期到高级阶段】真实 LLM Tutor 的供应商、模型、调用协议、密钥注入和计费验收待客户回款后确认。
2. 用户结算人民币时采用什么汇率来源、更新周期和精度规则？
3. 【已解决/MVP Gate】2026 年 8 月 19 日及修复前的新资料索引失败已被记录；2026 年 8 月 21 日 float4 窄修复后的隔离实证已通过资料检索与来源预览。
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
| 供应商密钥与地址仅留在服务端环境 | 浏览器和数据库不保存明文密钥；用户只读取安全模型目录 |
| 金额、价格和汇率采用 Decimal/NUMERIC 快照 | 账务可审计，避免浮点误差与未来价格变动影响历史扣费 |
| 钱包先预留、后结算且账本只追加 | 防止并发透支和重复扣费；充值冲正以新账本记录表示 |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| 初次项目扫描因空目录和非 Git 仓库返回失败 | 1 | 改为普通目录检查，确认工作区仅有设计草图 |
| 可视化服务在 Windows 默认写入受限目录 | 1 | 将会话目录设置到项目内 `.superpowers/brainstorm/` |
| 可视化服务被回收 | 1 | 重新启动并恢复已保存的页面 |
| Computer Use 读取 Obsidian 窗口遭遇 EPERM | 2 | 停止重复尝试，改用用户截图和既有 Obsidian 交互规律 |
| C3 原型首次补丁无法匹配压缩 CSS 行 | 1 | 按实际行内容拆分成更小补丁后完成更新 |
| Windows 权限上下文锁定 `.next`、Ruff/Pytest 缓存 | 2 | 仅处理可再生构建缓存；Ruff 禁用缓存，覆盖率写入系统临时目录，构建用正常系统权限复验 |
| Alembic 版本标识超过 PostgreSQL 默认长度 | 1 | 保留历史标识，迁移前安全扩展版本列表；并兼容短期旧标识数据库 |

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

- [x] Task 7「immutable indexing and reliable worker」最终 PASS；代码交付提交：`f298eb2`、`96a3ad6`、`53284ca`、`cfc6220`、`0d34b2a`、`363f3fb`；功能工作树文档提交：`8f22c2d`。
- [x] Task 7 最终独立规格复审 PASS，最终独立质量/安全复审 PASS；最终有限验证：知识相关组合 362 passed、迁移节点 3 passed、目标 Ruff 与 `git diff --check aa71123..HEAD` 通过。
- [x] Task 7 已实现 immutable contract-bound index、原子激活与旧 active 保留、数据库 lease/`FOR UPDATE SKIP LOCKED`、stale/retry/restart 去重、Compose worker、production HTTPS 对象存储门禁、READY snapshot 锁顺序与 embedding-contract drift replacement job。
- [x] OCR 的 blank completed page 仅在文档仍有可索引内容时接受；failed/unresolved/all-empty OCR 仍 fail-closed。初始质量复审的 production-HTTP 项经配置启动门禁核验后证伪，blank-page 项已由 `363f3fb` 修复。
- [ ] 下一步：Task 8「hybrid retrieval and secure source preview」。不得将 Task 7 完成误记为 Milestone 3 或 Phase 5 完成。
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

### 2026-08-18 · Phase 5 / Task 10 verification（环境阻塞，已复审）

- **状态：**Task 10 未完成；Milestone 3 与 Phase 5 继续为 `in_progress`。这不是最终交付，也未创建 `docs: record versioned knowledge delivery`。
- **已通过：**`pnpm test:web`（7 files / 34 tests）、`pnpm lint:web`、`pnpm build:web`；API `ruff check --no-cache src tests`；focused OCR 49 tests；`alembic heads` 仅确认 `0008_embedding_contract (head)`。
- **未通过：**完整 API coverage（覆盖率文件定向至 `%TEMP%`、禁用 pytest cache）为 590 passed、3 skipped、2 failed，覆盖率 88.08%，低于 90% gate；失败为两个 Windows OCR descendant-timeout PID-file assertions。focused OCR 与 graph head 不替代该 gate 或真实 migration。
- **未运行：**2026-08-18 无 Docker CLI/Desktop、`psql`、`pg_isready` 或 `initdb`，因此没有真实 PostgreSQL/pgvector migration upgrade/downgrade round-trip，也没有 Compose register → KB → Markdown/PDF → READY → search → cited-page vertical slice。
- **复审：**Task 10 阻塞记录经修复后独立 SPEC PASS 与 QUALITY/SECURITY PASS；修复仅澄清七文件记录范围、示例 provider 语义及 handoff 末尾 LF。
- **下一步：**提供可用 Docker/Compose 或隔离 PostgreSQL/pgvector 环境，稳定完整 coverage 到至少 90%，然后重跑两个 live gates；完成前不得标记 Task 10、Milestone 3 或 Phase 5 complete。
### 2026-08-18 · Milestone 4 新任务：设计与计划准备

- **状态：**已从 Task 10 的已复审阻塞记录转入 Milestone 4 的设计恢复与详细计划准备；此切换不改变 Task 10、Milestone 3 或 Phase 5 的未完成状态。
- **已知起点：**现有系统可复用模型目录、钱包预留/结算服务、空间权限和知识检索/不透明引用预览；尚无真实 LLM invocation、Tutor/Agent API、会话、题库/错题或 L0–L3 记忆的数据与服务边界。
- **计划约束：**在实现前先以正式设计和已落地代码写出 Milestone 4 的详细计划，并单独锁定真实 provider/model、可核验 usage、教学模式、记忆控制和题库/错题的个人/班级权限语义。不得以确定性测试 adapter 代替生产模型接入声明。
- **根目录保护：**本记录为增量追加，继续保持未提交；feature worktree 的 Task 10 文档提交和原有根目录记录均不回退。
### 2026-08-18 · Milestone 4 设计准备状态

- Task 10 的 90% API 覆盖率、真实 PostgreSQL/pgvector 迁移往返与 Compose 垂直验收仍被阻塞；不得将其与 Milestone 4 的设计准备混同，也不得将 Phase 5 标记完成。
- 已完成独立只读规格复核：现有模型目录、价格/汇率版本、钱包预留/结算/释放、空间检索、受权来源回看和 C3 Tutor 视觉壳可复用；尚不存在真实 LLM 调用适配器、Tutor 编排/端点、学习领域持久化实体、回答级引用、题库/错题和 L0–L3 记忆闭环。
- **当前设计门禁：**用户必须先确认首个可启用 Tutor 的具体供应商与模型，以及该调用是否可由服务端核验真实 usage 并允许生产计费。未确认前不得输出可批准的 Milestone 4 实施设计或开始实现。
- 下一步：按 brainstorming 一次只确认一个产品决策；确认后比较实现路径、提交设计供用户审核，再编写详细实施计划。
### 2026-08-18 · Task 10 environment resumption update

- [x] Docker Desktop/Engine (`29.7.2`) and Docker Compose (`v5.3.1`) were directly verified. The required CLI is `C:\Users\asus\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`; local `psql`/`pg_isready`/`initdb` are not required because the isolated Compose route supplies runtime services.
- [x] The reviewed operational handoff is now an isolated feature-worktree commit: `5a242dc docs: prepare Task 10 environment handoff`. A fresh documentation fix, independent SPEC PASS, and independent QUALITY/SECURITY PASS made its recovery rule valid after commit; feature worktree is clean at that commit.
- [ ] Task 10 remains incomplete: no `.env`, containers, volumes, live migration round-trip, or Compose vertical slice were created or run in this session. Before live validation, obtain explicit permission to create a Git-ignored local `.env`, pull/start a uniquely named disposable Compose project, perform the isolated downgrade/upgrade, save redacted evidence, and destroy only that project-owned stack after evidence collection.
- [ ] The complete API coverage gate remains separate at 88.08% versus the mandatory 90%; investigate and fix the two Windows OCR descendant-timeout failures without weakening the tests or threshold.
- [ ] Do not begin real billable Tutor provider work until Milestone 4 provider/model, server-verifiable usage response, streaming protocol, and initial price/FX snapshot owner are approved.

## 2026-08-19 · Task 10 覆盖率恢复（进行中）

- [x] Docker Desktop 已直接验证可用：绝对 CLI 路径为 `C:\Users\asus\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`，Engine client/server 为 `29.7.2`，Compose 为 `v5.3.1`；真实 Docker gate 仍须先获得隔离项目创建/销毁的明确授权。
- [x] Task 10 环境交接文档已在 feature worktree 的专用提交 `5a242dc docs: prepare Task 10 environment handoff` 中完成独立规格与质量/安全复审。
- [x] OCR coverage-only Windows 回归已修复并完成聚焦验证；生产改动当前未提交于 `apps/api/src/tutor_api/knowledge/ocr.py`，其 POSIX deadline 保持 Popen 前计时、Windows deadline 保持 secure startup 后计时，并剥离外部 OCR child 的 coverage auto-activation 环境变量。
- [x] 一次受控的官方完整 API coverage gate：`592 passed, 3 skipped`，功能零失败；总 coverage `88.13%`，仍低于强制阈值 `90%`，因此 Task 10 / Milestone 3 / Phase 5 均不得标记完成。
- [ ] 四个互斥的新鲜独立测试子任务已于 2026-08-19 重新派发：adapters（存储 range/HTTP fail-closed）、worker（对象完整性/checkpoint/lease）、ocr（deadline/env 回归）、retrieval（embedding/preview fail-closed）。每组须先独立 SPEC 复审 PASS，随后独立 QUALITY/SECURITY 复审 PASS；任何失败均由新鲜修复代理处理并重启复审链。
- [ ] 仅在四组测试复审均通过后，再运行一次完整 API coverage gate；不得通过降低阈值、skip/xfail、削弱 cleanup/timeout 断言或 `pragma: no cover` 达标。
- [ ] 仍待真实 Task 10 gate：隔离 pgvector migration `head → downgrade 0005_reversal_audit_group → upgrade head`，以及隔离 Compose Markdown+PDF 上传、READY、检索、真实 cited PDF `/page` vertical slice。

### 2026-08-19 · OCR coverage 补强验收

- [x] `apps/api/tests/test_knowledge_ocr.py` 的 OCR child 环境、POSIX/Windows deadline、Job Object assignment/resume fail-closed/cleanup 回归测试已补强；仅该测试文件新增测试，生产 `ocr.py` 改动保持为既有未提交改动。
- [x] 窄验证：`python -m pytest tests/test_knowledge_ocr.py` 为 `52 passed, 1 skipped`（唯一警告为既有 `.pytest_cache` 写权限）；`ruff check --no-cache` 与 `git diff --check` 均通过。
- [x] 最终新鲜独立规格复审：`SPEC PASS`；最终新鲜独立质量/安全复审：`QUALITY/SECURITY PASS`。中间审查发现的私有函数耦合、Windows cleanup 竞态、assignment handle close 覆盖和测试收集期全局 `subprocess` 污染均已用新鲜修复代理处理，并在最终双阶段复审前重新验证。
- [ ] 下一组：`test_knowledge_adapters.py` 的对象存储 range/Content-Range fail-closed 测试；完成后同样要求新鲜 SPEC → QUALITY/SECURITY。

## Session: 2026-08-19 · Task 10 S3 adapter coverage group accepted

- [x] storage.py / `test_knowledge_adapters.py 的 S3 range fail-closed 覆盖组已完成独立 SPEC PASS → QUALITY/SECURITY PASS 链。
- [x] 已覆盖真实 urllib 206 + Content-Range 成功路径，以及 200、无 Content-Range、start=0、精确 Content-Length 的成功回退；200/206 状态—header 组合、畸形/不匹配/截断/超长正文、整数解析、响应关闭和 server thread 有界清理均受测。
- [x] range 响应读取的超长正文仅在 get_object_range() 两个读取分支归一化为 ObjectRangeNotSatisfiableError，未改变通用 object-size 限制。
- 验证：adapter 目标集 109 passed，目标 Ruff 与 feature diff check PASS；未运行全量 coverage、迁移或 Docker 验收。
- 下一步：继续单文件的 worker/retrieval coverage 组，所有组各自复审通过后才运行一次 full API coverage gate。
## Session: 2026-08-19 · Task 10 worker coverage group accepted

- [x] `test_knowledge_worker.py 的 immutable processing / lease 防陈旧写入覆盖组完成独立 SPEC PASS → QUALITY/SECURITY PASS 链。
- [x] 覆盖对象 SHA-256/content-type 与 immutable version 元数据不一致、被篡改 BUILD_INDEX checkpoint、终态 parse failure 隔离，以及替代 worker 接管后陈旧成功/失败收尾均不可覆盖接管者。
- [x] lease 竞争测试使用显式 file SQLite NullPool 和公共 claim_next_job() 建立独立已提交接管；先前 StaticPool 共享事务的假阳性已修正，未发现需提交的 worker.py 生产缺陷。
- 验证：worker 目标集 22 passed，targeted Ruff 与 feature diff check PASS；未运行 full coverage、迁移或 Docker。
- 下一步：继续 retrieval 覆盖组；全部 coverage 组复审通过后才运行一次官方 full API coverage gate。
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

### Task 10 coverage exception (2026-08-19)

- [x] Completed high-value indexing coverage group with independent SPEC PASS and QUALITY/SECURITY PASS.
- [x] Re-ran the official full API coverage gate: 664 passed, 4 skipped, 40 warnings; total coverage 89.41%.
- [x] User approved treating the remaining 0.59 percentage-point gap to the former 90% coverage gate as an explicit exception; no further low-value coverage expansion is planned.
- [ ] Next: perform isolated pgvector migration round-trip and Docker Compose vertical slice after explicit create/destroy authorization.
## Task 10 final status (2026-08-19)

- [x] 0005 → 0008 migration downgrade/upgrade round-trip 已验证，当前为 `0008_embedding_contract (head)`。
- [x] pgvector float4 兼容修复完成：允许 SQLite exact storage 或 PostgreSQL float32 canonical round-trip；拒绝真实跨 binade 2-ULP 值。
- [x] focused indexing 测试 `35 passed`，targeted Ruff 与 `git diff --check` 通过；独立 SPEC 复审 PASS。
- [ ] Docker vertical slice 未通过：重建 API/worker 镜像后，Markdown/PDF 资料在 150 秒内仍未进入可检索状态，搜索结果为 0；最近 `index_versions` 记录为 `failed`。
- **Status:** Task 10 blocked/abandoned at the user's stop line. 不再继续反复改良或重复垂直验收。Phase 5 保持 `in_progress`，不得把本 Task 标记为完成。

## New-window handoff — 2026-08-19

- Phase 5 remains **in_progress**. It is not a near-complete phase: the first two knowledge-base deliverables have foundations but their real Docker ingestion/index/retrieval acceptance is blocked; self-growing knowledge/question-bank capabilities and the unified Agent Loop/L0-L3 memory remain future work.
- Task 10 is explicitly **blocked/abandoned at the user's stop line**. Full context is in `docs/superpowers/handoffs/2026-08-19-phase5-task10-context-handoff.md` in the feature worktree.
- Next window must read that handoff plus the three root planning files before acting. Do not repeat the settled float32 debate or rerun the deleted vertical script without a new diagnostic plan.

## 2026-08-19 · DeepTutor reuse decision

- [x] Read-only compatibility and license review completed for the local DeepTutor archive.
- [x] Recorded the no-wholesale-copy decision and candidate reuse classes in docs/superpowers/reviews/2026-08-19-deeptutor-phase5-reuse-review.md (feature worktree).
- [ ] Next Phase 5 implementation slice: design and implement current-native, space-scoped SQL/API foundations for learner notes, question attempts and wrong-question collection; reuse only reviewed pure helpers/concepts with Apache-2.0 attribution.
- [ ] Obtain a fresh independent review before any DeepTutor source-level copy, because the two review subagents on 2026-08-19 were rate-limited (HTTP 429) before reporting.

## 2026-08-20 · DeepTutor 全量复用审阅决定

- [x] 完成 DeepTutor learning/mastery/book/memory/Agent 关键模块的只读复审
- [x] 完成当前平台数据、权限、引用、worker、Provider/Billing 边界映射
- [x] 完成 Apache 2.0 与第三方 notices 复用约束核对
- [x] 形成正式复用报告：`.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-20-deeptutor-full-phase5-review.md`
- [ ] 在当前项目原生 SQL 学习域中实现题目、答题尝试、掌握度、复习任务和错题模型
- [ ] 迁移/重写 DeepTutor 的确定性评分、掌握度、下一目标和间隔复习纯算法
- [ ] 再接入最小 Agent 工具与课程提示词；不得引入第二套 DeepTutor runtime
- [ ] 最后评估 Book/Memory 高级能力

**复用决策：**采用 DeepTutor 的课程学习算法与交互约束作为参考/候选迁移来源；不整体复制其 runtime、存储、RAG、权限、计费或文件化 memory。Task 10 仍 blocked/abandoned，Phase 5 仍 in_progress。


## 2026-08-20 · Learning Foundation first slice (stopped quality gate)

- [~] Added an uncommitted pure-Python `tutor_api.learning` slice: deterministic grading, mastery, spaced-review scheduling, next-step policy, and three focused test modules.
- [x] Focused verification after the single quality correction: 30 passed; targeted Ruff and focused `git diff --check` passed. Pytest emitted only the pre-existing cache-write `WinError 5` warning.
- [x] Independent specifications review: **PASS** after one targeted contract correction.
- [!] Independent quality/security re-review: **FAIL** with one Minor residual frozen-contract issue: an OPEN `QuestionSpec` can retain a caller-supplied mutable non-string `expected_answer`, even though OPEN grading does not use it.
- [!] Per the project stop rule, this is the same immutability rule that already received one targeted correction. No third correction was made. This slice must not be marked complete or quality-approved; Phase 5 remains `in_progress`.
- [ ] Next work must be a separate Phase 5 item, not further tuning of this exception, unless the user explicitly revises the stop rule.

## 2026-08-20 · Next independent Phase 5 item planned

- [ ] Created `docs/superpowers/plans/2026-08-20-question-bank-foundation-plan.md` for a minimal native question-bank persistence slice.
- [ ] Scope is deliberately separate from the stopped Learning Foundation exception and blocked Task 10: single provenance snapshot per question version, server-owned answers, v1 creation and idempotent attempt recording only.
- [ ] First implementation task is tenant-aware schema + independent `0009` migration and focused schema tests. No API/LLM/scoring/Docker work starts until that schema task passes its review gates.
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

## 2026-08-20 · Question Bank Foundation Task 2 completed

- **Status:** complete — final independent **SPEC PASS** and **QUALITY/SECURITY PASS**. Phase 5 remains `in_progress`; Task 10 remains `blocked/abandoned`.
- **Delivered:** minimal tenant-aware Question Bank v1 API: server-validated signed citation creation, public question list/detail, and private own-attempt recording with SHA-256 idempotency keys.
- **Safety:** existing KB write/read authorization was reused; invalid/forged/cross-KB/inactive citations return hidden 404 without writes; public DTOs and public read queries exclude answers, rubrics, provenance, identities, and hashes; outsider attempts are directly regression-tested as 404.
- **Resource fix:** after one independent P1 review finding, normalized keywords are now bounded to 50 entries and 4,096 characters, and public read queries defer private ORM fields. The focused tests cover limits/no-write and deferred fields.
- **Verification:** `tests/test_question_bank_schema.py tests/test_question_bank.py` = **20 passed**; targeted Ruff and targeted `git diff --check` PASS. No Docker/Compose, Alembic execution, full suite, coverage, staging, commit, reset, stash, checkout, or protected Task 10/Learning file change.
- **Review evidence:** `docs/superpowers/reviews/2026-08-20-question-bank-foundation-task2-review.md`.
- **Next boundary:** Task 3 remains deliberately unstarted. It needs a separate quality-approved learning-domain transaction contract and must not call the stopped `tutor_api.learning` runtime.

## 2026-08-20 · Question Bank Task 3 assessment-contract plan

- **Status:** planned; implementation begins with Task 3A only. This is a native deterministic assessment ledger, not a revival of the stopped `tutor_api.learning` runtime.
- **Explicit v1 policy:** `choice`/`short` and open-without-keywords use normalized exact server-side matching; open-with-keywords uses normalized keyword phrase coverage; scores are integer basis points. Per-user/per-question-version assessment evidence is the limit of mastery scope.
- **Transaction target:** first idempotent submission must atomically write the attempt and one assessment; replay returns that stored evidence without recomputation or answer replacement. No teacher analytics, LLM grading, Agent work, course-level mastery, or dedicated review UI is in scope.
- **Plan:** `docs/superpowers/plans/2026-08-20-question-bank-assessment-plan.md`.

## 2026-08-20 · Question Bank Task 3A stop-rule record

- Task 3A deterministic assessment contract: focused functional/spec evidence passed (`20 passed`, targeted Ruff, targeted whitespace check; independent SPEC PASS).
- The independent quality/security re-review found a residual P2 in the **test-only AST import-isolation guard**: it misses `from tutor_api import learning`. The production assessment module currently has no prohibited runtime imports.
- The one allowed targeted correction for the same `ImportFrom` isolation rule was already used. Per the user-approved stop rule, no third repair will be attempted and Task 3A must not be reported as QUALITY/SECURITY PASS.
- Evidence: `.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-20-question-bank-assessment-task3a-review.md`.
- Next scope may be the independent Task 3B immutable assessment schema; it must preserve this known limitation in handoff material and may not silently claim Task 3A is fully quality-approved.

## 2026-08-20 · Question Bank Task 3B stop-rule record

- Task 3B immutable assessment schema: focused functional evidence passed (`35 passed`, targeted Ruff and diff check) and independent SPEC review passed.
- Current ORM and migration match, use the composite attempt identity FK and one-assessment uniqueness, and contain no answer/rubric/keyword/request-hash/provenance snapshot fields.
- QUALITY/SECURITY re-review found residual P2: the exact minimal-storage allowlist validates ORM metadata but does not independently validate the physical column set rendered by migration `0010`.
- This is the same privacy/minimal-storage regression-gate rule after its one targeted correction. Per stop rule, no third repair is allowed; Task 3B must not be reported as fully quality/security-approved. Evidence: `.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-20-question-bank-assessment-task3b-review.md`.
- Task 3C may proceed as a separately scoped atomic submit/replay API task, while carrying this known test-gate limitation forward.

## 2026-08-20 · Question Bank Task 3C complete

- [x] Completed the scoped atomic submit-and-assess API: first submission writes the private attempt and one immutable assessment in one transaction; safe replay returns the original persisted evidence without answer replacement or reassessment.
- [x] Independent SPEC review and final QUALITY/SECURITY re-review passed. The one permitted P1 correction serializes PostgreSQL submissions per `(user_id, question_version_id)` via a transaction-scoped advisory lock before replay/history/mastery reads.
- [!] Task 3A and Task 3B retain their separately documented P2 stop-rule limitations; this Task 3C PASS does not erase or reinterpret them.
- [ ] Next: plan a separate, minimal Phase 5 learning capability; do not revisit blocked Task 10 or perform a third repair of Task 3A/3B exceptions without a new approved scope.
## 2026-08-20 · Question Bank Task 4 review-queue plan

- [x] Planned a separate minimal owner-only wrong-question / review queue API over already immutable assessment evidence: `.worktrees/platform-foundation/docs/superpowers/plans/2026-08-20-question-bank-review-items-plan.md`.
- [x] Scope is deliberately read-only and migration-free; it excludes LLM/Agent, teacher analytics, task scheduling, Task 10, and further Task 3A/3B corrections.
## 2026-08-20 · Question Bank Task 4 review-queue complete

- [x] Delivered the scoped owner-only `review-items` read endpoint over immutable assessment evidence; no migration or new persistence was added.
- [x] Independent SPEC review passed. Independent QUALITY/SECURITY review passed with no P0/P1/P2 findings.
- [x] Controller verification: `tests/test_question_bank.py` = **20 passed**; targeted Ruff and the four-file `git diff --check` passed.
- [x] Review evidence: `.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-20-question-bank-review-items-task4-review.md`.
- [!] Verification remained intentionally bounded: no Docker/Compose, Alembic, full suite, coverage, real PostgreSQL concurrency/performance, or external-provider validation.
- [!] Task 10 remains blocked/abandoned; Task 3A and Task 3B retain their P2 stop-rule records. Phase 5 remains `in_progress`; Task 4 completion does not close the phase.
- [ ] Next scope must be separately planned and independently reviewed; do not revisit Task 10 or the Task 3A/3B stop-rule exceptions without a new approved scope.
## 2026-08-21 · Question Bank Task 5 attempt-history plan

- Planned the next independent Phase 5 slice: a bounded owner-only read endpoint for all immutable assessment history of one question version.
- Scope is migration-free and read-only. It reuses readable knowledge-base authorization, filters by current user and tenant, uses `QuestionAttempt.created_at` for newest-first keyset pagination, and exposes only the already-approved safe assessment projection.
- It deliberately excludes answer keys, submitted answers, rubrics, provenance, identities, request hashes, Task 10, LLM/Agent work, and changes to `tutor_api.learning`.
- Plan: `.worktrees/platform-foundation/docs/superpowers/plans/2026-08-21-question-bank-attempt-history-plan.md`.
## 2026-08-21 · Question Bank Task 5 completed

- [x] Added and independently reviewed the bounded owner-only attempt-history read endpoint for one question version.
- [x] Contract evidence: readable-KB authorization first; hidden 404 for inaccessible/cross-KB/cross-space versions; current-user isolation; all assessments retained; `QuestionAttempt.created_at` public timestamp; newest-first keyset ordering by `(attempted_at DESC, assessment.id DESC)`; `limit` 1..50/default 20/`limit + 1`; safe DTO-only output; and no GET writes.
- [x] Strengthened the focused pagination regression for three equal `attempted_at` values, using public `review_due_at` markers to prove secondary-key continuity across pages without exposing internal IDs.
- [x] Focused checks: 23 passed; targeted Ruff passed; untracked no-index whitespace check produced no whitespace diagnostics.
- [x] Independent SPEC review: PASS. Independent QUALITY/SECURITY review: PASS; no P0/P1.
- [x] Review record: `.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-21-question-bank-attempt-history-task5-review.md`.
- [!] Qualification: Task 5 allowed files remain untracked. The no-index diff check verifies emitted whitespace diagnostics only and does not replace the independent semantic/security reviews.
- [ ] Phase 5 remains `in_progress`; Task 10 remains `blocked/abandoned`; do not reopen the Task 3A/3B stop-rule records.

## 2026-08-21 · MVP 范围重定向（当前生效）

- [x] 收口一个客户可演示的“资料知识库 + 题库学习闭环”批次，而不是继续分散实现原 Phase 5 高级功能。
- [x] 完成一次集中 focused verification、一次 SPEC 审查、一次 QUALITY/SECURITY 审查及窄修复复审。
- [ ] 使用新鲜隔离环境完成最小真实资料链路验收；若失败，诚实保留 FAIL 并按客户决定缩减范围。
- [ ] 交付 Phase 6 客户验收包：演示步骤、范围声明、已知限制、延期高级功能和后续资金后的扩展清单。
- **Status:** complete




## 2026-08-21 · MVP 复审闭环中的当前门槛

- MVP 功能批次已完成：工作台不再承诺真实 AI 家教/LLM/费用，题库学习者 UI 和资料处理状态刷新已接入。
- focused 前端证据：3 个 Vitest 文件 21/21 通过；目标 ESLint 通过；非增量 TypeScript 检查通过。
- 独立 SPEC 与 QUALITY/SECURITY 复审已完成，但当前不能宣布通过：必须先收紧上传响应，不向浏览器返回 ingestion job、hash、worker/job 状态及无必要空间字段，并修复题库/资料刷新请求的取消竞态与前端答题幂等键复用。
- 题库历史 UI 本期明确收窄为“最近一页本人历史”；后端分页 API 保留，完整分页 UI 延期，不作为本次 MVP 阻塞项。
- 真实 Docker/pgvector 资料链路仍未验收；不得把服务健康或本地 focused tests 描述为端到端通过。


## 2026-08-21 · MVP 窄复审最终通过，进入 Phase 6

- MVP 主链路收口批次已完成，focused verification 与复审闭环完成。
- 最终独立窄复审结果：PASS；P0=0、P1=0、P2=0。
- 已关闭：上传响应内部字段暴露、题库切题/取消异步竞态、题库 loading 卡死、答题重试幂等键复用、提交成功后 review-items 刷新失败导致幂等键丢失、多个上传项状态刷新互相取消。
- Phase 6 当前只剩真实端到端资料链路、客户演示证据和验收包；不得把 focused PASS 等同于 Docker/PostgreSQL/pgvector PASS。

## 2026-08-21 · Phase 6 真实验收环境状态

- MVP 代码/复审门已通过，Phase 6 已启动。
- 当前 Codex PowerShell 无法解析 `docker`（`docker version` 返回“不是 cmdlet/可执行程序”），因此本会话未启动 Compose、未创建容器、未清理数据卷，也未伪造真实资料链路结果。
- Phase 6 真实 Gate 保持 pending / environment-blocked；需要用户在 Docker Desktop 已就绪且 `docker` 可解析的终端执行验收命令，或把 Docker 可执行文件/入口提供给本会话。

## Phase 6 实际执行结果（2026-08-21）

- [x] 新鲜隔离 Compose 环境启动、服务健康、Alembic 到 `0010_question_attempt_assessment`。
- [x] 完成注册 → 创建知识库 → 上传唯一 Markdown → 状态轮询的真实验收。
- [ ] 真实索引 → 搜索 → citation/source/page preview：**FAIL**；`build_index` 以 `index_validation_failed` 在 3/3 次尝试后失败。
- [x] 记录 API/worker/数据库证据并停止无依据重复修复。
- [x] 更新客户验收包，明确代码复审证据与真实资料 Gate 的边界。

**Phase 6 状态：部分完成 / 真实资料 Gate 阻塞。**

MVP 不能被称为“完整真实端到端可验收”；在客户接受该限制或单独授权一次有根因的最小修复前，不进入高级功能扩展阶段。题库学习闭环的 focused/API/UI 证据仍有效，但本次真实环境无法生成可引用资料 source，因此没有把题库演示伪装成完整资料驱动演示。

## 2026-08-21 · Phase 6 索引修复收口状态

- [x] 完成一次有根因假设的最小修复：embedding float4 32-bit 位模式比较。
- [x] 增加 signed-zero 边界回归测试并通过目标 Ruff、diff 检查。
- [ ] 在可用 Docker 入口中进行唯一一次真实资料链路重验；当前会话 `docker` 不可解析，环境入口待补齐。
- [ ] 只有真实重验成功后，才补充 searchable、搜索命中、citation/source/page preview 证据；若再次失败，立即按 stop-rule 保留 Gate FAIL。
- **Status:** Phase 6 code fix complete; real-data Gate pending/environment-blocked.

## 2026-08-21 · Phase 6 MVP 验收完成

- [x] 新鲜隔离环境完成真实资料导入 → 解析/索引 → searchable → 唯一 token 检索 → citation/source/page preview。
- [x] 复核服务健康与 Alembic head；真实链路证据与代码层 focused 证据边界已写入验收包。
- [x] 客户验收包已更新：交付范围、真实证据、历史限制、已知限制和延期高级功能均明确。
- **Status:** complete — MVP Phase 6 acceptance ready; advanced features deferred.

## 2026-08-30 · AI 组件真实链路恢复（组件级验收）

- [x] 不以 Faro health 作为成功标准，分别验证 AI 助教和知识候选的真实组件链路。
- [x] AI 助教：禁止恢复 failed/archived/旧 provider 会话；优先健康 Faro 会话，否则创建新 Faro/Gemini 会话。
- [x] 知识候选：兼容 Gemini 的 `formula_verification` 列表形态，保留多公式；同 canonical key 的跨块补充内容改为无损合并。
- [x] Worker 保留 `CandidateValidationError` 的稳定公开错误码，同时继续隐藏错误详情。
- [x] 聚焦 API/Web 测试、Ruff、ESLint、diff check 通过。
- [x] AI 助教真实 E2E 收到 `model_text_delta`，runtime completed，会话回到 waiting_input。
- [x] 知识候选真实任务 completed，批次 needs_review，持久化 29 条候选。
- **Status:** complete — 组件级后端链路已验证；UI 独立验收记录见 progress.md。

### 2026-08-30 补充：Web 代理路径回调修复

- [x] 独立浏览器验收发现：直接 API smoke 通过，但 UI 经 Web 代理发送 turn 返回 503，证明此前组件验收仍不完整。
- [x] 根因：API 使用 `request.url_for()` 从代理后的 `Host: web:3000` 派生 Runtime callback；宿主机 Runtime 无法解析 Docker 内部主机名，首个事件回调阻塞并在 30 秒后超时。
- [x] 修复：新增可信 `AGENT_RUNTIME_CALLBACK_URL`，API 不再从请求 Host 派生回调；Compose 默认指向宿主机可达的 `http://127.0.0.1:8000/api/v1/agent/runtime/events`。
- [x] 经 `http://127.0.0.1:3100` Web 代理完整 smoke：POST 202，收到 `model_text_delta`，runtime completed，session waiting_input。
- [x] 真实 UI 创建会话 `3bfc987d-1bd0-4a68-9bd5-f69c48d41587`；数据库持久化 `model_text_delta=UI_QA_OK_20260830`，最终 waiting_input / seq 4。
- **Status:** complete — Faro 基础健康、直连 API、Web 代理和真实 UI 会话均已有独立组件证据。

## Phase 7：选择性接入 qyw211 的支付/账户/欢迎页功能（完成）

- [x] 只移植支付后端，不合并 AI 助教、知识库检索、题库生成和工作台重构。
- [x] 基于当前 0018_object_deletion_outbox 新建线性支付迁移，不复制 qyw 的冲突迁移编号。
- [x] 保留 Faro/Gemini 与当前工作台布局，仅以独立账户面板接入。
- [x] 接入独立欢迎页并做现有认证回归。
- [x] 完成本地 API/Web focused tests、ruff、lint、build 和 git diff 安全审计。
- [x] 通过验证后提交当前 feature 分支；不提交 .env、密钥或 .tmp。
- **Status:** complete — awaiting commit and remote synchronization.

## 2026-08-30 · 选择性接入 qyw211 Web 功能（完成）

- [x] 仅移植 Web 账户面板、billing API、欢迎页及其样式
- [x] 账户面板使用独立 CSS module，保持可复用组件，不覆盖 workspace-shell
- [x] 仅补充二维码所需 Web 依赖，不改 API/AI/知识库核心
- [x] 完成账户面板定向测试、Web 全量测试、类型检查、lint 与生产构建
- **Status:** complete

## 本轮收尾：qyw211 支付后端选择性接入（2026-08-30）

- [x] 审计并选择性接入 qyw211 payment gateway / order billing API
- [x] 新建从 `0018_object_deletion_outbox` 继承的 `0019_recharge_orders_payment`
- [x] 完成支付、人工充值/钱包回归测试与 SQLite migration round-trip
- [x] 完成目标差异审查；未覆盖 core/config.py、main.py、compose.yaml、pnpm-lock.yaml、AI/知识库文件
- **Status:** code integration complete; Compose API/worker environment parity was restored and the full API suite is green
