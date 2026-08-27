# DeepTutor → Phase 5 Full Reuse Review

日期：2026-08-20  
审阅类型：只读规格/架构/许可证复审  
范围：DeepTutor learning、mastery、book、memory consolidator、chat agent pipeline；当前平台 Phase 5 边界  
结论状态：**审阅完成；未复制代码、未改产品实现、未改依赖、未启动 Docker、未运行测试**

## 1. 执行摘要

DeepTutor 不是只能用于论文分析的工具。其 `learning`、`mastery`、题目生命周期、错因诊断、间隔复习、教材块和中文学习提示词，确实与本项目的课程辅导目标高度相关。

但不建议把 DeepTutor 整体复制为本项目 Phase 5 的实现底座。两者的关键边界不同：

- DeepTutor：本地 workspace、SQLite/JSON/Markdown 状态、自有 Agent runtime、文件化知识库与记忆；
- 本项目：PostgreSQL/SQLAlchemy、pgvector、MinIO、Redis/数据库 worker、多租户 `space_id`、班级权限、不可变资料版本、引用链、Provider/Billing。

**正式建议：保留本项目平台底座，选择性迁移 DeepTutor 的课程学习算法、交互约束和提示词结构；所有持久化、权限、Agent 调度、引用和计费必须在当前架构内重写。**

这条结论不会替代 Task 10 的真实 Docker 验收。当前真实 ingestion/index/search 纵向链路仍未闭环，Task 10 仍为 blocked/abandoned，Phase 5 仍未完成。

## 2. 审阅范围与证据

已阅读或核对：

- `C:\Users\asus\Downloads\DeepTutor-main\DeepTutor-main\deeptutor\learning\models.py`
- `...\deeptutor\learning\service.py`
- `...\deeptutor\learning\storage.py`
- `...\deeptutor\learning\scheduler.py`
- `...\deeptutor\learning\policy.py`
- `...\deeptutor\learning\mastery.py`
- `...\deeptutor\learning\grading.py`
- `...\deeptutor\capabilities\mastery\tools.py`
- `...\deeptutor\capabilities\mastery\loop.py`
- `...\deeptutor\book\models.py`
- `...\deeptutor\book\compiler.py`
- `...\deeptutor\book\blocks\base.py`
- `...\deeptutor\book\blocks\quiz.py`
- `...\deeptutor\services\memory\consolidator\*`
- `...\deeptutor\agents\chat\agentic_pipeline.py`
- `C:\Users\asus\Downloads\DeepTutor-main\DeepTutor-main\LICENSE`
- `C:\Users\asus\Downloads\DeepTutor-main\DeepTutor-main\THIRD_PARTY_NOTICES.md`
- 当前 feature worktree 的 `apps/api/src/tutor_api/knowledge`, `spaces`, `classrooms`, `providers`, `billing`, `identity` 目录及现有模型符号

DeepTutor 根目录已确认采用 Apache License 2.0，并包含额外第三方 notices。若以后复制具体源代码，必须保留许可证、版权/专利/归属声明及适用 notices，并对修改作显著说明；本审阅没有复制任何源代码。

## 3. 课程辅导价值判断

### 3.1 高价值：学习闭环算法

以下能力可以作为当前项目的首批迁移对象，但应按当前命名、类型和测试体系重新实现：

1. **确定性答题评分**：选择题规范化、短答有限匹配、开放题关键词覆盖和空答案识别。
2. **掌握度计算**：仅使用最近尝试、较新的答案权重更高、证据不足时限制掌握度上限。
3. **下一学习目标决策**：未完成交互优先；到期复习其次；再按课程顺序选择未掌握知识点，并按知识类型设置门槛。
4. **间隔复习调度**：连续正确推进间隔，错误回退并提高优先级，复习队列按到期时间/风险排序。
5. **错误粗分类**：空答案和非空错误分开处理，再允许模型做更细的诊断。

这些是纯算法或领域策略，不依赖 DeepTutor 的文件系统、LLM provider 或 Agent runtime，最适合先提取为当前项目的纯函数/领域服务。

建议的当前项目接口方向：

```text
compute_mastery(attempts, knowledge_point_type) -> MasteryResult
normalize_answer(raw_answer, question_type) -> NormalizedAnswer
grade_answer(question_version, normalized_answer) -> GradeResult
schedule_review(mastery_state, outcome, policy) -> ReviewTask
select_next_learning_step(learner_state, due_reviews, course_structure) -> NextStep
```

具体天数、阈值和权重应作为产品策略配置，不应将 DeepTutor 的默认数字视为不可变技术标准。

### 3.2 必须保留的安全/一致性设计

DeepTutor 的题目生命周期中有一个必须采用的原则：

> 前端和模型只能看到题目的公开投影；标准答案、评分依据、来源锚点和内部状态必须由服务端保存并控制。

本项目后续应将题目拆为类似：

- `Question` / `QuestionVersion`：服务端完整记录；
- `PendingQuestionView`：返回题干、选项和交互说明，但不返回标准答案；
- `QuestionAttempt`：服务端按 pending question 和题目版本进行幂等提交。

提交答题应在一个数据库事务中完成：权限校验 → 锁定 pending 状态 → 读取服务端答案 → 评分 → 记录 attempt → 更新 mastery/error/review → 写入学习事件。不能信任浏览器或模型传回的 `expected_answer`、`space_id`、`user_id` 等隐式参数。

### 3.3 中高价值：mastery capability 的交互约束

`mastery/tools.py` 和 `mastery/loop.py` 值得参考的重点不是其具体 runtime，而是：

- 服务端注入路径、session、turn 等上下文；
- 模型可以提出学习路径或题目，但服务端校验并持久化；
- `ask_user` 暂停前先提交 awaiting 状态；
- 用户恢复时由服务端读取真实 pending 题目，而不是让模型重新编造；
- stale question、重复提交、路径切换和并发写入需要显式状态转换。

这些约束应适配当前项目的 HTTP/worker/Provider/Billing 协议，不能直接挂载 DeepTutor 的 capability registry。

## 4. 当前项目的原生映射

当前 feature worktree 已有可靠的平台边界：

- `KnowledgeBase`、`Document`、`DocumentVersion`、`Page`、`Block`、`IndexVersion`、`Chunk`、`IngestionJob`；
- 不可变源文件和 MinIO 对象存储；
- `space_id` 隔离、个人/班级访问控制和教师权限；
- PostgreSQL/pgvector 索引身份与引用预览；
- Provider profile、价格版本、钱包预留和用量结算；
- Redis/数据库 worker 租约与失败状态。

因此，DeepTutor 的学习域不能继续使用其 aggregate JSON/SQLite store，而应新增当前项目原生的 SQL 模型。建议最小领域集合：

```text
LearningPath
CourseModule
KnowledgePoint
Question
QuestionVersion
PendingInteraction
QuestionAttempt
MasteryState
ReviewTask
ErrorRecord
LearningEvent
```

每个租户相关对象都必须明确 `space_id` 与 learner/owner 关系；班级共享对象还需明确 teacher approval 和发布版本。知识点、题目、讲解、错题总结和生成教材均应保留到不可变资料的来源锚点：

```text
DocumentVersion → Page / Block / Chunk → source_pointer
```

生成内容不能覆盖原始 `DocumentVersion`，也不能将无来源的 LLM 文本伪装成教材原文。

## 5. 复用矩阵

| DeepTutor 区域 | 结论 | 原因/动作 |
|---|---|---|
| `learning/mastery.py` | 高优先级迁移算法 | 纯掌握度计算；按当前领域模型重写并补边界测试 |
| `learning/grading.py` | 高优先级迁移算法 | 可解释、低成本；中文/公式/代码须支持 `needs_review` |
| `learning/scheduler.py` | 高优先级迁移策略 | 间隔复习框架可用；参数产品化 |
| `learning/policy.py` | 高优先级迁移策略 | 下一步学习选择应结构化、可测试，不交给 LLM 临场决定 |
| `learning/models.py` | 领域建模参考 | 不直接复制 Pydantic 聚合；映射 PostgreSQL 表和权限 |
| `learning/service.py` | 流程参考，存储重写 | 事务、幂等、锁和审计须使用 SQLAlchemy |
| `learning/storage.py` | 不可直接复用 | SQLite/JSON/file workspace 与多租户 SQL 不兼容 |
| `mastery/tools.py` / `loop.py` | 交互协议参考 | 重建为当前 Agent 的工具，不引入第二套 runtime |
| `book/models.py` / `blocks/*` | 中期参考 | Block taxonomy、partial/error/ready 状态和 source anchor 有价值 |
| `book/compiler.py` | 不直接复制 | 依赖 DeepTutor storage/provider/retrieval；需当前 worker/引用/计费适配 |
| `memory/consolidator/chunker.py` | 局部纯算法参考 | 适合生成内容/记忆分块，不替代正式知识库分块 |
| `memory/consolidator/line_doc.py` | 中后期参考 | 行级 replace/delete/insert 和引用回校验适合审阅式笔记更新 |
| `memory/consolidator/references.py` / `guards.py` | 规则参考 | 必须绑定当前 citation、权限和审核模型 |
| `memory/consolidator/modes/*` | 不直接复制 | 文件化文档、LLM、原子写入和事件运行时需重建 |
| `agents/chat/agentic_pipeline.py` | 架构参考 | 不复制 orchestrator/registry/stream/provider；避免第二套 Agent Loop |
| DeepTutor 中文 prompts | 高价值内容参考 | 可作为课程辅导提示词初稿，需改为当前引用、工具、计费和权限语义 |
| DeepTutor parse/RAG/multi_user | 不直接复用 | 与当前 immutable SQL/pgvector/MinIO/tenant 边界冲突，且不能解决 Task 10 失败 |

## 6. 推荐实施顺序

### 第 0 步：先定义原生学习域不变量

暂不接完整 Agent、自动教材和 L0-L3 consolidation。先确定题目版本、标准答案隔离、答题幂等、错题状态、复习任务、来源锚点和班级审核规则。

### 第 1 步：实现不依赖 LLM 的学习闭环

创建题目 → 展示公开投影 → 服务端评分 → 记录尝试 → 更新掌握度 → 记录错因 → 安排复习 → 返回下一步。

### 第 2 步：接入权限、审计和 worker

将学习状态写入 PostgreSQL，使用事务/行锁或版本号解决并发；长任务使用已有 worker/lease；模型生成题目和讲解要经过 Provider/Billing。

### 第 3 步：接入最小 Agent

先实现 `rag_search`、`answer_with_citations`、`ask_user`、`mastery_status`、`mastery_quiz`、`mastery_grade`，直接复用当前知识库的权限过滤和 citation 结构。

### 第 4 步：补齐教学流程

依次增加诊断、基于资料讲解、Feynman 检查、练习、错因诊断、错题本、间隔复习、进度面板和教师干预。

### 第 5 步：最后再做高级教材与记忆

在基础学习模型、引用链、Agent、计费和 worker 稳定后，再实现教材 `Chapter/Page/Block`、概念图、闪卡、自动笔记和 L1/L2/L3 记忆。

## 7. 风险与验收门槛

| 风险 | 等级 | 门槛 |
|---|---:|---|
| 第二套 Agent runtime | 高 | 不允许直接导入 DeepTutor orchestrator/registry/stream/provider |
| 多租户/班级越权 | 高 | 所有学习对象和工具参数由服务端绑定 `space_id`/learner/role |
| 标准答案泄漏 | 高 | 公开题卡、API 响应和模型工具参数不含标准答案 |
| 引用链断裂 | 高 | 生成讲解/题目/笔记必须能回到不可变来源锚点 |
| 状态竞争 | 高 | pending/attempt/path/review 状态具备事务、幂等或版本约束 |
| 中文/专业学科误判 | 中高 | 不确定答案支持 `needs_review`，不得强行二值结论 |
| LLM 计费脱节 | 高 | 所有模型调用经过当前 provider、钱包预留、价格快照和 usage settle |
| 许可证/第三方归属 | 中 | 复制代码前建立 NOTICE 记录并保留 Apache/第三方文本 |
| Task 10 被误替代 | 中高 | DeepTutor 复用审阅不能作为 ingestion/index/search/citation 验收证据 |

## 8. 最终决定

1. **接受** DeepTutor 作为课程学习业务层的成熟参考和候选迁移来源。
2. **拒绝** 整库复制、覆盖当前 `apps/api` 或引入第二套 runtime/存储/权限/计费体系。
3. **下一实施优先级**：先在当前项目设计原生 SQL 学习域，再迁移掌握度、评分、复习和下一目标四类纯算法。
4. **暂不实现** Book 全量编译和 L0-L3 memory consolidator；它们属于后续阶段。
5. **保持事实准确**：Task 10 仍未完成，Phase 5 仍为 `in_progress`。

任何源代码迁移前，必须另做一次独立规格复审、许可证/第三方依赖审计和当前数据模型映射，并获得用户确认。
