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
- Docker 和 uv 当前未安装。实施计划必须先完成 Docker Desktop/Compose 可用性检查；在此之前可以先生成代码和运行不依赖容器的前端检查，但不能宣称本机端到端环境完成。
- 用户随后报告 Docker 已安装，但当前 Codex 终端仍无法解析 `docker`；桌面快捷方式目标位于已不存在的沙箱用户目录，标准安装目录也未发现可执行文件。可能需要重启 Codex/终端刷新安装状态，或确认 Docker Desktop 实际安装位置。
- Codex 工作区提供独立 Python 3.12.13，可用于 Docker 安装前的后端单元测试与开发；正式项目仍以 Python 3.12 和锁定依赖为准，不依赖系统 Anaconda Python 3.9。
- `react-resizable-panels` 官方当前版本 4.x 使用 `Group`、`Panel`、`Separator`，并支持 `defaultLayout` 与键盘可访问分隔条；首个前端计划按该接口实现三块可拖动区域。
- 当前仓库是 `main` 分支的普通检出，不是隔离 worktree；开始业务代码前需按开发流程获得用户同意后创建项目内隔离 worktree。

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
