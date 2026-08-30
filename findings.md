# Findings & Decisions

## Requirements

### 用户、空间与班级

- 支持用户名或邮箱 + 密码注册登录。
- 每位用户拥有独立的个人空间、教材库、会话、余额和长期学习记忆。
- 任何注册用户可创建班级；创建者拥有班级最高权限。
- 班级只设教师和学生两类角色，但角色显示名称可自定义。
- 创建者可设置或撤销其他教师；普通教师不能移除创建者或转移最高权限。
- 通过邀请码加入班级。
- 学生资料上传后默认仅个人使用；提交班级后由教师审核，批准后才进入共享知识库。

### 文件与知识库

- 首期支持 PDF、DOCX、Markdown、JPG、PNG。
- 支持 Obsidian Vault 文件夹或 ZIP 导入，保留 Markdown、附件、目录、标签、Frontmatter 和 `[[双向链接]]`。
- 文档处理采用“先提取文本层，必要时 OCR”的策略；同时保存原页图片或文档原件。
- OCR、Embedding、重排和解析引擎由管理员在后台切换。
- 知识库须记录索引版本、解析器、OCR、Embedding 模型、维度和建立时间，模型不兼容时触发重建而不是混用。
- 原始教材和练习册不可被 AI 改写。
- AI 可生成章节摘要、概念笔记、题型、错题和关系；个人空间允许自动写入且可撤销，班级空间必须教师审核。

### Agent 与学习体验

- 回答默认展示完整解答；用户可打开“分步引导”。
- 回答必须标注教材名、章节、页码，并可点击查看原页或原文。
- 当检索依据不足时，区分教材依据与模型补充知识。
- 支持基于上传资料出题、题库、错题集和学习掌握情况。
- 长期记忆记录学习进度、薄弱知识点、错题、常用教材和回答偏好；用户可查看、修改、删除或关闭自动记忆。
- 私人对话和记忆默认不向教师开放。

### 模型、配置与计费

- 首期供应商：阿里千问、DeepSeek、OpenAI API。
- 用户在答疑界面选择管理员已启用的大模型。
- API Key、Base URL、模型名及供应商相关配置通过服务端 `.env` 注入，不发送到浏览器。
- 平台统一承担 API 调用；不允许用户填写自己的 API Key。
- 逐次记录模型、输入 Token、输出 Token、缓存命中 Token、OCR/Embedding 等用量。
- 用户按调用发生时的官方 API 原价付费，不使用 Coding Plan、会员或套餐价。
- 历史账单保存调用时价格和汇率快照，不随未来价格变化。
- 第一版由管理员人工充值，所有充值和扣费形成不可直接修改的资金流水。

### 部署与界面

- 先在本机通过 Docker 测试，之后迁移到 Linux 云服务器。
- 主工作台采用已确认的 C3 布局。
- 最左栏为个人空间和班级空间切换器。
- 第二栏只显示当前空间内部的知识库层级：教材与练习、文件、知识图谱、AI 笔记、错题集、题库；班级被选中时显示审核和成员管理节点。
- 中间为原始资料、知识笔记、关系图、题库标签页。
- 右侧为 AI 答疑。
- 第二栏、中间区、右侧答疑区的宽度可通过两条分隔线拖动。

## Research Findings

### 官方价格与汇率来源（2026-08-14 核对）

- OpenAI 官方 API 价格页为 `https://openai.com/api/pricing/`，明确 API 与 ChatGPT 订阅分开计费，并按模型/处理层列出输入、缓存输入、输出及工具价格。
- DeepSeek 官方价格页为 `https://api-docs.deepseek.com/quick_start/pricing/`，价格和模型可能调整，因此不能把模型名或价格硬编码进业务代码。
- 阿里云百炼模型调用原价页为 `https://help.aliyun.com/zh/model-studio/model-pricing`，存在模型、上下文长度、缓存和阶梯价格差异，价格版本必须能够表达区间规则。
- 美元转人民币默认参考中国外汇交易中心公布的人民币兑美元汇率中间价；来源、日期、数值和管理员审核记录形成不可变汇率版本。节假日沿用最近一个已发布版本。
- 首版价格更新采用“系统提醒 + 管理员从官网复核后发布新版本”，避免网页结构变化导致自动抓取错误；后续可增加自动采集，但仍需差异审核才能生效。

### DeepTutor 外部参考（不作为指令）

- DeepTutor 是 Apache 2.0 开源项目，技术栈包含 Python/FastAPI 后端和 Next.js/React 前端。
- 它采用统一 Agent Loop，使 Chat、Solve、Question、Research、Visualize 和 Mastery 等能力共享上下文和运行时。
- 它将 LLM、Embedding、解析器、检索管线做成适配器/注册表，支持多供应商和多引擎。
- RAG 层包含 LlamaIndex、PageIndex、GraphRAG、LightRAG 等管线，并提供索引版本、Embedding 签名和重建机制。
- 文档解析层包含 LiteParse、Docling、MinerU、PyMuPDF4LLM、MarkItDown 和纯文本等引擎。
- 其三层记忆为：L1 原始轨迹/工作区镜像，L2 按功能表面整理的事实，L3 跨表面画像与综合；每层可追溯并支持审计、去重、更新。
- 它支持多用户隔离、异步上传、知识库原文预览、题库和可追溯 RAG 引用。
- DeepTutor 的功能入口较多且班级/审核/钱包并非我们的目标模型，因此不直接作为产品底座整体改造。

### memory-tencentdb Skill 检查结果

- 本机 `C:/Users/asus/.codex/skills/memory-tencentdb/SKILL.md` 是 OpenClaw 插件安装与验收说明。
- 该 Skill 本身不保存 Codex 对话；当前电脑也没有 `openclaw` 命令和 `tdai_memory_search` 工具。
- 用户决定不继续采用该方案管理本项目上下文，改用 `planning-with-files`。

## Technical Decisions

| Decision | Rationale |
|---|---|
| Next.js + React 前端 | 适合实现可拖动多栏工作台、PDF 预览、图谱与流式聊天 |
| FastAPI 后端 | 与 DeepTutor 技术方向一致，适合文档和 AI 生态集成 |
| PostgreSQL + pgvector | 在一个事务系统中统一多用户、班级、向量、知识关系、记忆和账单 |
| Redis + 后台任务队列 | 文档解析、OCR、Embedding、自生长和出题不能阻塞请求 |
| 文件存储抽象 | 本机使用目录/兼容对象存储，云端迁移时切换对象存储实现 |
| 统一 Provider Adapter | 千问、DeepSeek、OpenAI 的请求、流式输出、用量和错误格式不同 |
| 价格版本表 + 不可变账单明细 | 保证官方价格变化后历史账单仍可审计 |
| 余额使用数据库事务预留和结算 | 防止并发调用导致余额透支或重复扣费 |
| L0-L3 记忆和混合召回 | 避免把完整历史对话塞入上下文，同时保留可编辑、可追溯记忆 |
| DeepTutor 选择性复用 | 复用前做许可证和边界审查；班级、计费、权限和数据模型自主实现 |
| 模块化单体 + 独立 Worker | 首版保持业务事务简单，同时让文档与 AI 长任务可独立扩容 |
| 首版全文 + pgvector 混合检索 | 成本和复杂度可控；关系图先用于浏览、过滤与辅助扩展，未来再接 GraphRAG |
| 所有知识资源必须归属空间 | 统一个人与班级隔离，避免仅依赖前端路径判断权限 |
| 班级中的对话、错题和记忆同时归属用户 | 用户使用班级知识不代表私人学习数据自动共享给教师 |
| 学生分享采用冻结提交版本 | 审核期间内容不可静默变化；批准后班级建立受控副本/引用，撤销不删除个人原件 |
| 原生解析优先、页面级 OCR | 避免对所有教材无条件 OCR；文本用于检索，原页用于公式、图像和版面复核 |
| 索引版本构建完成后原子切换 | OCR、Embedding 或切分配置变化时不打断现有问答，并保留回滚能力 |
| AI 自生长内容采用版本化草稿 | 个人空间可自动发布并撤销；班级必须教师审核，已审核内容不被静默覆盖 |
| Agent 使用动态上下文预算 | 仅注入本轮相关的近期对话、记忆和教材证据，完整历史保留在数据库 |
| L0-L3 记忆必须可追溯和可编辑 | 防止黑盒画像；支持去重、冲突降权、删除和关闭自动记忆 |
| 用户界面隐藏内部执行流程 | 普通用户只看简化状态、最终结果和可展开的来源/费用；完整步骤仅供管理员诊断 |
| 供应商密钥与地址只放服务端环境配置 | 浏览器与数据库均不保存明文密钥；数据库仅保存启用状态、能力映射和非敏感版本信息 |
| 每次调用采用费用预留后按实际用量结算 | 防止余额透支；成功后释放未使用预留，失败且供应商未产生可核验用量时不扣用户费用 |
| 价格与汇率使用不可变版本快照 | 每笔账单锁定模型、输入/缓存命中/输出单价、计价单位、币种、汇率、来源和生效时间 |
| 后台模型切换不静默重建现有知识库 | OCR/Embedding/Rerank 新配置默认只影响新任务；已有知识库需明确发起可回滚的重建 |
| 普通用户只看到余额、模型价格和本次最终费用 | Token、OCR 页数、Embedding 用量等明细默认折叠，内部调用链只供管理员诊断 |
| 后台任务使用幂等、检查点和原子切换 | 服务重启或供应商失败后能够续传，且不会生成重复知识、重复发布或重复账单 |
| 本机与云端保持容器和数据迁移一致 | 首版使用 Docker Compose 验证，云端主要替换对象存储、入口、安全和运维设施 |
| 权限与资金准确性属于发布阻断项 | 跨用户访问、未审核班级发布、余额透支或重复扣费均不能带缺陷上线 |

## Issues Encountered

| Issue | Resolution |
|---|---|
| 工作区开始时为空且不是 Git 仓库 | 先完成产品设计与持久计划，正式实施阶段再初始化工程与 Git |
| Obsidian 窗口无法通过桌面控制读取 | 使用用户提供截图确认目标层级结构 |
| 初版 C2 将个人/班级空间放在内容树中 | C3 改为最左栏空间切换，第二栏只显示空间内容 |
| 用户最初希望 Tencent Memory 保存开发上下文 | 查明当前 Skill 仅适用于 OpenClaw后，用户改用文件规划 |

## Local Environment Check（2026-08-14）

- Node.js 已安装：v24.18.0。
- pnpm 可用：v11.19.0。
- 系统 Python 为 3.9.13，不作为本项目目标运行时；后端统一使用 Python 3.12 容器或后续安装的独立运行时。
- 初检时 Docker 和 uv 尚未可用；Docker 问题已解决，后续验收使用 Docker Desktop 29.7.2 与 Compose v5.3.1。项目不依赖系统 uv。
- 用户随后报告 Docker 已安装，但当前 Codex 终端仍无法解析 `docker`；桌面快捷方式目标位于已不存在的沙箱用户目录，标准安装目录也未发现可执行文件。可能需要重启 Codex/终端刷新安装状态，或确认 Docker Desktop 实际安装位置。
- 安装 WSL 后再次核对：`C:/Users/asus/AppData/Local/Docker/wsl` 已出现，但 Docker Desktop 主程序与 `docker.exe` 仍未安装到 Program Files 或当前用户程序目录；需要在 WSL 安装完成后重新运行 Docker Desktop Installer。
- Docker Desktop 最终安装在 `C:/Users/asus/AppData/Local/Programs/DockerDesktop/`。当前 Codex 沙箱不能直接执行该用户目录程序，但经授权在沙箱外验证成功：Docker Client/Server 29.7.2、Compose v5.3.1、引擎操作系统为 Docker Desktop。
- Codex 工作区提供独立 Python 3.12.13，可用于 Docker 安装前的后端单元测试与开发；正式项目仍以 Python 3.12 和锁定依赖为准，不依赖系统 Anaconda Python 3.9。
- `react-resizable-panels` 官方当前版本 4.x 使用 `Group`、`Panel`、`Separator`，并支持 `defaultLayout` 与键盘可访问分隔条；首个前端计划按该接口实现三块可拖动区域。
- 基础实现位于 `E:/项目/知识库课本/.worktrees/platform-foundation`，分支为 `feature/platform-foundation`；主检出和 `main` 分支未被自动合并或删除。

## Implementation Findings（2026-08-14 至 2026-08-16）

- 平台基础、身份与班级权限、供应商目录和钱包计费均已完成并经过独立规格与质量复审。
- 认证使用可撤销的 7 天 HttpOnly Cookie 会话；个人空间自动创建。邀请码仅在创建时返回一次，数据库保存 SHA-256 摘要；班级非成员读取保持 404，写操作返回 403。
- 生产配置失效保护拒绝 SQLite、未认证后端和占位凭据；MinIO 管理员与应用身份分离，应用仅有指定存储桶权限。
- 供应商配置严格解析且不回显原始输入；数据库只存非秘密模型资料、价格和汇率版本。用户只会看到启用、可计量的模型及安全的人民币价格摘要。
- 钱包采用 Decimal/NUMERIC、行锁、预留和追加式账本；结算绑定已验证用量及不可变价格/汇率快照。充值与一次性冲正均保留审计关系，冲正会拒绝造成余额倒挂的请求。
- C3 仍保持三面板和两条可键盘调整的分隔线；右侧只显示模型选择与两位小数余额，模型和余额独立失败、独立重试，避免泄露内部错误或供应商配置。
- SQLite 不可替代 PostgreSQL 的行锁验收；邀请码、首次建钱包、重复充值编号与冲正并发均有 PostgreSQL 专用回归路径。隔离 Compose 验收使用独立端口和卷，停止时不删除卷。
- Alembic 历史迁移标识需兼容 PostgreSQL 版本表长度；已保留历史标识、在写入前扩容，并将短期旧标识安全映射到保留的历史标识。

## Resources

- DeepTutor 官方仓库：https://github.com/HKUDS/DeepTutor
- 用户提供的 DeepTutor 源码包：`C:/Users/asus/Downloads/DeepTutor-main.zip`
- DeepTutor 本地只读参考摘录：`E:/项目/知识库课本/.superpowers/references/deeptutor/`
- 已确认 C3 原型：`E:/项目/知识库课本/.superpowers/brainstorm/platform-design/content/workspace-c3-space-navigation.html`
- planning-with-files Skill：`C:/Users/asus/.agents/skills/planning-with-files/SKILL.md`
- memory-tencentdb Skill：`C:/Users/asus/.codex/skills/memory-tencentdb/SKILL.md`
- 正式设计：`E:/项目/知识库课本/docs/superpowers/specs/2026-08-14-textbook-agent-platform-design.md`
- 实施路线图：`E:/项目/知识库课本/docs/superpowers/plans/2026-08-14-textbook-agent-platform-roadmap.md`
- 首个详细计划：`E:/项目/知识库课本/docs/superpowers/plans/2026-08-14-platform-foundation-plan.md`

## Visual/Browser Findings

- DeepTutor 首页使用左侧全局导航和中央大型对话入口，空间清晰但功能入口较多。
- DeepTutor 知识中心将检索引擎与知识库卡片分开，并在知识库详情页同时提供文件列表和原始 PDF 预览。
- DeepTutor 学习空间包含聊天历史、笔记本、题库、掌握路径、画像和 Skills。
- DeepTutor 记忆图采用 L3 中心、L2 中环、L1 外环的可追溯放射结构。
- 用户截图确认内容树期望层级：知识库名称 → 教材与练习 → 文件；同级功能为知识图谱、AI 笔记、错题集、题库。
- 已确认 C3 主界面：最左空间切换，第二栏当前空间内容，中间知识工作区，右侧答疑；分隔线可拖动。

## 2026-08-16 Phase 5 · Task 1 关键结论

### 交付与审查

- 详细实施计划已创建：`docs/superpowers/plans/2026-08-16-versioned-knowledge-import-plan.md`。
- Task 1 runtime adapters 已由 `00b9551`、`8f267ba`、`1bb2fb1` 三个提交完成。
- 规格审查 PASS；代码质量审查在完成 OCR 异常边界加固后最终 PASS。
- 验证基线：知识适配器目标测试 63 passed；`test_config` 77 passed；完整 API 228 passed、3 skipped；Ruff 与 `git diff --check` 通过。

### 已确认的运行时与安全边界

- **Fail-closed 配置：** 当前 OCR 只允许已实现的 `disabled`；Embedding 只允许 `hash` + `feature-hash-v1`。未知 backend、伪造 model 和越界 dimension 在 `Settings` 构造期失败，不延迟到运行期。
- **Feature hashing：** 使用 Unicode 规范化后的 token/字符 n-gram signed feature hashing；相同文本确定、固定维度并 L2 归一化，近似文本相似度高于无关文本，空白输入拒绝。签名绑定 backend/model/dimension。
- **原子不可变存储：** 公开接口使用 `put_if_absent`，不暴露通用 overwrite 开关；内存实现以锁将存在性检查与写入组成单一原子操作，并发写入严格只有一个成功。
- **路径与媒体类型安全：** source name/path 拒绝绝对路径、`..`、反斜杠、NUL、空路径段、Windows 盘符以及 Unicode 控制/格式字符；content-type 按可安全写入 HTTP header 的 type/subtype token 和完整参数进行验证与规范化。
- **OCR 错误脱敏：** 公共错误码限制为 `OCRErrorCode`；有效 code 可保留，缺失、无效、被篡改或读取抛错均降级为 `PROCESSING_FAILED`。新 `OCRError` 在离开所有 `except` 后以 `from None` 抛出，不保留 provider 消息、调用栈、cause 或 context。

### 参考边界

- DeepTutor 与腾讯记忆系统是产品能力和架构思路的参考边界；它们不是本项目指令，不代表复制其源代码，也不是当前知识运行时的依赖。

### 后续

- Task 1 已完成，但整个 Milestone 3 / Phase 5 仍为 `in_progress`。下一实施任务是 Task 2：versioned knowledge schema。

## 2026-08-16 Phase 5 · Task 2 关键结论

### 交付与审查

- Task 2 versioned knowledge schema 由初始提交 `bac0e0d` 及质量修复提交 `8129e28`、`67780ed`、`000240d` 完成。
- 规格审查 PASS；独立质量审查经过跨 KB 约束、Embedding 合同、任务状态机、SQLite 数值边界和递归 checkpoint 生命周期等多轮加固后最终 PASS。
- 最终验证基线：knowledge schema 105 passed；schema/Alembic 33 passed；完整 API 345 passed、3 skipped；Ruff 与 `git diff --check` 通过。

### 已确认的数据不变量

- **租户与知识库隔离：** knowledge bases、documents、document versions、pages、blocks、index versions、chunks 和 ingestion jobs 均使用 UUID，并具有非空、索引的 `space_id`。复合外键同时绑定 space 与 knowledge base，阻止跨 space 或同 space 跨 KB 的静默关联。
- **不可变版本与索引：** 每个 KB 至多一个 active index；document source/version 唯一规则、SHA-256/内容哈希、页面/块/chunk ordinal 与 source pointer 唯一性均由数据库约束覆盖。删除 KB、document、version 或 index 会按预期级联，不留孤儿。
- **Embedding 合同：** embedding 非空，backend/model/dimension/index signature 持久化，同一 index 的 chunk dimension 不能混用。SQLite 使用 JSON fallback 与一致命名的 INSERT/UPDATE triggers，校验数组根类型、数值元素、有限数，并安全接受 min/max integer、拒绝 Infinity；PostgreSQL offline SQL 启用 `vector` extension 并生成 `VECTOR` 类型路径。
- **可恢复任务状态机：** ingestion jobs 持久化 lease、retry、attempt、checkpoint、started/completed 时间，并以数据库约束保护 queued/running/retry_wait/terminal 状态以及 parse/OCR/build-index 的 kind/target 矩阵。
- **递归 checkpoint：** checkpoint 仅接受 JSON object；递归 mutable dict/list 会把嵌套修改传播至 ORM 根对象。子树跨任务赋值会复制而不共享 identity，替换、删除、pop、clear、slice/remove 等移除路径会解除旧父链接，detached 旧引用后续修改不会误标记或抛出 ORM 生命周期错误。

### PostgreSQL 验收边界与下一步

- 当前只验证 PostgreSQL offline SQL，未运行真实 PostgreSQL/pgvector；extension 创建权限、DBAPI vector bind/result 往返、JSONB 真实往返、并发行为和性能仍待后续集成验收。
- Task 2 最终 PASS，但 Phase 5 / Milestone 3 仍未完成；下一实施任务是 Task 3：space-scoped knowledge APIs。
## 2026-08-16 Phase 5 · Task 3 关键结论

### 交付与审查

- Task 3 space-scoped knowledge APIs 由提交 `92261fe feat: add scoped knowledge bases` 完成。
- 路由为 `POST/GET /api/v1/spaces/{space_id}/knowledge-bases` 与 `GET /api/v1/knowledge-bases/{knowledge_base_id}`，未扩展到上传、解析、OCR 或 worker。
- 规格审查 PASS，直接相关聚焦结果为 20 passed；独立质量/安全审查 PASS，高价值聚焦结果为 5 passed。
- 实现阶段最终基线：API focused 17 passed；schema uniqueness 3 passed；direct regression 179 passed；完整 API 365 passed、3 skipped；Ruff 与 `git diff --check` 通过。

### 已确认的权限、API 与数据库边界

- personal/classroom 访问控制完全由服务端查询 owner 与 membership：personal owner、classroom owner/teacher 可创建；classroom student 只读且创建返回 403；personal non-owner 与 classroom nonmember 返回 404；未认证返回 401。
- 详情查询把知识库 ID 与授权条件放在同一个受限查询中；已知 UUID 不能绕过 personal/classroom 或跨空间权限边界。
- 响应只暴露 `id`、`space_id`、`name`、`state`、`created_at`、`updated_at`，请求不能注入 owner、creator、role、state 或 body `space_id`。
- name 先 strip，再验证 1–120 字符；同空间名称由数据库唯一约束保护并返回稳定 409，不同空间可重用，名称语义保持精确且区分大小写。
- 列表严格限定 path `space_id`，并按 `created_at, id` 稳定排序。
- ORM 与尚未发布的 Alembic `0006` 同步加入 `uq_knowledge_base_name_in_space(space_id, name)`；重复名称失败使用 savepoint，不破坏外层 session；无关 `IntegrityError` 不应映射为重名 409。

### 保留风险与下一步

- 本阶段未运行真实 PostgreSQL/pgvector；PostgreSQL constraint-name 异常提取、真实数据库往返、并发与性能仍待后续集成验收。
- 非阻塞后续项：可补恰好 120 字符名称成功、同空间 `Physics` 与 `physics` 共存的回归测试；可进一步收窄 constraint-name substring fallback。
- Task 3 已完成，但 Phase 5 / Milestone 3 仍为 `in_progress`；下一实施任务是 Task 4：safe immutable uploads。

## 2026-08-16 Phase 5 · Task 4 关键结论

### 交付与审查

- Task 4 safe immutable uploads 的提交序列为：初始实现 `4ca2acf feat: add immutable knowledge uploads`；首轮规格修复 `07ec443 fix: harden immutable knowledge uploads`；交接文档 `091e95f docs: checkpoint immutable upload review`；质量 P1 修复 `53a253a fix: avoid blocking immutable upload worker`；取消 ownership 修复 `72c0194 fix: own upload temporary file in worker`。
- 最终独立规格复审 PASS；最终独立质量/安全复审 PASS。

### 已确认的上传与安全边界

- **不可变上传协议：** API 校验 MIME/extension/signature/size 组合，以分块读取计算 SHA-256 并写入 spool；文件名先做 NFC 规范化，拒绝控制/格式字符与不安全名称。
- **租户与幂等：** personal/classroom 权限由服务端判定；KnowledgeUploadRequest 约束请求；相同 idempotency key + 完全相同请求返回同一版本，不同请求稳定冲突；相同 SHA 可复用不可变对象但不覆盖历史，新内容按锁内状态递增版本。
- **持久化结果：** 成功上传创建或复用 Document，创建不可变 DocumentVersion，并排入 queued ingestion job；响应只在数据库 commit 后返回。
- **生产安全：** production multipart 初始化有进程内锁；provider/storage 异常映射为受限公共错误，避免泄露 provider 文本、堆栈与内部诊断。

### 并发、线程与取消所有权

- 文件 prepare（读取、校验、hash、spool）期间不持有数据库锁；同步数据库查询、行锁、对象存储写入和 commit 全部放入 worker thread，避免阻塞事件循环。
- 同一 SQLAlchemy Session 的数据库工作保持在线程内，满足 Session thread ownership；拿到锁后执行最终权限重检，避免 prepare 期间权限变化被遗漏。
- PreparedUpload lease 把 copied temporary file 的 ownership 交给已启动 worker。客户端取消后，worker 不会使用已被 request cleanup 提前关闭的临时文件；原 UploadFile、原 spool 与 worker-owned copy 均有确定性关闭路径。
- commit before response 保证成功响应对应已提交状态；客户端取消后，已经接管 lease 的 worker 仍可能在后台完成。

### 准确验证记录

- `07ec443` 时：upload focused 57 passed；相关 regression 308 passed；完整 API 425 passed、3 skipped；targeted Ruff 与 `git diff --check` 通过。
- 独立规格复审运行 61 focused passed。
- `53a253a` 后：Task 4 upload focused 60 passed，仅完整运行一次；targeted Ruff 与 diff check 通过。
- `72c0194` 后：取消/线程定向 4 passed；增量规格复审另 2 passed；最终质量复审执行静态检查与 2,000 次内存竞争探针。
- 两个并发修复后没有重跑完整 API suite；未运行真实 PostgreSQL/pgvector/MinIO/Docker/OCR/external services。

### 保留风险与下一步

- 真实 PostgreSQL 行锁、constraint diagnostics 与真实 MinIO conditional-create 尚未验证。
- object write + DB commit 不是分布式事务；数据库提交失败时可能留下不可变 orphan object。
- 同一知识库上的慢 storage 或锁等待可能长期占用 AnyIO worker pool；后续需引入 timeout、limiter 或队列化方案。
- 客户端取消后已接管的 worker 可能后台完成，目前缺少专门的结果日志、任务关联与可观测性。
- copied spool 的落盘复制仍在异步路径中执行，可能造成短暂事件循环延迟。
- lease duplicate claim 在当前生产调用路径不可达，但尚未显式拒绝；service 的 caller-owned temporary file contract 也应后续明确。
- DOCX 只检查 ZIP magic；100 MiB 限制只在 service layer；digest 未加入 domain prefix。
- Task 4 final PASS 不代表里程碑完成：Phase 5 / Milestone 3 继续保持 `in_progress`，下一步为 Task 5：native parsing and Obsidian import。

## 2026-08-17 Phase 5 · Task 5 关键结论

### 交付与审查

- Task 5 native parsing and Obsidian import 的提交序列为：`2dc8ce1 feat: parse supported knowledge formats`、`30014ae fix: harden native knowledge parsers`、`5c70d87 fix: bound native parser resources`、`75997c7 fix: bound zip central directory`。
- 最终独立规格复审为 **Task 5 specification review PASS**；最终独立质量/安全复审为 **Task 5 quality/security review PASS**。

### 已确认的解析与资源边界

- 测试代码生成确定性微型 PDF、DOCX、Markdown、PNG 与 Vault ZIP fixture；解析结果保留 PDF 页码/块顺序、DOCX 标题/段落/表格顺序、Markdown 行范围/frontmatter/tags/table，以及 Vault 的规范化路径、附件和 wikilink。
- PDF 原生优先提取，低文本或乱码页标记为 `needs_ocr`；页面树、页数、文本和块均有预算。DOCX 使用安全 ZIP/XML 路径；XML 防护为编码感知的字节模式 fail-closed。Markdown frontmatter 受 64 KiB 限制并对深 YAML 错误脱敏。PNG 聚合 IDAT 后执行有界 zlib/scanline 结构验证。
- Vault ZIP 拒绝路径穿越、drive-relative、bomb、Zip64、多磁盘和超预算输入；目录计入条目限制，路径字节/深度、单 Markdown、累计 Markdown、行/块/tag/wikilink 均有界，tag 使用有序 O(1) 去重。
- 质量/安全复审最后一个 P1 已关闭：经典 EOCD 的 `central_size` 在 `zipfile.ZipFile` 构造前检查。DOCX 固定、Vault 默认使用 16 MiB 中央目录预算；Vault 参数可注入但必须是非 bool 的严格正整数。真实 ZIP entry comment/extra 测试及 spy 确认预检拒绝时 `ZipFile` 从未构造。

### 准确验证记录

- 聚焦解析器测试：57 passed。
- 目标 Ruff：`parsers.py` + `test_knowledge_parsers.py`，`--no-cache`，All checks passed。
- `git diff --check`：pass。
- 增量规格复审：PASS；聚焦 7 passed，确认正常 DOCX/Vault 未回归且中央目录限制稳定 fail-closed。
- 增量质量/安全复审：PASS；聚焦 8 passed，并完成 DOCX/Vault 预构造拒绝、Zip64、多磁盘与最大 EOCD comment 等只读安全探针。
- 未运行完整 API suite；未使用 Docker、PostgreSQL、MinIO、OCR、外部服务或大型真实文档集成测试。

### 保留风险与下一步

- `pypdf.extract_text` 仍无子进程隔离或墙钟超时；单次第三方提取调用在返回文本预算检查前仍可能瞬时消耗 CPU/内存。
- 未执行真实大文件/复杂 PDF、DOCX、PNG 或 Obsidian Vault 集成；PNG 是有界结构验证器而非完整 PNG 一致性实现。
- XML 加固是编码感知的字节模式 fail-closed 防御，不是专用 hardened XML 库。YAML 在 `safe_load` 前仅由 64 KiB frontmatter 上限约束，节点/深度预算在 load 后执行。
- ZIP 当前未拒绝 symlink 之外的所有 Unix 特殊类型，但当前解析流程不把归档内容落盘解压。
- 16 MiB 中央目录是安全策略，可能拒绝极端 metadata-heavy 但合法的 ZIP；Vault 上层若允许调高预算，应只开放给可信调用方并继续设置上限。
- 解析器调用前输入仍整体为 `bytes`；本轮资源限制主要防止解析阶段进一步无界物化，不限制上游完整上传缓冲。
- Task 5 final PASS 不代表整个导入阶段或里程碑完成：选择性 OCR、页证据、索引、检索与引用仍未实现；Phase 5 / Milestone 3 保持 `in_progress`，下一步为 Task 6：selective OCR and page evidence。

## 2026-08-17 Phase 5 · Task 6 关键结论

### 最终状态与交付

- Task 6「selective OCR and page evidence」final PASS；Phase 5 / Milestone 3 继续保持 `in_progress`。
- 提交序列：`e2e2a6b feat: add selective page OCR`、`d9f244d fix: bound selective OCR resources`、`5225691 fix: close OCR lifecycle gaps`。
- 初始完整规格复审 PASS。首轮质量复审指出 subprocess 输出/后代清理与文档累计资源预算问题，`d9f244d` 完成修复；后续质量复审又提出 4 个 Important，`5225691` 全部关闭。最终独立增量规格复审 PASS，最终独立质量/安全复审 PASS。

### 设计与安全决策

- OCR 仅针对 PNG 与 `needs_ocr=True` 的 PDF 页；PDFium child 按需渲染，Tesseract adapter 执行 OCR。默认 OCR backend 为 disabled，容器镜像只在 non-root `USER` 之前安装 English/Chinese Simplified Tesseract 包。
- evidence、checkpoint 与 result 均为 immutable，保留 page number、block order、source pointer；partial failure 可恢复，provider 错误保持稳定映射与脱敏。
- 预算采用双层边界：单页 pixel/language/per-call output/input/time 上限，以及 document-level page/evidence/text/deadline 累计上限；subprocess stdout 有界，避免文档规模线性放大单次调用资源。
- `d9f244d` 补齐 bounded subprocess output、descendant 清理与文档累计预算。`5225691` 进一步统一 `Popen` 后清理边界，关闭第二个 `Thread.start` 失败泄漏；Windows 改为 suspended + Job fail-closed，并删除不安全 PID-tree fallback；所有 adapter 使用 `timeout_seconds/remaining` 合同，legacy adapter 在 body 前 fail-closed；stdin-only descendant deadline 正确映射为 `TIMEOUT`。
- Windows Job containment、POSIX process-group 静态路径，以及进程、pipe、I/O thread、Job/process handle 的确定性清理共同构成生命周期边界。

### 验证结论

- `d9f244d` 后主线程验证：OCR 44 passed；adapter OCR 10 passed；parser 57 passed；targeted Ruff PASS；`git diff --check` PASS；新的增量规格复审 PASS。
- `5225691` 后主线程最终限定验证：`test_knowledge_ocr.py` 49 passed；`test_knowledge_adapters.py -k ocr` 10 passed；`test_knowledge_parsers.py` 57 passed；targeted Ruff PASS；`git diff --check d9f244d..5225691` PASS。
- 最终独立增量规格复审 PASS，reviewer 运行 11 focused passed。最终独立质量/安全复审 PASS，reviewer 运行 7 focused passed。
- 质量 reviewer 的只读探针：10 次真实 BrokenPipe 全部稳定映射为 `PROCESSING_FAILED`；Windows Job handle 精确关闭 1 次；预热后成功 3×20 与 timeout 3×10 调用的 handle 数稳定，OCR I/O threads 归零。
- 未运行完整 API suite、真实 Tesseract/container smoke、Docker、PostgreSQL、MinIO、外部服务、POSIX 实机 process-group 路径或复杂 PDFium corpus。

### 非阻塞残余风险与下一步

- 尚未运行真实 Tesseract/container smoke；尚未在 POSIX 实机执行 process-group 路径，主动 `setsid`/改组的 descendant 可能逃离。
- 尚未运行复杂 PDFium corpus，PDFium child 没有 OS 级地址空间上限；每个 PDF OCR 页仍需 spawn 并复制完整 PDF bytes，输入也仍整体以 `bytes` 进入。
- 安全预算可能拒绝极端但合法的页面；OCR executable 必须来自可信配置。
- deadline-aware adapter 是受信任 port 合同；声明支持却忽略 timeout 的 adapter 无法由当前调用方强制终止。
- Windows Job Assign 使用 CPython `Popen._handle` 私有属性，需要随 Python 版本复核。
- POSIX 轻微风险：强制 SIGKILL 位于第一次 bounded join 后，理论上 daemon I/O thread 可能极短暂存活；现有重复探针没有发现持久或线性泄漏。
- Task 6 final PASS 不代表整个导入阶段或 Milestone 3 完成；下一步为 Task 7「immutable indexing and reliable worker」。

## 2026-08-18 · Task 7「immutable indexing and reliable worker」最终记录

- **状态：**最终 PASS；Phase 5 / Milestone 3 仍为 `in_progress`，Task 8 尚未开始。
- **交付提交：**`f298eb2`、`96a3ad6`、`53284ca`、`cfc6220`、`0d34b2a`、`363f3fb`；功能工作树文档：`8f22c2d`。
- **核心保证：**immutable contract-bound target、heading-aware bounded chunks、完整 parser/OCR/chunk/embedding contract 才允许 vector reuse、source/page/block/lexical/vector provenance、原子 activation（失败保留旧 active）、lease + `FOR UPDATE SKIP LOCKED` + stale/retry/restart safety、与 API image 复用的 Compose worker。
- **关键加固：**S3 redirect/响应关闭/对象字节上界；non-local production storage 在 API 与 worker 启动时强制 HTTPS；terminal parse state/timestamps；READY snapshot 在 KB 锁内捕获；adapter signature drift 会失败并清理旧的未激活 target，再幂等创建/复用 current-contract build job。
- **OCR 语义：**初始独立质量审查识别到“有内容页 + 空白完成 OCR 页”会被错误拒绝；`363f3fb` 改为仅当整篇无可索引 block 时 `ocr_empty_result`，而 failed checkpoint、未完成 OCR 与全空 OCR 仍失败关闭、且不落 partial graph。审查中提出的 production-HTTP 项为误报：`Settings.production_errors()` 已拒绝非 HTTPS 的 non-local endpoint。
- **验证：**post-fix 独立规格 PASS（34 focused），独立质量/安全 PASS；最终相关组合 362 passed（36 warnings）、迁移节点 3 passed（4 warnings）、targeted Ruff PASS、`git diff --check aa71123..HEAD` PASS。
- **非阻塞风险：**长外部 handler 期间持有 transaction/job lock；S3 PUT 在配置上限内缓冲整个对象；未进行真实 PostgreSQL/pgvector、MinIO/S3、Redis、Docker、Tesseract/PDFium corpus、外部服务或 live POSIX process-group 验收。历史 Windows 大组合中的两个 1 秒 OCR PID-file 探针曾时序失败，但精确两项、完整 OCR 与最终 362 组合均通过，质量审查判定为非阻塞测试时序观察。
## 2026-08-18 · Task 8 cited retrieval findings

- 只限制候选 heap 大小不足以保证数据库工作有界于常数；当前实现选择完整 ACTIVE index 流式扫描以保证召回正确性，内存保持有界，但总行工作仍为 O(index size)。这是明确记录的性能权衡，不是安全或正确性缺陷。
- runtime embedding 合同不可假定与 ACTIVE index 相同；重建完成前旧索引仍可 ACTIVE，因此 query adapter 必须与已存 backend/model/dimension/signature 精确匹配，否则只能 lexical-only。
- cited page preview 必须由正常解析持久化路径生成；仅在测试中直接设置 `Page.text_object_key` 会制造无法用于真实上传的假闭环。
- opaque citation 仍需在对象读取前重新验证知识库作用域、ACTIVE index、文档/版本状态和租户权限；不能把 token 完整性当作授权替代品。

## 2026-08-18 · Task 9 C3 knowledge workspace findings

- A document `ACTIVE` state alone does not mean learner search readiness: an accepted upload can be `ACTIVE / UPLOADED / QUEUED`; only a `READY` version with `COMPLETED` job is shown as `可搜索`, failures as `处理失败`, and all other accepted states as `处理中`.
- Client-side request sequencing alone avoids stale state writes but does not stop costly work. Create/upload/search/preview controllers are retained, aborted on unmount or KB context switch, removed after settlement, and intentional aborts stay silent.
- Upload retry must preserve its original idempotency key; while an upload is active, duplicate submission is disabled and older completion clears the chooser only if the same `File` remains selected.
- The knowledge panel consumes only existing cookie-auth KB routes and opaque citation tokens. It neither invents document listing/status polling nor exposes OCR, embedding, worker, provider, storage, object-key, or citation-token internals.
- There is no tutor/Agent Loop API in this milestone; the static tutor surface is not a failed request path. Model, balance, and knowledge requests retain independent error/retry paths.

## Session: 2026-08-18 · Phase 5 / Task 10 verification（blocked, reviewed）

- **Honest gate state:** Task 10 remains incomplete. Web test/lint/build passed (7 files / 34 tests); API Ruff passed only with `--no-cache`; full API coverage was 590 passed / 3 skipped / 2 failed and 88.08%, below the mandatory 90% threshold. The two failures are Windows OCR descendant-timeout PID-file timing assertions; no source change weakened them.
- **Runtime gap:** Docker CLI/Desktop plus `psql`, `pg_isready`, and `initdb` were absent on 2026-08-18. A real PostgreSQL/pgvector upgrade/downgrade round-trip and Compose vertical slice (register → KB → deterministic Markdown/PDF → READY → search → cited page) remain unrun, not failed/passed by inference.
- **Evidence boundary:** Deterministic parser/upload tests cover PDF, DOCX, Markdown, JPEG, PNG and Obsidian ZIP plus both `.jpg` and `.jpeg`; no binary textbook fixtures are tracked. `alembic heads` and focused OCR success are informative only and do not replace the live migration or full coverage gates.
- **Configuration boundary:** knowledge defaults are 100 MiB upload, 5,000 Vault members, 500 MiB uncompressed Vault data, disabled-only OCR, and deterministic `hash / feature-hash-v1 / 384` embeddings. The OpenAI profile in `.env.example` is nonfunctional example metadata with empty credentials; no remote OCR/embedding provider or enabled real model call is configured. Compose does not forward arbitrary knowledge overrides to both API and worker.
- **Review result:** final independent SPEC PASS and QUALITY/SECURITY PASS after narrowly correcting the Task 10 files list, provider wording, and a handoff terminal LF. No completion claim is justified.
## Session: 2026-08-18 · Milestone 4 design-preparation boundary

- **Reusable but incomplete:** the deployed codebase has an authenticated model catalog, internal idempotent wallet reserve/settle/release services, space-scoped knowledge search, opaque citation tokens and authorized source preview. These do not constitute a tutor runtime.
- **Absent by evidence:** no provider invocation/usage-verification adapter, Tutor/Agent request API, conversation/message/citation persistence, question/wrong-answer service, or L0–L3 memory model/API exists yet. The C3 tutor controls remain a static shell.
- **Safety gates for the new task:** an Agent run must make reservation, authorized retrieval, provider call, verified usage settlement or release, response citation binding, and private learning-data isolation explicit. A model catalog/example profile is not evidence of enabled invocation or billable usage.
- **Design dependency:** current formal design assigns this scope to Milestone 4, but the concrete provider/model and policy choices must be locked in the design/implementation plan before production enablement. Task 10 Docker/pgvector and coverage blockers remain separate, unresolved gates.
## 2026-08-18 · Milestone 4 设计准备独立规格复核

- **复核结论：**设计准备信息足以识别边界，但不足以批准实施；唯一最高优先级的未决项是首个 Tutor `ProviderProfile`（具体供应商 + 具体模型）及其可核验 usage / 生产计费姿态。
- **已证实可复用：**`providers` 中的受认证模型目录和价格/汇率版本；`billing` 的 Decimal/NUMERIC 钱包、幂等预留、核验用量结算、释放和不可变账本；`knowledge` 的空间授权检索、opaque citation 与受权来源/原页回看；C3 的模型、余额和输入展示壳。
- **未落地：**远程 LLM 适配器、流式/usage 解析与核验、Tutor 编排和模式状态机、Conversation/Message/AnswerCitation/AgentRun/ToolCall、题库/作答/错题、L0–L3 记忆和用户控制。当前检索引用只有来源与页码，未满足回答级教材名/章节/页码、证据持久化和模型补充知识区分。
- **推荐决策路径：**指定一个能返回可由服务端核验真实 usage 的具体模型，之后才作为生产计费 Tutor 启用；若不能确认 usage，只能作为不可计费预览或模拟 Provider，不能扣用户钱包。
- **隔离约束：**Task 10 仍为 blocked（覆盖率 88.08% < 90%，且本机没有 Docker/PostgreSQL 工具以运行迁移往返和 Compose vertical slice）；Milestone 4 设计绝不替代这些验收门禁。
- **审查来源：**独立子代理只读复核；正式需求见 `docs/superpowers/specs/2026-08-14-textbook-agent-platform-design.md`，路线图见 `docs/superpowers/plans/2026-08-14-textbook-agent-platform-roadmap.md`，Task 10 证据见 `docs/superpowers/handoffs/2026-08-18-task10-verification-blocked.md`。
## 2026-08-18 · Task 10 environment now available (still unexecuted)

- Docker Desktop is running and the verified absolute CLI is `C:\Users\asus\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`; Engine client/server are `29.7.2` and Compose is `v5.3.1`. Sandboxed Docker access is denied, so stateful Docker/Compose commands require the controlled elevated invocation rather than PATH changes.
- Compose is the required route for the vertical slice; no local PostgreSQL client/server tools are needed. The only external runtime precondition is permission to pull pinned images and allocate isolated disk/CPU/memory/network resources. A proxy/image-pull failure must be fixed in Docker Desktop networking, not bypassed.
- The final Task 10 environment procedure is committed at `5a242dc docs: prepare Task 10 environment handoff`. It requires fail-closed `.env` creation, an explicit unique Compose project, project-scoped destructive cleanup only after redacted evidence, preservation/restoration of `COVERAGE_FILE`, an independent pgvector migration round-trip, and a deterministic PDF citation `GET .../page` proof that source preview cannot replace.
- This availability changes no acceptance result: Task 10 remains incomplete until the three outstanding live/coverage gates pass. Milestone 4 remains a separate formally billable Tutor scope whose concrete provider/model, verified usage, protocol, and price/FX owner are unresolved.

## 2026-08-19 · Task 10 coverage 状态与恢复约束

- 已验证的 OCR 问题根因是 Windows `CREATE_SUSPENDED → Job Object assignment → ResumeThread` 的安全启动时间被原先 0.2 秒预算吞没；coverage instrumentation 下 helper 可能尚未写入 PID 即被终止。修复仅针对 Windows 将 deadline 置于成功 Resume 后，POSIX 继续在 `Popen` 前计时。
- 外部 OCR child 只移除 `COV_CORE_SOURCE`、`COV_CORE_CONFIG`、`COV_CORE_DATAFILE`、`COV_CORE_BRANCH`、`COVERAGE_PROCESS_START`；不变更父环境，且保留 `OCR_*` 与普通业务变量。聚焦 6 个进程契约测试、两项历史 descendant 测试（普通与 coverage diagnostic）及 `test_knowledge_ocr.py` 49 passed 已通过；ruff/diff check 通过。
- 官方全量 API coverage 随后为 `592 passed, 3 skipped, 88.13%`。此结果表示历史 OCR 功能失败已消除，唯一阻塞为项目覆盖率阈值 90%，不是测试失败。不得把两项低总覆盖率的 coverage diagnostic 非零退出误记为功能失败。
- 代理恢复状态：先前四个代理的工具句柄在本会话恢复后不可枚举；本地 feature diff 只含 `apps/api/src/tutor_api/knowledge/ocr.py`，没有任何测试改动或额外 worktree。因此于 2026-08-19 以互斥文件范围重新派发四个独立测试子任务。不得与其并行编辑同一文件。
- Docker 可用但 sandbox PATH/权限不足；仅可经受控 elevated 的绝对 `docker.exe` 调用。未发现本地 PostgreSQL/pgvector、Redis、MinIO、psql、pg_isready 或 initdb；Compose 路线不需要安装它们。真实 Docker 操作仍须用户明确允许创建 Git 忽略 `.env`、拉镜像、启动唯一隔离项目、执行可销毁 migration、保存脱敏证据及仅项目级清理。

### 2026-08-19 · OCR coverage 测试复审结论

- OCR coverage 扩展的最终范围仅为 `apps/api/tests/test_knowledge_ocr.py`；当前 feature worktree 同时保留早已审查的 `apps/api/src/tutor_api/knowledge/ocr.py` 生产 diff。最终一组测试通过公共 `TesseractOCRAdapter.extract_text` 路径（而非直接调用 `_run_tesseract_process`）验证可观察的 deadline/错误契约。
- Windows-only 测试通过明确的 creationflags、Job Object API 与有界 wait mock 表达契约；它们在当前 Windows 主机的 suite 中被平台条件跳过，因此不能把本机结果表述为实际 Windows subprocess 路径已实机执行。其结构、资源清理和无全局污染特性已分别由独立 SPEC 及 QUALITY/SECURITY review 审查通过。
- 曾出现的测试问题及已采取的最小修复：helper embedded-source `\\n` 转义错误；私有函数耦合；suspended-child 立即副作用检查；terminate 后未 wait；assignment-failure 未记录 CloseHandle；测试收集期通过 `setattr(subprocess, "CREATE_SUSPENDED", ...)` 污染标准库。最终改用局部 `_CREATE_SUSPENDED = getattr(...)` 常量，未修改标准库。
- 在所有 A–D 覆盖率组完成独立 review 前，不运行新的 full API coverage。当前 Task 10 coverage 证据仍是 `592 passed, 3 skipped, 88.13%`，并未因本组窄测试而改变。

## 2026-08-19 · Task 10 S3 range adapter coverage finding (accepted)

- S3 range 响应必须 fail-closed：有 Content-Range 只接受 206；无该 header 的兼容回退只接受 200、start=0、可解析且不超过请求长度的 Content-Length 与精确匹配正文。
- 实际 response body 超长会触发通用 _read_bounded() 的 ObjectSizeLimitError；在 range 协议路径中这属于 header/body 不一致，因此仅在 get_object_range() 的两处读取调用把它稳定归一化为 ObjectRangeNotSatisfiableError from None。通用对象大小限制未被扩大捕获。
- 回归测试包含真实 loopback urllib 206 与 200 fallback 成功路径、两分支超长 body、截断/畸形/状态不配对、稳定异常映射、response close 和 HTTP server shutdown/server_close/bounded join/thread-dead 断言。
- 定向证据：`test_knowledge_adapters.py 为 109 passed；targeted Ruff、git diff --check PASS；最终 fresh SPEC PASS，随后 fresh QUALITY/SECURITY PASS。未声称 full coverage 或 Docker acceptance 通过。
## 2026-08-19 · Task 10 worker coverage finding (accepted)

- Worker parse 必须将不可变 version 的 SHA-256 或 content type 与对象实际字节/内容类型不符稳定终结为 object_content_mismatch，不得持久化 pages、blocks 或 BUILD_INDEX job。
- 不合法 BUILD_INDEX checkpoint 应终态失败、移除 partial target，且不建立 replacement；终态 parse 失败同样不得 enqueue index 或重试。
- lease 竞争测试不能把 StaticPool 的共享 SQLite 连接当作独立接管事务：handler 异常会回滚同连接的 replacement 写入，造成错误的陈旧失败复现。显式 NullPool 独立连接 + 已提交公共 claim 可稳定验证陈旧 complete_job() 与 `fail_job() 都返回 worker_lease_lost 且完整保留 replacement 状态/lease/checkpoint/error 字段。
- 定向证据：`test_knowledge_worker.py 22 passed，targeted Ruff、git diff --check PASS；最终 fresh SPEC PASS，随后 fresh QUALITY/SECURITY PASS。无 full coverage/Docker completion claim。
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

## Task 10 coverage decision (2026-08-19)

- The post-indexing official API coverage command completed with 664 passed and 4 skipped. The reported total was 89.41%, up from the prior 89.18%, but the former 90% fail-under threshold still caused the command to exit 1.
- No test failed on functionality. The remaining coverage concentration includes platform-sensitive OCR/parser/worker paths and lower-value exception branches.
- User explicitly approved not spending further effort to close the remaining 0.59 percentage-point coverage gap. Treat this as a documented acceptance exception, not as a claim that the original 90% gate passed.
- Current unit tests do not require OpenAI or Anthropic keys. Compose defaults provider profiles to an empty array; OCR and embeddings use local deterministic implementations.
## 2026-08-19 · Task 10 pgvector/Docker final finding

- 初始真实 Docker 失败并非虚假 API key：`PROVIDER_PROFILES_JSON=[]`，本地 embedding 为 deterministic hash adapter，不调用外部 provider；Alembic 为 `0008_embedding_contract (head)`。
- 根因曾定位为 PostgreSQL/pgvector `VECTOR` 的 float4 回读与 Python embedding 精确列表比较冲突。实现了最小兼容校验：`persisted == expected`（SQLite）或 `persisted == float32(expected)`（pgvector），不使用宽泛 `math.isclose`。
- 最终 focused indexing 验证：35 passed；Ruff 与 diff check PASS；独立 SPEC PASS。质量复审指出原跨 binade 测试常量不是可表示的真实 2-ULP float32，已改为 `2.000000238418579`；该回归测试随后通过。
- 重建隔离 Docker API/worker 镜像后，Alembic current 仍为 `0008_embedding_contract (head)`，但真实 `task10_vertical_slice.py` 仍在 150 秒后失败：`status=200, results=0`。数据库中该次知识库最近的 `index_versions` 均为 `state=failed`。因此没有声称真实 pgvector 垂直链路通过。
- 按用户止损要求停止继续修复。当前 feature worktree 的未提交改动全部保留；未 reset/stash/stage/commit；未配置或需要真实 OCR/embedding/LLM API key。

## 2026-08-19 · Phase 5 new-window handoff

- 用户确认当前上下文不足，要求转入新窗口继续；已新增 feature worktree 交接文档：`docs/superpowers/handoffs/2026-08-19-phase5-task10-context-handoff.md`。
- 交接明确：Phase 5 仍 in_progress；Task 10 blocked/abandoned；知识导入/检索基础已有大量实现但真实 Docker ingestion/index/search 未闭环；自生长笔记/知识图谱/错题题库以及 Agent Loop/L0-L3 记忆仍未正式实现。
- 已保留现有 root 三份规划记录与 feature worktree 全部未提交改动；未重新运行测试或修改代码。

## 2026-08-19 DeepTutor 复用审查（只读初步结果）

- 用户提供本地源码：C:\Users\asus\Downloads\DeepTutor-main\DeepTutor-main，要求评估是否可以直接复制完成 Phase 5。
- 初步确认 DeepTutor 根项目为 Apache-2.0，并带有 THIRD_PARTY_NOTICES.md；其中至少记录 CSSwitch 的 MIT notice。不能无条件删除许可证、版权和第三方声明。
- DeepTutor 解析层（33 个 Python 文件）与 RAG 层（56 个 Python 文件）是本地文件/目录运行时，包含可选 Docling、MinerU、LlamaIndex、LightRAG、GraphRAG、PageIndex 等重型/外部后端；当前 API 依赖锁定为 FastAPI + SQLAlchemy + psycopg + Redis + MinIO 边界，没有这些依赖和目录运行时。
- DeepTutor 的 ParsedDocument/parser signature、embedding signature/index versioning、preflight 和 retriever 属于有价值的设计参考；但其持久化主要围绕 data/knowledge_bases/<kb>/version-* 文件目录或可选引擎存储，不能直接替换当前 knowledge_bases/documents/document_versions/pages/blocks/index_versions/chunks/ingestion_jobs 的不可变 SQL 模型。
- 当前项目已拥有 PDF/DOCX/Markdown/JPG/PNG/Obsidian Vault 解析、OCR、安全对象存储、版本化索引与引用基础；直接复制 DeepTutor parsing 会重复实现并绕开租户、对象存储和原页证据边界。
- Phase 5 第 3、4 项对应的 DeepTutor memory/notebook/question/agent 模块更接近可移植的业务算法和提示词参考，不是可直接粘贴的 FastAPI/SQLAlchemy 功能：其 memory 使用本地 Markdown/JSON L0-L3 目录，Question/Notebook/Agent 依赖 DeepTutor 自己的 orchestrator、stream bus、tool/capability registry、session SQLite、runtime workspace 和 provider factory。
- 结论暂定：**不能整目录复制或覆盖当前 pps/api**。可考虑在用户确认后，以 Apache-2.0 合规方式提取少量纯算法/协议思想，先映射到当前数据模型和权限服务，再写 focused tests；本轮尚未复制、修改业务代码或运行测试。

- 完成详细审查报告：E:\项目\知识库课本\.worktrees\platform-foundation\docs\superpowers\reviews\2026-08-19-deeptutor-phase5-reuse-review.md。结论：DeepTutor 可作为 Apache-2.0 合规的选择性来源，但没有可以安全地“整目录复制粘贴”进当前架构的 Phase 5 模块；解析/RAG 仅作参考，Notebook/Question/Memory 的概念需迁移到 SQL、多租户、来源可追溯模型。两名独立审查子代理均因服务端 429 Too Many Requests 未返回报告，后续源级复制前应重新获得独立复审。

## DeepTutor 全量 Phase 5 复用审阅（2026-08-20）

- DeepTutor 的 `learning`/`mastery` 不是论文专用能力，已包含诊断、讲解、Feynman 检查、练习、错误分类、掌握度、间隔复习、题目 pending 生命周期和中文课程提示词，和本产品课程辅导目标高度相关。
- 可优先迁移的不是整套代码，而是纯算法/策略：确定性评分、掌握度计算、下一目标选择、间隔复习、错误粗分类，以及标准答案隔离和服务端状态机约束。
- `learning/storage.py` 虽已改为 SQLite/CAS/lease，但仍是 DeepTutor workspace 聚合存储；它不能替代当前 PostgreSQL/SQLAlchemy、`space_id` 权限、MinIO、Redis/worker、不可变文档版本和 Provider/Billing。
- `book` 的 `Chapter/Page/Block`、partial/error/ready 状态、source anchor 和增量编译思想值得中后期参考；其 compiler、storage、retrieval 和 provider 不能直接复制。
- memory consolidator 的自然边界分块、行级编辑、引用回校验和 checkpoint 思路值得后续吸收；文件化 LLM 运行时必须改为多租户、可审计、异步 SQL 实现。
- `agentic_pipeline.py` 只能参考工具门控、上下文预算、暂停/恢复、服务端参数注入；直接复制会引入第二套 session/tool/stream/provider/usage runtime。
- Apache 2.0 允许在保留许可证/归属/专利声明和第三方 notices 的前提下派生，但本轮未复制源代码。任何复制前都要做许可证与依赖审计，并明确修改说明。
- DeepTutor 复用审阅不会替代 Task 10 的真实 ingestion/index/search/citation 验收；当前 Task 10 仍未完成，Phase 5 仍未完成。


## 2026-08-20 · Learning Foundation review finding

- A minimal pure Python learning-domain slice was added in the feature worktree only. It contains deterministic grading, mastery, review scheduling, and next-step policy; it has no database, API, provider, LLM, filesystem, Docker, or DeepTutor runtime dependency.
- Focused validation after repair: 30 passed; Ruff and focused `git diff --check` passed. The only test warning is a pre-existing `PytestCacheWarning` / `WinError 5` cache-write denial; no workaround was introduced.
- Independent SPEC review passed after one targeted correction.
- Independent QUALITY/SECURITY review did **not** pass: residual Minor issue is that `QuestionSpec(question_type=OPEN, expected_answer=<mutable non-string>)` can retain the caller object, so a frozen contract is not fully immutable on that unused field.
- This was explicitly judged the same frozen-container rule already corrected once; per the agreed one-correction stop rule, it is documented rather than repaired again. Treat this slice as an uncommitted partial foundation with a known quality exception, not a Phase 5 completion.

## 2026-08-20 20:16 · Question Bank Foundation Task 1 completed

- Added the minimal tenant-aware persistence schema only: questions, question_versions, and question_attempts, plus migration  009_question_bank_foundation from  008_embedding_contract and Alembic metadata import.
- Contracts now enforce KB/space composite ownership, immutable DocumentVersion anchoring, per-question version uniqueness, tenant-aware attempt links, and (user_id, question_version_id, request_key_hash) idempotency.
- Each version retains a chunk provenance *snapshot* only; it has no chunks foreign key or ORM relationship, so reindex worker cleanup remains independent.
- Focused red test initially confirmed missing 	utor_api.question_bank. Final focused verification: 11 passed; Ruff passed using a temporary cache; target diff check passed (only pre-existing env.py line-ending notice).
- Independent SPEC review passed after one formatting-only correction. Independent QUALITY/SECURITY review initially found ORM/migration JSON-vs-JSONB drift; one targeted correction aligned the ORM with the migration and added dialect-resolution regression coverage. Quality/security re-review: PASS, no P0/P1/P2 findings.
- No Docker/Compose, Alembic upgrade, full suite, coverage gate, staging, committing, reset, stash, or protected Task 10/Learning file modification occurred.
- Task 2 (safe author/read/attempt APIs) is next; Phase 5 remains in progress and Task 10 remains blocked/abandoned.

## 2026-08-20 · Question Bank Task 2 API findings

- A citation identifier is an opaque capability-like input: malformed, forged, cross-KB, inactive, and overlong tokens all use the same 404 behavior, after server-side signature and scoped-source validation. Rejecting a malformed token at schema level with 422 leaks an avoidable behavior distinction.
- Response DTO omission alone is not sufficient for efficient confidentiality boundaries: public list/detail queries should also defer private answer/rubric/provenance/identity columns, so large private fields are not loaded for ordinary student reads.
- Aggregate JSON input limits matter even when each element is bounded. Normalized expected keywords now cap both count (50) and total characters (4,096), and excess inputs are rejected before any Question write.
- The Question Bank Task 2 final evidence is `20 passed` focused tests plus targeted Ruff and diff checks; final independent SPEC and QUALITY/SECURITY reviews both passed.

## 2026-08-20 · Question Bank Task 3A review outcome

- Pure deterministic assessment implementation is functionally verified (20 focused tests, Ruff, whitespace check) and the independent specification review passed.
- `AssessmentResult` and `ReviewSchedule` construction invariants plus bounded `deque(maxlen=5)` mastery history are independently confirmed fixed.
- Residual P2: the AST test catches `from tutor_api.learning.grading import ...` but not `from tutor_api import learning`; current runtime imports remain standard library only.
- This is the same import-isolation rule after the one permitted correction. Record as `QUALITY/SECURITY FAIL / stop-rule`; do not apply a third fix or call the task fully approved.

## 2026-08-20 · Question Bank Task 3B review outcome

- Assessment schema function/spec evidence passed: composite tenancy/user/version/attempt FK, one assessment per attempt, deterministic scoring/mastery/review evidence, contract labels, additive migration, and 35 focused SQLite/offline-DDL tests.
- Current schema does not store answers, rubrics, keywords, request hashes, or source/provenance snapshots.
- Residual P2 is limited to regression coverage: the exact privacy column allowlist checks ORM metadata, not the physical migration-created column set. A migration-only future sensitive column could evade that guard.
- Stop-rule applies after the one targeted test correction; retain `QUALITY/SECURITY FAIL` for Task 3B and do not apply a third fix.

## 2026-08-20 · Question Bank Task 3C concurrency finding

- A unique idempotency key alone is not sufficient for derived learning evidence: concurrent different keys for the same user and question version can both observe the same prior mastery/streak state. A transaction-scoped serialization primitive must cover replay lookup, evidence read, derivation, and write.
- PostgreSQL `pg_advisory_xact_lock` keyed from the stable pair `(user_id, question_version_id)` is a narrow fit here when executed on the request's outer SQLAlchemy transaction; SQLite tests must bypass PostgreSQL-only lock SQL.
- Focused dialect-mocked tests can verify key scope and ordering, but they are not equivalent to a real PostgreSQL concurrent end-to-end test. That verification was not authorized or run.
## 2026-08-20 · Question Bank Task 4 owner review queue findings

### Accepted contract

- The review queue is a read-only current view, not a historical error archive: one latest assessment per question version, owner-scoped to the current user and knowledge-base space, and returned only when the latest evidence has `needs_review=true`.
- `scope=due` uses `review_due_at <= now(UTC)`. `limit` is bounded to 1..50 and pagination is keyset-based over `(review_due_at, assessment.created_at, assessment.id)` with `limit + 1` lookahead.
- The safe projection is enforced at both DTO and query levels. `load_only(...)` prevents ordinary review-queue reads from loading answers, rubrics, provenance, identities, request hashes, or internal assessment/attempt identifiers.

### Review outcome

- Independent SPEC review: **PASS**.
- Independent QUALITY/SECURITY review: **PASS**, no P0/P1/P2.
- Focused verification: `20 passed`; targeted Ruff and four-file diff check: **PASS**.
- Review record: `.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-20-question-bank-review-items-task4-review.md`.

### Boundary and next step

- No Docker/Compose, Alembic, full suite, coverage, real PostgreSQL concurrency/performance, or external-provider validation was run for this slice. Existing framework deprecation warnings are non-blocking.
- Task 4 is complete, but Phase 5 remains `in_progress`. Task 10 is still blocked/abandoned, and the Task 3A/3B P2 stop-rule records remain unchanged. The next capability must be separately scoped rather than reopening stopped work.
## 2026-08-21 · Question Bank Task 5 attempt-history plan

- Planned the next independent Phase 5 slice: a bounded owner-only read endpoint for all immutable assessment history of one question version.
- Scope is migration-free and read-only. It reuses readable knowledge-base authorization, filters by current user and tenant, uses `QuestionAttempt.created_at` for newest-first keyset pagination, and exposes only the already-approved safe assessment projection.
- It deliberately excludes answer keys, submitted answers, rubrics, provenance, identities, request hashes, Task 10, LLM/Agent work, and changes to `tutor_api.learning`.
- Plan: `.worktrees/platform-foundation/docs/superpowers/plans/2026-08-21-question-bank-attempt-history-plan.md`.
## 2026-08-21 · Question Bank Task 5 final findings

- `attempt-history` is deliberately distinct from Task 4’s review queue: it returns all immutable assessments for the current user/version rather than collapsing to the latest assessment.
- Public chronology must use `QuestionAttempt.created_at`; assessment creation time is not a substitute for when the learner attempted the question.
- Stable newest-first history pagination needs the full tuple `(attempted_at DESC, assessment.id DESC)` in both SQL ordering and cursor predicate. Equal timestamps are now covered with public `review_due_at` markers across two pages; no internal assessment ID is exposed in the response.
- Safe output requires both an explicit DTO/envelope and `load_only(...)` query projection. Selecting `QuestionAttempt.created_at` as a scalar avoids loading the attempt entity’s submitted answer and idempotency hash.
- Independent Task 5 reviews: SPEC PASS and QUALITY/SECURITY PASS, with no P0/P1. The only review qualification is procedural: ordinary `git diff --check` does not inspect untracked files. The controller used `git diff --no-index --check -- NUL <file>` and observed no whitespace diagnostics; this is whitespace evidence only, not a replacement for source/test review.
- Task 5 review record: `.worktrees/platform-foundation/docs/superpowers/reviews/2026-08-21-question-bank-attempt-history-task5-review.md`.

## 2026-08-21 · MVP 验收范围与止损规则

- 本期可向客户声明的范围是“带来源追溯的资料知识库 + 题库学习闭环 MVP”，不能将模型目录、哈希 embedding 或普通知识库搜索描述成真实 LLM 课程辅导 Agent。
- 真实 LLM Tutor 仍缺少已确认的 endpoint、密钥注入方式、模型名、协议和真实调用/计费验收；改为高级延期项，而不是隐性假设某供应商格式。
- 2026 年 8 月 19 日真实 Docker Task 10 失败仍有效：服务健康不等于资料已可检索。MVP Gate 允许一次证据驱动定位和至多一次狭窄修复；若仍失败，停止反复调参并把该路径写为客户可见 FAIL/限制。
- 题库 Task 3A/3B 和 Learning Foundation 已有冻结 stop-rule 限制保持不变；Task 5 已完成且不重新实现。用户接受 coverage `89.41%` 的例外，不能替代端到端真实证据。
- 为减少低价值流程成本，三个耦合 MVP 工作项合并后只进行一次集中验证、一次 SPEC 审查、一次 QUALITY/SECURITY 审查；安全、权限、来源、私密字段、幂等与事务一致性仍不可省略。

## 2026-08-21 · 独立 MVP 审计发现

- 知识库页面已有创建、上传、搜索和 citation 预览交互；题库端点已注册，但工作台中的“题库/错题集”仍是静态树项，学习者无法在 UI 完成作答—反馈—复习—历史闭环。
- “AI 家教”目前没有提交行为、Tutor/Agent API、LLM client 或真实费用结算。若本期不接入真实 LLM，必须将其隐藏或重命名为资料检索/题库练习，不能保留可误解的模型、费用和回答承诺。
- 上传返回“处理中”后，前端缺少明确状态刷新/轮询，客户无法确认是否已真正可检索；这应作为 MVP 主链路项而非界面美化项。

## 2026-08-21 · MVP 收口执行阻塞（非项目环境）

- 合并 MVP 批次的唯一实现子代理在写入 CSS/测试收尾时被执行平台拒绝，返回 `403 Forbidden：预扣费额度失败`。该限制与 Docker、Compose、PostgreSQL、API key、LLM、OCR、embedding 或本机硬件无关。
- 因已有 partial changes 且 focused tests 仍为 18/21，当前不得作出 MVP 实现完成、集中验证通过、SPEC PASS、QUALITY/SECURITY PASS 或 Phase 6 可验收的任何声明。
- 恢复条件是 Codex 执行额度可用；恢复后应复用同一实现子代理继续其明确收尾，不扩大范围、不切换为 controller 手工重做，也不重新运行历史 Docker/Task 10 验收。

## 2026-08-21 · MVP 收口批次完成后的规格修正

- 前一条“执行额度阻塞、18/21 失败”的记录是过程日志，已被后续事实 supersede：实现收尾已完成，21/21 focused tests、目标 ESLint、无增量 TypeScript 检查均通过。
- MVP 本期承诺的是题库 UI 的最近答题历史；完整历史分页 UI 不作为客户首付款验收阻塞项。后端 pagination contract 保留。
- 上传接口的兼容字段仍可能到达浏览器，但 UI 不读取/显示；安全 status endpoint 是唯一学习者处理状态来源。完整 DTO 最小化作为后续契约优化登记，不构成本期泄密证据。
- SPEC 初审的 P1 记录不一致已修正；P2 项已通过明确范围和延期记录处理。等待复审与 QUALITY/SECURITY 审查。

## 2026-08-21 · MVP 复审后的真实阻断项

- 规格复审确认本期客户口径为“带来源追溯的资料知识库 + 题库学习闭环 MVP”；完整答题历史分页 UI、真实 LLM Tutor、知识图谱、长期记忆、多 Agent、生成式题目、教师分析、性能压测和非关键 coverage 均延期。
- 质量/安全复审确认没有跨租户越权或学习者私密答案泄露，但上传 POST 响应仍将 `ingestion_job_id`、`content_sha256`、`job_state` 及无必要空间/内部状态字段发给浏览器，属于本次必须收紧的 P1。
- 前端存在可复现的取消竞态：题库切题/切换知识库时旧提交或历史请求可能污染新题目，取消后 loading 可能卡死；资料状态刷新不同条目时共享 controller 可能令前一条永久显示刷新中；答题网络重试没有复用同一 Idempotency-Key。
- 修复原则：只做契约和状态管理的窄改动，保留既有未提交文件，不重做已完成任务；修复后只做目标 focused tests、lint/typecheck 和独立窄复审。

## 2026-08-21 · MVP 窄复审最终结论

- 最终独立窄复审 PASS：P0=0、P1=0、P2=0。
- 上传 POST 与前端 DTO 现在只暴露 `document_id`、`document_version_id`、`source_name`、`created_at`；处理状态单独通过授权 status endpoint 获取。
- 题库幂等键绑定到知识库、题目版本和规范化答案；提交成功但 review-items 刷新失败时保留评估、答案和 key，避免重复答题；修改答案、切题或切换知识库时生成新 key。
- 本结论只覆盖代码合同和 focused 回归，不代表 Docker/PostgreSQL/pgvector、Alembic、全量测试、外部 OCR/Embedding/LLM 已通过。2026-08-19 真实 Docker 资料链路失败事实仍有效。

## 2026-08-21 · Phase 6 环境阻塞事实

- 尝试启动真实隔离验收前，当前 PowerShell 执行 `docker version --format '{{.Server.Version}}'` 失败，提示 `docker` 不可解析。
- 本次没有自行安装、搜索、修改 PATH、启动 Docker Desktop、运行 Compose 或清理数据卷；没有新增任何真实链路结论。
- 要继续 Phase 6，只需要一个可用入口：Docker Desktop 引擎已就绪且当前终端能解析 `docker`，或 Docker CLI 的准确可执行路径/远程 Compose 入口。API key 不是本 Gate 的前置条件：默认知识处理链路使用本地/禁用外部 provider 配置，真实 LLM Tutor 仍延期。

## 2026-08-21 · Phase 6 真实资料 Gate 失败证据

### 环境

- Compose project：`mvp-phase6-20260821`
- Docker Server：`29.7.2`
- Docker Compose：`v5.3.1`
- Alembic：`0010_question_attempt_assessment (head)`
- 服务：postgres/pgvector、redis、minio、api、worker、web 均已启动；api 与 web healthy。

### 真实链路结果

| 步骤 | 结果 |
|---|---|
| 注册临时用户 | PASS |
| 创建个人知识库 | PASS |
| 上传唯一 token 的 Markdown | PASS，HTTP 201 |
| 状态观察 | `processing` → `failed` |
| `parse_document` | `completed` |
| `build_index` | `failed`，3/3 次尝试 |
| 失败码 | `index_validation_failed` |
| 观察到的页/块 | `pages=1`，`chunks=0` |
| 搜索唯一 token | 未执行为 PASS；索引失败后无合法检索前提 |
| citation/source/page preview | 未执行为 PASS；无搜索 citation |

### 决策

这是 2026-08-19 失败事实之后的新鲜隔离复验，仍在索引校验层失败。按项目 stop-rule，当前不做第三轮无证据调参；真实 PostgreSQL/pgvector 资料导入、检索和来源预览不宣称通过。若客户要求无条件资料检索 MVP，需要单独授权一次有根因假设和最小修复；否则本期交付口径收缩为“代码复审通过的知识库/题库 API 与 UI + 资料上传/状态可见化”，资料检索端到端列为已知阻塞。

## 2026-08-21 · Phase 6 一次性索引修复结果

- 逐字段诊断中唯一不一致项是 embedding：持久化值与期望值是同一 PostgreSQL float4，但 Python float64 文本表示不同；其他 ordinal、租户/版本/页块/source pointer/content hash、lexical terms、dimension、signature 均一致。
- 已实施且通过独立窄验证的唯一修复：将 embedding 比较改为 float4 32-bit 位模式比较，避免相对容差，并显式拒绝 signed-zero 位模式不一致、NaN/Inf、overflow、类型异常和长度不一致。
- stop-rule 仍生效：真实 Docker Gate 只允许在代码修复后重验一次；若重验仍失败，保留 FAIL，不再无依据反复调参。
- 当前新会话的 `docker` 不可解析，因此真实重验尚未开始；不得把本次代码测试 PASS 写成资料检索端到端 PASS。

## 2026-08-21 · Phase 6 真实资料 Gate 修复后 PASS

- 修复后的唯一真实重验已通过：重建 api/worker 后，新资料成功完成解析、索引构建和可检索状态转换。
- 证据：`processing → searchable`；唯一 token 搜索返回 1 条；citation source/page 两个预览端点均返回 HTTP 206，内容类型分别为 `text/markdown; charset=utf-8` 与 `text/plain; charset=utf-8`。
- 先前一次上传请求返回“不支持的文件类型”是验收脚本 multipart 文件部件未声明 `text/markdown`，未进入解析/索引，不计为产品 Gate 失败；随后使用明确 MIME 的请求完成同一验收。
- 旧环境与修复前环境的索引失败记录仍不可删除，但已被本次有根因修复后的新鲜实证 supersede 为当前 Gate PASS。
- MVP 可以进入客户验收/资金节点；高级能力按既定清单延期，不因本次 PASS 扩大承诺范围。

## 2026-08-30 · Faro 健康不等于 AI 组件健康

- `.env` 的 Faro base URL、key、模型和 runtime 配置存在且基础连接可用，但这不能证明组件成功。
- AI 助教独立根因：前端把 `state=failed` 的 Faro 会话仍视为可写，URL/localStorage/最近会话会反复恢复失败会话。
- 知识候选独立根因一：Gemini 实际可返回 `formula_verification: []` 或多个校验对象的列表，旧解析器只接受单对象/null。
- 知识候选独立根因二：同一个 canonical key 会在不同上下文块生成互补 markdown/公式/来源，旧合并器要求完全一致并抛出 `candidate_note_conflict`。
- 可观测性问题：`CandidateValidationError` 的稳定码存放在异常消息前缀，Worker 原实现只读取 `.code`，导致真实错误被降级为 `worker_unhandled_error`。
- 修复后真实 AI 助教链路：AgentPanel/API → Agent Runtime → Faro → Gemini → `model_text_delta`，最终 runtime=completed、session=waiting_input、无 error event。
- 修复后真实知识候选链路：Worker → Faro/Gemini → 结构/候选解析 → 跨块合并 → DB；任务 `1cc3f623-2eb6-489a-a4f2-ea613a7fac88` completed（6/6），批次 `fca98b9e-5130-4f7a-80e8-aa9130b47dd1` needs_review，29 notes，failure_code 为空。

## 2026-08-30 · UI 503 的第二层根因

- 直接调用 API:8000 的 smoke 会成功，但 UI 通过 Web:3100 反向代理时，请求到达 API 的 Host 是 Docker 内部 `web:3000`。
- `post_turn` 原先用 `request.url_for("runtime_event_callback")` 构造 callback，导致 Runtime 收到 `http://web:3000/api/v1/agent/runtime/events`。
- Agent Runtime 是宿主机 Node 进程，不能解析 Docker Compose 内部 DNS 名 `web`；它虽然 Faro 调用成功并建立 sequence=0 的 Runtime session，但首个事件无法回调 API，API 的 RuntimeClient 30 秒后将请求映射为 `503 runtime_unavailable`。
- 这解释了“Faro health 正常、直接 API smoke 正常，但 UI AI 助教失败”的表面矛盾。
- 修复后 callback 来自可信环境配置而非不可信/不可达的代理 Host。

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

## 2026-08-30 · AI 助教 UUID / 消息正文 / 上下文合同排查

- 输入框上方 `86d77e8b-74d0-4fea-ba1f-82f24a9c35e0` 已由数据库确认是知识库 `wire sign` 的 `knowledge_bases.id`，不是文件名、文件 ID 或会话 ID。
- Web 默认上下文只提供 `knowledge_base_id`，Composer 又把该 ID 当展示兜底，因此内部 UUID 泄露；整库关联应显示 `知识库：wire sign`，具体文件关联才显示文件名。
- Runtime 的 Faro Provider 发出 `user_message.payload.message`，Web reducer 只读 `payload.text`，导致页面只显示角色“你”而正文为空；数据库已证明用户输入完整保存。
- 前端虽发送 `linked_contexts`，API `TurnCreateRequest` 未声明该字段，当前会被 Pydantic 静默忽略；关联知识库目前没有真正注入 Runtime。
- Faro 空响应发生在 HTTP/JSON 成功后提取 `choices[0].message.content` 阶段；需安全记录 finish_reason/message keys 等结构摘要，并修正 Gemini 3.7 不应携带的废弃 sampling 参数。

## 2026-08-30 真实页面验收补充
- UUID `86d77e8b-74d0-4fea-ba1f-82f24a9c35e0` 经数据库确认对应知识库 `wire sign`，不是文件名。
- 修复后的 Composer 不再把内部 `knowledge_base_id` / `vault_file_id` 作为可见标签；默认显示 `知识库：<名称>`。
- 重建 Web/API 并重启 Faro Runtime 后，真实页面显示 `知识库：Faro 真实链路验收` 与 `已连接 · cursor 12`。
- 真实检索注入能让 Faro 根据 `wireless-faro-e2e.md` / `browser-faro-candidate.md` 回答路径损耗、信噪比和误码率关系。
- E2E 发现检索上下文曾被拼进用户气泡；已将 Faro 可见 `user_message` 限定为首个文本块，同时仍向模型发送完整检索上下文。
- 数据库最新事件序列 9-12 为 `turn_started → user_message → model_text_delta → session_state(completed)`，其中 user_message 仅保存原始提问。

## 2026-08-30 · qyw211 选择性接入边界

- qyw211 的 c53f459 是大杂糅提交，直接 merge/cherry-pick 会覆盖当前 Faro、知识库和工作台修复；本轮只选择性移植 billing、account-panel、welcome。
- 当前稳定数据库 head 为 0018_object_deletion_outbox；qyw 分支使用 0016/0017/0018/0019，不能直接复制迁移文件，必须新建从 0018 继承的支付迁移。
- 当前前端没有 qrcode 依赖；账户面板需要 qrcode 与类型包，依赖锁文件应通过 pnpm 生成而非复制 qyw 的整份锁文件。

## 2026-08-30 · qyw211 支付选择性接入最终审计

- qyw211 支付代码未整体合并，避免将 AI 助教、知识库、题库和工作台改动带入当前工作树。
- 支付入口统一经过 billing service；线上通知只在签名/字段/金额校验后调用现有人工充值入账路径，避免另建余额逻辑。重复通知可幂等处理，金额不匹配进入 `paid_mismatch` 且不入账。
- 0019 迁移显式声明 `mock/alipay/wechat` 与订单状态约束，并关闭 SQLAlchemy 非原生 Enum 的自动 CHECK 生成，避免重复 `payment_provider_kind` 约束。
- 完整 API 测试唯一失败：`tests/test_knowledge_worker.py::test_compose_worker_reuses_api_image_without_ports_or_root`，原因是当前未提交的支付配置已加入 API 环境而 `compose.yaml` 的 worker 环境尚未同步；本轮禁止覆盖/修改 `compose.yaml`，因此未将该失败伪装成支付代码问题。

## 2026-08-30 · 支付/账户/欢迎页选择性接入结论

- qyw211 提交 `c53f459` 是 AI 助教、知识库、题库、支付和 UI 的混合提交，不能整体合并；本轮采取白名单移植。
- 支付实现复用当前钱包账本和人工充值/冲正服务，新增充值订单和网关适配层。默认 `PAYMENT_PROVIDER=mock`，无真实支付宝/微信凭据时应用仍可启动。
- 数据库采用新迁移 `0019_recharge_orders_payment`，父迁移固定为当前稳定 head `0018_object_deletion_outbox`，没有引入 qyw 的冲突编号。
- Web 只加入独立账户面板、二维码依赖、欢迎页和一个账户入口；AI 助教、知识库检索、候选生成、Agent Runtime 和现有工作台核心文件未被 qyw 改动覆盖。
- 全量 API 测试首次发现 Compose worker 未同步新支付环境变量，已补齐 api/worker 环境后回归通过；这是配置一致性修复，不涉及 AI/知识库逻辑。
- 当前变更具备提交条件；推送前仍需确保仅显式 stage 白名单文件，排除 `.env`、`.tmp/` 和任何临时检查产物。
