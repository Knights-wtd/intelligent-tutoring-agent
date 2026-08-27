# MVP 收口完成 / Phase 6 验收入口交接

- 日期：2026-08-21
- 工作树：`E:\项目\知识库课本\.worktrees\platform-foundation`
- 目标：以“带来源追溯的资料知识库 + 题库学习闭环 MVP”进入 Phase 6 客户验收。

## 已完成

- MVP 工作台移除未实现的 AI Tutor、模型、余额和费用承诺。
- 题库学习者 UI 已支持查看题目、提交答案、查看评估、复习队列和最近一页本人历史。
- 资料处理状态通过受权限保护的 status endpoint 刷新。
- 上传响应 DTO 已收紧为 `document_id`、`document_version_id`、`source_name`、`created_at`。
- 题库切换/取消请求、loading 清理、上传多条目状态刷新竞态已修复。
- 同一题目+同一规范化答案重试复用幂等键；提交成功后复习列表刷新失败也保留 key。
- 最终独立窄复审：PASS，P0=0、P1=0、P2=0。

## 验证证据

- API 上传 focused tests：61 passed。
- Web focused：3 files / 22 tests passed；题库回归 4 passed。
- 目标 Ruff、ESLint、TypeScript 非增量检查、差异检查：通过。
- 本次已执行：隔离 Docker/Compose、Alembic head、真实资料导入/索引/检索/source/page preview；未执行全量测试、coverage、外部 OCR/Embedding/LLM。

## Phase 6 已完成 / 客户验收入口

1. 客户演示真实资料链路：上传 Markdown → 状态 searchable → 唯一 token 搜索命中 → 打开 citation source/page preview。
2. 客户演示题库 UI/API：选题 → 作答 → 评估 → review-items → 最近历史（已有 focused/API/UI 证据）。
3. 使用已更新的验收包说明范围、已知限制和延期高级功能；不要把本次 MVP PASS 扩大为真实 LLM Tutor 或高级能力已交付。

## 不可改写的已知事实

2026-08-19 的真实 Docker/pgvector Task 10 曾出现：服务健康，但 Markdown 资料索引失败，150 秒内搜索结果为 0。MVP 窄复审 PASS 不等于历史失败记录已消失；修复后的新鲜隔离链路已在本交接文件末尾记录为 PASS。

## 保护约束

- 保留所有既有未提交记录；不要 `git add`、`commit`、`reset`、`stash`、`checkout`。
- 不重新实现 Task 5，不重开已停止的 Task 10 反复修复循环。
- 真实 LLM Tutor、知识图谱、自生长笔记、L0-L3 记忆、多 Agent、生成式题目、教师分析、性能压测和非关键 coverage 延期到客户验收/下一笔资金后。

## 2026-08-21 实际执行状态

- 已尝试在当前 Codex PowerShell 启动 Phase 6，但 `docker version --format '{{.Server.Version}}'` 无法解析 `docker`。
- 未启动任何 Compose 项目，未创建/删除容器或数据卷，未运行 Alembic；因此没有新的真实资料链路结果。
- 用户下一步只需在 Docker Desktop 已就绪且 `docker` 可解析的终端提供入口；进入工作树后使用新 project name，不复用 2026-08-19 失败数据。
- Docker 可用后验收顺序：
  1. `docker compose --project-name <fresh-name> --env-file .env up --build -d`
  2. 等待 `api/postgres/redis/web` healthy；执行 Alembic current/upgrade head。
  3. 注册测试用户、创建个人知识库、上传新鲜 Markdown。
  4. 轮询安全 status endpoint，必须看到 `searchable`；若 `failed`，收集 API/worker 日志并记录 FAIL，不再无依据调参。
  5. 搜索唯一 token，检查结果数量与 citation；打开 source/page preview，记录响应状态和内容类型。
  6. 演示题库：选题、提交、评估、review-items、最近历史。

## 2026-08-21 实际验收结论

- Docker 已可用，使用隔离 project `mvp-phase6-20260821` 完成一次真实验收。
- 服务健康、迁移到 `0010_question_attempt_assessment (head)`、注册/建库/上传成功。
- 真实处理失败：`parse_document=completed`，`build_index=failed`，`index_validation_failed`，3/3 次尝试；pages=1，chunks=0。
- 这不是环境阻塞，而是代码/运行时真实索引 Gate FAIL。结合 2026-08-19 旧失败，按 stop-rule 停止重复修复。
- 未改代码、未运行重复全量测试、未删除 Compose 数据卷；根目录和 feature worktree 既有未提交记录保留。
- 下一会话如继续，先由客户决定：接受收缩 MVP 并进入商务/高级功能，或单独授权一次有根因假设的索引修复任务。不要直接宣称 Phase 6 完整通过。

## 2026-08-21 索引校验窄修复交接

- 真实失败根因已锁定为 embedding float4 文本 round-trip 的 Python 精确比较误判；已按唯一根因完成窄修复。
- 代码验证已通过：相关索引比较测试 9 passed，目标 Ruff 通过，`git diff --check` 通过；没有跑全量测试或外部 API。
- 当前新 PowerShell 无法解析 `docker`，修复后的真实资料 Gate 尚未重验。需要用户提供 Docker CLI 准确路径或切换到能解析 `docker` 的终端。
- 真实重验只允许一次：成功才记录 searchable/检索/citation/source/page preview；失败则停止，不再重复调参。所有既有未提交记录必须保留。

## 2026-08-21 Phase 6 完成记录

- 修复后的唯一真实资料 Gate 已通过：`searchable`、唯一 token 搜索命中、source/page preview 均有 HTTP 206 证据。
- 代码层修复与最小验证：float4 32-bit 位模式比较；signed-zero 回归；相关测试 9 passed；Ruff 与 diff check 通过。
- MVP 当前可转交客户验收/资金节点。高级功能继续延期，不要扩大本期承诺。
- 后续如进入新任务，优先做客户演示材料或在资金确认后启动延期高级能力；不要重复 Task 10/Phase 6 资料 Gate，除非基础设施或代码发生实质变化。
