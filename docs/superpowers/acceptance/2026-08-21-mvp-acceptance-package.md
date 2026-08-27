# MVP 客户验收包（Phase 6 草案）

> 状态：**代码/合同复审通过；真实 Docker 资料链路 Gate 已通过；MVP 可进入客户验收**。
>
> 本文不把 focused tests 或服务健康误写成 PostgreSQL/pgvector 端到端通过。

## 一、本期交付口径

本期产品应对外表述为：

**带来源追溯的资料知识库 + 题库学习闭环 MVP**。

已包含：

- 个人/班级空间与服务端授权；
- 知识库创建、资料上传、处理状态查询；
- 资料检索与来源/原页预览（已由修复后隔离容器 Gate 证明）；
- 题目查看、确定性作答评估、复习队列、最近一页本人历史；
- 学习者响应不包含答案、rubric、提交内容、用户身份等私密字段；
- 题库答题后端事务与幂等保护。

## 二、代码复审证据

- 最终独立窄复审：PASS；P0=0、P1=0、P2=0。
- API 上传 focused tests：61 passed。
- Web focused：3 files / 22 tests passed；题库面板回归 4 passed。
- 目标 Ruff、ESLint、TypeScript 非增量检查、差异检查：通过。

## 三、已完成的 Phase 6 Gate（证据见第八节）

在新鲜隔离 Compose project 中完成一次：

1. 新建测试用户和个人知识库；
2. 上传带唯一检索 token 的 Markdown；
3. 通过安全 status endpoint 看到 `searchable`；
4. 搜索唯一 token，结果数量大于 0；
5. 打开 citation/source/page preview，并记录 HTTP 状态、内容类型和来源名；
6. 通过产品 UI 或记录的 API 步骤完成一次题目作答、评估、复习队列、最近历史。

若资料状态为 `failed` 或搜索结果为 0，应记录为 **FAIL/已知限制**，不能用 fake API key、服务 health 或内存测试替代真实链路。

## 四、历史环境阻塞（已解除）

2026 年 8 月 21 日在当前 Codex PowerShell 执行：

```powershell
docker version --format '{{.Server.Version}}'
```

该会话曾因 `docker` 不可解析而暂时阻塞；随后使用已知 CLI 路径完成验证，未安装软件、改 PATH 或清理数据卷。\r\n\r\n当前验收已完成；后续新任务若需 Docker，可使用 `C:\Users\asus\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`。\r\n\r\n## 五、明确延期项

客户验收/下一笔资金后再扩展：

- 真实 LLM Tutor runtime、流式对话和真实调用计费联动；
- 知识图谱、自生长笔记、教师治理；
- L0-L3 长期记忆、多 Agent、复杂规划；
- 生成式题目、教师分析、班级画像；
- 完整历史分页 UI；
- 性能压测、高级检索质量评估和非关键 coverage 优化。

## 六、历史限制

2026 年 8 月 19 日真实 Docker/pgvector Task 10 曾出现服务健康但资料索引失败、150 秒内搜索结果为 0。该事实保持不变；本次只有新鲜隔离实证成功后才可把真实资料链路改为 PASS。

## 七、2026-08-21 新鲜隔离环境验收结果

### 环境证据

- Compose project：`mvp-phase6-20260821`（独立于 2026-08-19 失败项目）
- Docker Server `29.7.2`，Compose `v5.3.1`
- PostgreSQL/pgvector、Redis、MinIO、API、Worker、Web 均启动；API/Web healthy。
- Alembic：`0010_question_attempt_assessment (head)`。

### 资料链路结果：FAIL

- 注册、个人知识库创建、Markdown 上传均成功。
- 资料处理状态：`processing` → `failed`。
- 数据库任务：`parse_document=completed`；`build_index=failed`；`attempt_count=3/max_attempts=3`；`last_error_code=index_validation_failed`。
- 观察到 `pages=1`、`chunks=0`、`index_versions.state=failed`。
- 因无成功索引和 citation，搜索唯一 token、source preview、page preview 不具备 PASS 前提，未作虚假通过声明。

### 本期交付边界修订

当前可以向客户展示/交付的内容：

1. 已通过独立复审的多租户权限、上传契约、处理状态可见化、题库学习者 UI/API、确定性评估、复习队列和最近一页历史；
2. 新鲜 Compose 环境服务启动、迁移和上传成功证据；
3. 真实资料索引失败的透明记录。

当前不能无条件承诺：

- PostgreSQL/pgvector 真实资料导入后可检索；
- citation/source/page preview 的真实端到端成功；
- 真实 LLM Tutor、OCR/远程 embedding、知识图谱、自生长笔记、记忆、多 Agent、生成式题目、教师分析和性能压测。

### 验收决策

Phase 6 的代码与题库 MVP 证据可作为阶段性成果；“真实资料检索 Gate”未通过。根据 stop-rule，本次不再重复调参。若客户接受资料检索阻塞，可按收缩后的 MVP 交付并进入商务确认；若客户要求资料检索无条件 PASS，需另立一次有明确根因假设的修复任务，不应把本次结果标为 PASS。


## 2026-08-21 代码层索引修复更新

- 已完成一次且仅一次有明确根因的最小修复：`float4` 比较改为 IEEE-754 32 位位模式比较，`+0.0` 与 `-0.0` 不再被错误放行。
- 新增回归测试并完成最小验证：相关测试 9 passed；目标 Ruff 通过；`git diff --check` 通过；测试文件末尾换行已修复。
- 当前新 PowerShell 会话无法解析 `docker`，因此尚未执行修复后的唯一真实重验；未安装、搜索、改 PATH、启动或清理 Docker。
- 下次继续只需提供 Docker CLI 的准确可执行路径，或在能解析 `docker` 的终端执行一次真实 Gate；不要重复历史 Task 10 或把代码层 PASS 当作真实资料检索 PASS。

## 八、2026-08-21 修复后唯一真实资料链路重验：PASS

### 环境与范围

- Compose project：`mvp-phase6-20260821`；保留原有容器与数据卷。
- 仅重建 `api`/`worker` 以载入 float4 位模式比较修复；服务恢复 healthy。
- Docker Server `29.7.2`，Compose `v5.3.1`；Alembic `0010_question_attempt_assessment (head)`。
- 新建临时用户、个人知识库和唯一 token Markdown；未使用外部 OCR/Embedding/LLM API key。

### 真实证据

| 步骤 | 结果 |
|---|---|
| 注册/登录临时用户 | PASS |
| 创建个人知识库 | PASS |
| 上传 Markdown（明确 `text/markdown` MIME） | PASS |
| 处理状态 | `processing` → `searchable` |
| 唯一 token 搜索 | PASS，`results=1` |
| citation source preview | PASS，HTTP `206 Partial Content`，`text/markdown; charset=utf-8` |
| citation page preview | PASS，HTTP `206 Partial Content`，`text/plain; charset=utf-8` |

### 结论

- Phase 6 的真实资料链路 Gate **PASS**；本期 MVP 可按“带来源追溯的资料知识库 + 题库学习闭环”进入客户验收。
- 2026-08-19 及修复前的 `index_validation_failed` 是历史失败记录；本次 float4 位模式窄修复后的新鲜隔离证据证明该根因已修复。
- 不得由本次资料链路 PASS 推导出真实 LLM Tutor、OCR/远程 embedding、知识图谱、长期记忆、多 Agent、生成式题目、教师分析或性能压测已交付。
