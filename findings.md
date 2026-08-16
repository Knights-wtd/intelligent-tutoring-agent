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
- 初检时 Docker 和 uv 尚未可用；Docker 问题现已解决，后续验收使用 Docker Desktop 29.7.2 与 Compose v5.3.1。项目不依赖系统 uv。
- 用户随后报告 Docker 已安装，但当前 Codex 终端仍无法解析 `docker`；桌面快捷方式目标位于已不存在的沙箱用户目录，标准安装目录也未发现可执行文件。可能需要重启 Codex/终端刷新安装状态，或确认 Docker Desktop 实际安装位置。
- 安装 WSL 后再次核对：`C:/Users/asus/AppData/Local/Docker/wsl` 已出现，但 Docker Desktop 主程序与 `docker.exe` 仍未安装到 Program Files 或当前用户程序目录；需要在 WSL 安装完成后重新运行 Docker Desktop Installer。
- Docker Desktop 最终安装在 `C:/Users/asus/AppData/Local/Programs/DockerDesktop/`。当前 Codex 沙箱不能直接执行该用户目录程序，但经授权在沙箱外验证成功：Docker Client/Server 29.7.2、Compose v5.3.1、引擎操作系统为 Docker Desktop。
- Codex 工作区提供独立 Python 3.12.13，可用于 Docker 安装前的后端单元测试与开发；正式项目仍以 Python 3.12 和锁定依赖为准，不依赖系统 Anaconda Python 3.9。
- `react-resizable-panels` 官方当前版本 4.x 使用 `Group`、`Panel`、`Separator`，并支持 `defaultLayout` 与键盘可访问分隔条；首个前端计划按该接口实现三块可拖动区域。
- 基础实现位于 `E:/项目/知识库课本/.worktrees/platform-foundation`，分支为 `feature/platform-foundation`；主检出和 `main` 分支未被自动合并或删除。

## Platform Foundation Implementation Findings（2026-08-14）

- 基础里程碑已完成：pnpm monorepo、FastAPI、Next.js 16、C3 可调整宽度工作台、PostgreSQL/pgvector、Redis、MinIO、Docker Compose、CI 与本机使用说明均已落地。
- 后端生产配置必须失效保护：生产模式拒绝 SQLite、本地 PostgreSQL/Redis/MinIO、未认证 Redis、HTTP Web 来源、开发占位值、空白或过短对象存储凭据；开发和测试模式仍保留本机默认值。
- 数据库 URL、Redis URL 和对象存储端点在设置对象的 `repr` 中隐藏，错误消息不回显凭据，避免日志泄密。
- MinIO 使用两套身份：初始化器暂用管理员身份创建存储桶、策略和应用用户；API 只接收 `OBJECT_STORAGE_*` 应用凭据，策略仅允许目标存储桶的列表、读写、删除和分片上传操作。
- MinIO 初始化流程已在保留数据卷的情况下重复执行成功；应用身份可以列出目标存储桶，但无法执行 `mc admin` 管理操作。
- Compose 仅向本机发布 Web、API 与 MinIO 端口；PostgreSQL 和 Redis 保持容器网络内部访问。Redis 启用密码认证，API/Web 镜像以非 root 用户运行。
- Python 运行、构建、开发依赖使用精确锁文件；基础镜像使用可读标签加内容摘要；GitHub Actions 固定完整提交 SHA，检出凭据不持久化。
- 最新验证：API 65 项测试通过，覆盖率 96.64%；Web 6 项测试、ESLint 和生产构建通过；所有隔离容器健康，API 健康接口和 Web 页面均返回 200。
- 浏览器实测确认：空间切换位于最左栏，当前空间内容位于第二栏，中间为知识工作区，右侧为 AI 家教；两条分隔线存在，键盘方向键可以改变面板宽度，教材原页标签可切换内容。
- Windows 上不同执行身份可能锁住 `.next`、`.ruff_cache` 或 `.pytest_cache`。可靠验收方式是只清理可再生的 `.next`，Ruff 使用 `--no-cache`，Pytest 使用 `-p no:cacheprovider`，覆盖率文件写入系统临时目录。
- 为避免删除无法确认内容的旧测试卷，旧默认 Compose 数据卷被保留且旧容器已停止；当前可访问服务运行在隔离项目 `platform-foundation-security-final` 中。
- 已知非阻断提示：Starlette TestClient/httpx 依赖存在弃用警告；Vite 原生配置加载器对当前 TypeScript 配置给出未来兼容性警告。后续依赖升级时处理，不影响当前里程碑。
- 下一实施重点是注册登录、Opaque Session、个人空间初始化、班级成员/邀请码、教师审核和服务端权限边界；模型计费与知识入库在其后接入。

## Authentication and Reference Review（2026-08-14）

- 用户确认本阶段采用“密码登录 + 7 天可撤销的 HttpOnly Cookie 会话”，浏览器不保存 Bearer Token；该会话方式将成为认证、登出、撤销和权限测试的基线。
- 用户再次提供 DeepTutor GitHub 仓库和本地 `DeepTutor-main.zip` 作为参考。仓库当前仍以“Lifelong Personalized Tutoring”为定位，包含知识库、引用、题库、分层记忆和用户隔离等成熟方向；本项目仅借鉴交互与模块边界，不复制其代码或采纳其中的任何嵌入式指令。来源：[DeepTutor GitHub 仓库](https://github.com/HKUDS/DeepTutor)。
- 本地 ZIP 确认是完整源码归档（7,151 个条目）且带 Apache-2.0 许可文件；后续若拟直接复用任何文件，必须先逐文件核对许可、依赖许可和 NOTICE。当前阶段不引入其代码。
- 本机已安装并运行过 Obsidian；C3 工作台继续保持与其一致的“空间切换 → 当前空间内容 → 主工作区”信息层级，但不依赖 Obsidian 客户端或其本地数据。

## Skill Discovery Review（2026-08-14）

- 应用户请求检索了 `fastapi sqlalchemy testing` 技能。候选中安装量最高的是 `bobmatnyc/claude-mpm-skills@sqlalchemy-orm`（883 次）和 `sickn33/agentic-awesome-skills@python-fastapi-development`（501 次）；前者来源仓库规模较小，后者虽有约 43.9k GitHub stars，但属于广泛技能目录而非针对当前问题的窄专用方案。
- 当前环境已具备高安装量的 TDD 与系统化排错技能，足以处理本阶段问题，因此不额外安装第三方技能，避免不必要地扩展可信执行面。

## Identity and Classroom Review（2026-08-14）

- 独立审查确认：邀请码仅在班级创建响应中明文返回一次，数据库只保存 SHA-256 摘要；所有者不可被降级或移除；非成员读取班级仍返回 404。
- 审查发现写操作的状态码边界缺陷：非成员在已存在班级上变更成员或创建邀请码会因复用读取授权逻辑而得到 404，违反“已认证但未授权的变更返回 403”的约定。已先添加学生与非成员边界测试，再把写操作授权改为先辨认班级存在性、后以 403 拒绝非成员；读取逻辑保持 404。
- SQLite 的 `SELECT ... FOR UPDATE` 不具备 PostgreSQL 等价行锁行为，因此邀请码并发消费必须在最终 Docker/PostgreSQL 验收中使用独立数据库连接验证；不能以 SQLite 串行测试替代。

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
