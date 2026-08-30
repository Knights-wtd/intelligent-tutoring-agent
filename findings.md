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

## 2026-08-18 Phase 5 · Task 7 关键结论

### 最终状态、提交与审查

- Task 7「immutable indexing and reliable worker」在代码 HEAD `363f3fb` final PASS；Phase 5 / Milestone 3 继续保持 `in_progress`。
- 交付提交依次为：`f298eb2 feat: build knowledge indexes reliably`、`96a3ad6 fix: close reliable indexing gaps`、`53284ca fix: harden reliable indexing delivery`、`cfc6220 fix: serialize ready index snapshots`、`0d34b2a fix: requeue changed embedding contracts`、`363f3fb fix(api): allow blank OCR pages`。
- `0d34b2a` 时的独立规格复审 PASS。初始独立质量复审 FAIL 报告两项：production-HTTP 项经只读核查证伪，因为 `config.py` 的 production gate 已要求 nonlocal storage 使用 HTTPS；blank OCR page 项有效，并由 `363f3fb` 修复。
- 修复后独立规格复审 PASS，reviewer 运行 34 focused passed；修复后独立质量复审 PASS。

### 已确认的索引、激活与合同边界

- 每个 build target 不可变，并绑定实际 embedding backend/model/dimension/signature 合同，防止构建过程中配置漂移静默混入同一 index version。
- chunking 感知 heading，同时严格限制 chunk 大小与 overlap；内容与合同完全一致时按 hash 精确复用，避免近似或跨合同误复用。
- building index 下持久化 source page/block pointers、lexical terms、embedding vectors、backend/model/dimension/signature 与内容 hashes，为后续混合检索和可追溯引用保留完整元数据。
- 校验与 activation 在同一事务内完成；replacement 未成功前旧 active index 保持可用，失败构建不能提前 supersede 当前 active。
- READY snapshot 使用 knowledge-base lock ordering 串行化，避免并发 READY 文档集合产生不可重复快照或锁顺序反转。
- adapter contract drift 会把旧的未激活 target terminalize，并幂等创建或复用绑定当前合同的 replacement job；重复恢复不会制造无限 replacement 或错误激活旧合同。

### 已确认的 worker、存储、解析与 OCR 边界

- job claim 使用 database lease 与 PostgreSQL `FOR UPDATE SKIP LOCKED`；覆盖 stale recovery、bounded retry、restart-safe processing 与重复启动不产生重复成果。worker 由 Compose 使用与 API 相同的镜像运行。
- S3 adapter 对对象大小和 redirect 次数设界，并拒绝不安全跳转；production 的 nonlocal storage 由配置 gate 强制 HTTPS。bounded PUT 当前最多会缓冲到配置的最大对象大小。
- parse lifecycle 持久化 terminal state、started/completed timestamps 和稳定错误状态，避免 job 已终止但 document/version 仍表现为处理中。
- OCR 路径继续 fail-closed。`363f3fb` 只放宽一种有效情况：completed OCR page 可为空，但仅当整份 document 仍保留内容；整份文档为空或 OCR 未完成时仍失败关闭。
- 非阻塞并发成本：当前 transaction/job lock 会在长时间 external handler 执行期间保持，可能扩大锁占用时间，但独立质量复审未将其列为 Task 7 阻塞项。

### 验证与未覆盖范围

- 最终主线程组合验证在 `363f3fb` 后运行 `test_knowledge_indexing.py test_knowledge_worker.py test_knowledge_adapters.py test_knowledge_uploads.py test_knowledge_parsers.py test_knowledge_ocr.py test_config.py test_compose_security.py`：362 passed、36 warnings。
- migration nodes：3 passed、4 warnings。targeted Ruff：all checks passed。`git diff --check aa71123..HEAD`：pass。
- 历史 Windows OCR combined run 曾出现精确两个 1 秒 PID-file timing failures；精确两项测试与完整 OCR 文件分别通过，最终 362 项 combined focused run 也通过。质量 reviewer 将其记录为非阻塞 timing observation，而非 Task 7 correctness failure。
- 未运行 Task 7 变更后的完整 API suite；未运行 Docker、真实 PostgreSQL/pgvector、MinIO/S3、Redis、真实 Tesseract/PDFium corpus、external services 或 live POSIX process group。
- 下一步是 Task 8「hybrid retrieval and secure source preview」；本次不开始 Task 8，也不创建最终 handoff。

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
## 2026-08-18 · Task 10 verification findings

- The supported upload set is `.pdf`, `.docx`, `.md`, `.jpg`, `.jpeg`, `.png`, and `.zip` (Obsidian Vault). Parser tests deterministically construct valid PDF, DOCX, Markdown, JPEG, PNG, and ZIP inputs; upload tests parameterize every accepted extension, including both JPEG suffixes. There are no checked-in binary fixture files.
- Effective defaults are bounded: 100 MiB per knowledge upload, 5,000 Vault members, 500 MiB uncompressed Vault content, disabled-only OCR, and deterministic `hash / feature-hash-v1 / 384` embeddings (dimension validation range 8–4096). No remote OCR, embedding, or model provider is configured. Compose currently relies on these application defaults and does not forward arbitrary knowledge override variables.
- `pnpm test:web` passed (7 files / 34 tests), `pnpm lint:web` passed, and the production `pnpm build:web` passed when run outside the sandbox that denied `.next\trace` writes. API `ruff check --no-cache src tests` passed; its default cache location was not writable in this environment.
- Full API coverage was executed with `COVERAGE_FILE` redirected to `%TEMP%` and pytest cache disabled. Result: 590 passed, 3 skipped, 2 failed, total coverage 88.08% versus required 90%. Both failures were `test_tesseract_timeout_kills_descendant_holding_pipes` and `test_tesseract_timeout_kills_descendant_inheriting_only_stdin`, where a Windows helper did not create its PID file within one second. The same OCR module alone passed 49 tests without coverage; this is an observed suite/timing failure, not a product-code fix made during Task 10.
- Docker CLI/Desktop, `psql`, `pg_isready`, and `initdb` were absent on 2026-08-18. `alembic heads` resolved `0008_embedding_contract (head)`, but no real PostgreSQL/pgvector migration round-trip or Compose register/upload/search/cited-page vertical slice could run. These are completion blockers; do not mark Milestone 3 / Phase 5 complete.

## 2026-08-21 · MVP 主链路收口实现前核对

- 已核对 question-bank 已有安全端点：题目列表、尝试提交、review-items、attempt-history；当前 Web 没有题库 client/panel。
- 已核对知识库上传响应仅是即时状态，缺少后续受 read 权限保护的 document/version 状态读取。新增 DTO 必须只含 document_id、document_version_id、processing_state。
- `searchable` 不能根据 `DocumentVersionState.READY` 伪断言；Task 10 在 2026-08-19 的容器验收仍然 failed / results=0。实现将只认可 active index 内含该版本 chunk 的证据，或显示 processing/failed，不修 Docker 根因。
- WorkspaceShell 仍请求模型目录和余额并渲染不可提交 AI 家教壳；本批将删除这些承诺，保持检索和题库学习定位。
## 2026-08-21 · MVP 复审窄修复事实

- 上传成功响应的允许集合固定为 `document_id`、`document_version_id`、`source_name`、`created_at`；处理状态不从 upload response 推导，而是读取已经授权并只返回公开状态的 status endpoint。
- 同一个 `AbortController` 不能安全管理多个资料条目的刷新：取消第二项会使第一项的 `finally` 跳过 loading 清理。按条目 ID 持有 controller，并通过 identity 判断其 `finally`，可同时处理多个刷新且不会由过期请求覆盖新状态。
- 对答题网络重试，幂等键需要绑定到 `(knowledgeBaseId, questionVersionId, normalizedAnswer)` 生命周期；只有问题、知识库或答案更改时才失效。旧请求在题目/知识库切换时必须同时取消并使 sequence 失效，且边界处立即恢复按钮 loading 状态。

## 2026-08-21 · MVP 幂等键生命周期窄修复

- `submitAttempt` 成功不代表整个 UI 成功流程完成；只有随后 `listReviewItems` 成功，才清空答案和幂等键。
- review 刷新失败时必须保留原答案/key，并将错误归因于刷新阶段；否则用户重试同一答案会生成新 key，可能造成重复答题记录。

## 2026-08-21 · 工作台视觉接入发现

- 原型 `workspace-c3-space-navigation.html` 是独立的高保真静态 HTML；此前的 React `WorkspaceShell` 只保留了 MVP 功能壳，两者没有真正连接。
- 视觉迁移应只迁移已承诺的结构与样式；原型中的真实 LLM、模型选择、余额、费用、长期记忆和知识图谱内容不能作为当前产品功能继续展示。
- 当前 React 实现已经恢复 Obsidian 风格的三栏工作台骨架，并把真实知识库/题库功能保留在中心区域。

## 2026-08-21 · 浏览器预览发现

- `http://localhost:3000/` 未登录时进入 `AuthForm`，不是 `WorkspaceShell`；原先看到的白底裸文字来自认证组件缺少 CSS，并非工作台样式加载失败。
- 为避免用户在进入工作台前看到原生 HTML，认证入口现在使用独立 CSS module；登录/注册语义和 API 行为保持不变。

## 2026-08-21 · 注册失败根因

- 注册失败不是用户名或密码校验首先触发，而是本地运行时缺少 API 服务且 Web client 未使用已配置的 API origin；浏览器请求记录为 `POST /api/v1/auth/register` 命中 Next.js 并返回 404。
- 修复后 API 服务运行在 `127.0.0.1:8000`，Web 通过 `NEXT_PUBLIC_API_BASE_URL` 发请求。注册时仍需满足：有效邮箱、用户名 3–32 位且只含字母/数字/下划线/连字符、密码长度至少 12 位。

## 2026-08-21 · 旧 Worker 更新事实

- 旧 Worker 由 Compose 项目 `mvp-phase6-20260821` 管理，配置文件是当前 worktree 的 `compose.yaml`，环境文件是 `.env.identity-test`。
- 它已运行约 8 小时，使用旧 API 镜像；当前 Worker 命令为 `python -m tutor_api.worker_main`。
- 使用 Compose build/up 完成镜像重建和容器替换；没有删除任何数据卷。

## 2026-08-21 · 注册失败第二次修复事实

- API 的最近日志只有健康检查，没有 `POST /api/v1/auth/register`，说明页面请求没有发到 API。
- `mvp-phase6-20260821-web-1` 创建时间明显早于当前配置；重建 Web 后，构建产物中已包含 `localhost:8010`，页面和容器健康检查均正常。

## 2026-08-22 · 注册链路根因

- 后端注册实现和数据库事务本身可用；既有 API 测试通过，真实经同源代理提交后也返回 201。
- 长期故障点是浏览器端编译期 API origin：它将部署端口固化进静态资源，运行时配置无法修正，旧镜像因此持续请求错误端口。
- 将跨组件地址留在服务器运行时，并让浏览器只访问同源 `/api/...`，同时消除了旧镜像端口漂移、CORS 和跨端口 Cookie 链路的不稳定性。

## 2026-08-22 · 注册 422 根因

- 该次失败已经穿过 Web 同源代理到达 API，响应码为 422；链路修复有效。
- 前端此前未公开或预校验后端的密码最小长度 12，导致用户只能看到统一失败提示。
- 前端规则与后端一致后，短密码不再产生 API 请求，并给出可操作的中文错误。

## 2026-08-22 · 工作台裸控件根因与功能映射

- `KnowledgePanel` 和 `QuestionBankPanel` 共用 `workspace-shell.module.css`。工作台视觉迁移后，组件仍引用的 19 个类均不存在，因此 `className` 解析为空；这不是后端返回缺失，也不是按钮 DOM 缺失。
- 知识库主链路已连接 API：列表、创建、上传、处理状态、检索和来源预览；题库学习者链路已连接题目列表、答题评估、待复习项和个人历史。
- 后端 `POST /api/v1/knowledge-bases/{id}/questions` 已存在，但当前 Web 没有教师/作者出题入口。
- 工作台外壳有 7 个静态原型控件没有 `onClick` 或提交行为；它们不应被算作已交付功能，后续应接真实交互或明确禁用/移除。

## 2026-08-22 · 浅色工作台排版事实

- 浅色模式通过语义 token 集中在 `WorkspaceShell` 的 CSS Module 中，避免在 JSX 中散布颜色逻辑；柔紫和薄荷绿分别承担选择/主操作与健康/连接状态。
- `react-resizable-panels` 的 `Panel` class 会落在内部 slot，窄屏收起时需结合 `[data-panel]:has(...)` 隐藏其外层 panel，才可真正为中心内容回收宽度。
- 本地 Windows `npm run build` 受 `.next/trace-build` 文件锁阻塞，但同一代码在干净 Docker build 环境完成了编译、类型检查和静态生成；该锁定是本地生成目录问题，不是应用构建错误。

## 2026-08-22 · LLM Markdown 导入设计事实

- 用户选择 B：Word/PDF/图片全文由 LLM 整理为 Markdown，而不是只做标题/摘要增强。
- 原始文件、解析块和生成 Markdown 必须分离；生成结果先是草稿，用户确认后才能进入正式知识库。
- 章节长短不是有效性指标。长文只按 Faro 模型上下文窗口分块；短文也应正常通过。异常检查限制为空响应、明显截断、模型错误文本混入等。
- Obsidian 双向链接由确定性 `[[笔记名]]` 解析器建立，支持反向链接和未解析链接；LLM 的自动链接建议不直接写入正式关系。
- Faro 教程只确认 OpenAI 兼容聊天接口和 Gemini 生成接口，未确认 embedding 接口；本计划不假设 Faro 能提供向量模型。
- 真实 Faro Key 不应写入源码、数据库、日志、计划文件、浏览器或测试输出。
- 同一验收指标连续三次修复失败后必须暂停并请求用户决定，避免无止境试错。

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
## 2026-08-29 · AI 助教无法运行的根因与恢复边界

- **根因已定位：** 当前 `WorkspaceShell` 挂载 `AgentPanel`，请求 `/api/v1/agent` 后进入 Host Claudian Runtime；Runtime 当前只注册 `ClaudeProvider`。这条链路与用户要求的 Faro → Gemini 3.7 Flash 不一致。
- **直接故障点：** `apps/api/src/tutor_api/tutor/router.py` 把 Tutor 创建会话和发消息接口改成 `410 Gone`，`/api/v1/tutor/status` 被移除；`main.py` 也不再创建 `FaroOpenAICompatibleAdapter` 和 `tutor_semaphore`。因此 API/Docker health 为 healthy 并不表示 AI 助教聊天写链路存在。
- **Faro 配置仍保留：** `compose.yaml`、`.env.example`、`core/config.py`、`llm/faro.py`、`worker_main.py` 仍包含 Faro 配置；默认模型为 `gemini-3.7-flash-tiered`。Worker 的语义索引仍可能使用 Faro，但当前聊天 UI 不使用它。
- **可复用实现：** Git HEAD 仍有完整 Faro Tutor router/service/schemas/main、前端 TutorPanel/tutor-api 与测试，可作为恢复参考。
- **必须保留的新增能力：** 当前 Tutor service/router 新增 legacy 会话列表/读取；citation schema 已扩展 knowledge/web 类型及 `knowledge_base_id`、`knowledge_base_name`、`space_id`、`url`。不能简单 checkout HEAD 覆盖。
- **产品/UI方向：** AI 助教默认区域只保留聊天、引用、输入框、状态摘要和“设置”按钮；设置使用统一暖白/浅紫 tokens，二级页签为“会话记录”和“服务设置”；服务页只读显示 Faro、Gemini 模型、配置/连接状态，不显示 Key，不提供 Claude 选项。
- **测试解释：** 2026-08-29 运行的 Web 聚焦测试为 3 files / 21 tests passed，但当前测试仍接受 Agent cutover 和只读 Tutor 历史，因此不是目标功能验收。API 聚焦测试在用户中断前只产生部分通过标记，无最终结论。
- **工作树风险：** 当前约 95 个修改/未跟踪条目，包含 Claudian Runtime、Agent API、Vault、迁移和大量测试；任何恢复操作必须限制路径并审查 diff。
## 2026-08-30 · AI 助教 Faro/Gemini 最终结论

- **最终根因：** 旧活跃链路虽然使用 Agent API，但 Runtime 只注册 `ClaudeProvider`；Faro 配置只存在于环境和其他 worker 路径，没有进入 AI 助教聊天链路。8765 端口一度还运行重启前旧构建，所以仅看容器/API 健康无法发现此问题。
- **最终架构：** `AgentPanel → /api/v1/agent → Agent Runtime → Faro OpenAI-compatible /chat/completions → gemini-3.7-flash-tiered`。Runtime provider registry 不再包含 Claude。
- **配置边界：** 活跃会话固定 `provider=faro`、`model=gemini-3.7-flash-tiered`、`context_window=32000`。数据库中的旧 Claude 或错误 Faro 设置不能覆盖固定配置；API 拒绝错误更新。
- **兼容策略：** 旧 Claude/Fable 会话只读保留，避免历史丢失；对旧会话发起新 turn 返回明确的 `409 agent_session_provider_retired`，不会送入 Runtime。
- **UI 决策：** AI 助教主区域只承担对话；会话记录与服务设置进入设置弹层二级页签。Provider、模型与上下文窗口只读，密钥只显示 configured/not-configured 状态。视觉沿用现有暖白/浅紫、细边框、圆角与轻阴影。
- **验收证据：** Runtime diagnostics 仅报告 `faro` 且为 `ok`；真实 Faro smoke 两次成功并收到非空 `model_text_delta`；API 119 项、Web 232 项、Runtime 86 项测试全部通过，Web lint/build 与 Runtime typecheck/build 通过。
- **运行状态：** Host Runtime PID `35704`；API/Web/PostgreSQL/Redis healthy，Worker/MinIO running；API health 为 `ok`，Web 入口 HTTP 200。
- **安全约束：** 验证过程未打印 Faro key、Runtime token 或 Capability secret；没有 reset/clean、删除卷、覆盖其他未提交改动或恢复退休 Tutor 写接口。

## 2026-08-30 · 最终稳定性收尾调查

- 正常 Markdown 已真实验证上传、Worker 完成、手动刷新到“可搜索”，说明状态 API 与基础 Worker 链路不是全面失效。
- 已确认 Web 存在双状态源缺陷：workspace 轮询只更新 `workspaceDocuments`，不会按 `document_id + document_version_id` 把权威 `processing_state` 合并到 `uploadsByKnowledgeBase`，所以“原始资料”可已就绪而“当前任务”仍停留在处理中。
- `knowledgeApi.workspace()` 与 `documentStatus()` 的易变 GET 未显式 `cache: no-store`，存在复用旧状态的风险。
- 数据库中发现两条真实 PDF 失败：一条 parse_document 最终为 `DataError/worker_unhandled_error`，一条为 `ParseError/invalid_format`；需安全重放定位，禁止泄露正文和异常敏感细节。
- 用户补充最终缺陷范围：会话记录无法返回旧聊天、四个会话功能无效、Capabilities 四按钮不可操作、知识库无删除入口；这些均纳入本轮收尾。

## 2026-08-30 · Runtime mutation contract blocker

- 真实分叉 400 的根因是 API RuntimeClient 未发送 Runtime 对 stop/rewind/fork 强制要求的 `Idempotency-Key` 与 `X-Workspace-Capability`。
- fork 请求还缺少预生成的 `fork_session_id`；Runtime 返回体包含该 `session_id` 与 `native_session_id`，API 数据库必须使用相同 session UUID，避免双端会话 ID 分裂。
- resume 使用完整 RuntimeStartRequest，是另一套合同；前端目前明确禁用继续，本轮不把它伪装成可用能力。
- 调查中一次误用 `apps/runtime/src` 路径失败；真实 Runtime 路径为 `apps/agent-runtime/src`，后续已改用正确路径。

## 2026-08-30 · Vault 删除真实 E2E 与最终取舍

- 用户明确表示分叉功能不是必需项，因此最终收尾不再为分叉增加新能力；已经完成并通过的修复保留，避免无收益改动。
- 使用全新隔离账号和个人知识库执行真实删除，不接触用户主知识库；在 Worker 实际 gent_vault_root 下创建 cleanup-proof.md 后调用删除接口。
- 验收结果：DELETE /api/v1/knowledge-bases/{id} 返回 204；Worker 第一次 500ms 轮询前已清理 <vault_root>/spaces/<space_id>/<knowledge_base_id>；随后详情 GET 返回 404。
- 这证明数据库硬删除、durable object-deletion outbox、Worker 领取任务与本地 Vault scope 清理已在真实 Compose/PostgreSQL 环境闭环。
- 第一次隔离注册使用了过长用户名并收到 422；改用符合长度约束的短用户名后一次通过。该失败属于验收数据不符合既有校验，不是产品缺陷。
## 2026-08-30 · Quality 与发布边界复核

- 用户确认本次暂不处理 Quality workflow 的红叉；它们表示 CI 门禁未全绿，不等同于当前代码未提交或 GitHub 文件不可下载。当前本机功能回归基线仍为此前记录的 API/Web/Runtime 通过结果。
- 远程核对：`git ls-remote github-collab` 返回 `feature/platform-foundation-wip -> f2a0acf`；`main -> 3347c6f`；`feature/aiopc-upgrades -> c53f459`；`feature/add-AIOPC -> 117fe2b`。
- 分支关系核对：`main` 是当前稳定分支祖先；`feature/aiopc-upgrades` 与当前稳定分支互不为祖先，因此没有被带入；`feature/add-AIOPC` 已在当前分支祖先链中，变更仅是 `progress.md` 记录。
- 未发现被跟踪的 `.env`、密钥、token 文件；本地 `.tmp/`、coverage 和临时 HTML 属于未跟踪诊断产物，不进入发布提交。
