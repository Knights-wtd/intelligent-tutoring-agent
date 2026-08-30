# Agent Index Migration and Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为永久 Vault 建立确定性基础索引与 AI SemanticIndexPlan 两阶段流水线，安全迁移旧知识库，并提供 Node.js 24 宿主机 Runtime 的配置、安装、可观测性和 CI 门禁。

**Architecture:** watcher/change set 先保证每个支持文件均有基础投影和可搜索内容，再由 Agent provider 输出结构化语义计划；计划校验失败不破坏原文件或 active index。迁移采用 inventory、copy、hash verify、shadow sync、原子激活和可逆 manifest，Runtime 独立于容器化 FastAPI/Web 生命周期。

**Tech Stack:** Python 3.12, SQLAlchemy/Alembic, PostgreSQL/pgvector, durable ingestion worker, Node.js 24 host service, PowerShell/Bash, Docker Compose, GitHub Actions

---

### Task 1: 定义和校验 SemanticIndexPlan

**Files:**
- Create: `apps/api/src/tutor_api/knowledge/semantic_plan.py`
- Create: `apps/api/tests/test_semantic_index_plan.py`
- Modify: `apps/api/src/tutor_api/vault/models.py`

- [ ] **Step 1: 写完整知识点计划失败测试**

```python
def test_plan_accepts_many_chunks_terms_tags_and_links_without_product_count_cap():
    payload = {
        "schema_version": "1.0",
        "source_hash": "a" * 64,
        "chunks": [{"ordinal": i, "heading": f"H{i}", "start": i, "end": i + 1} for i in range(250)],
        "concepts": [{"name": f"C{i}", "aliases": [], "tags": ["知识点"]} for i in range(250)],
        "terms": [{"term": f"T{i}", "definition": f"D{i}"} for i in range(250)],
        "links": [{"source": f"C{i}", "target": f"C{i+1}", "relation": "related"} for i in range(249)],
    }
    assert validate_semantic_index_plan(payload).source_hash == "a" * 64
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_semantic_index_plan.py -q`

Expected: FAIL，因为 schema/validator 尚不存在。

- [ ] **Step 3: 实现严格 schema**

```python
class SemanticChunk(BaseModel):
    ordinal: int = Field(ge=0)
    heading: str | None = None
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    concepts: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

class SemanticIndexPlanPayload(BaseModel):
    schema_version: Literal["1.0"]
    source_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    chunks: list[SemanticChunk]
    concepts: list[SemanticConcept]
    terms: list[SemanticTerm]
    links: list[SemanticLink]
```

不对 list 设置固定 `max_length`；校验 start/end、ordinal 唯一、link 引用存在、路径/heading 合法和 source hash 一致。资源防护使用请求字节、provider context、worker 并发和磁盘指标，不把知识点数量静默截断。

- [ ] **Step 4: 实现 prompt contract**

Planner system instruction 明确：所有支持文件已自动收录；AI 只判断分块、知识点、术语、别名、标签和关联；可结合文件、其他授权 Vault 内容、模型通用知识和公开 Web 来解释联系；不得虚构原文内容，外部推断必须标记 provenance/confidence。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest apps/api/tests/test_semantic_index_plan.py -q`

Expected: PASS，包括 250+ 项、invalid offset、dangling link、stale source hash 和 provenance。

- [ ] **Step 6: 提交**

```powershell
git add apps/api/src/tutor_api/knowledge/semantic_plan.py apps/api/src/tutor_api/vault/models.py apps/api/tests/test_semantic_index_plan.py
git commit -m "feat: validate unlimited semantic index plans"
```

### Task 2: 扩展两阶段索引和原子激活

**Files:**
- Modify: `apps/api/src/tutor_api/knowledge/indexing.py:127-660`
- Modify: `apps/api/src/tutor_api/knowledge/worker.py`
- Modify: `apps/api/src/tutor_api/worker_main.py`
- Create: `apps/api/src/tutor_api/knowledge/semantic_worker.py`
- Modify: `apps/api/tests/test_knowledge_indexing.py`
- Create: `apps/api/tests/test_semantic_index_worker.py`

- [ ] **Step 1: 写失败保留旧索引测试**

```python
def test_planner_failure_keeps_previous_active_index(session, active_index, planner):
    planner.raise_error("provider unavailable")
    result = run_semantic_index_job(session, active_index.knowledge_base_id)
    session.refresh(active_index)
    assert result.state == "failed"
    assert active_index.state == IndexVersionState.ACTIVE
    assert active_index.activated_at is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_knowledge_indexing.py apps/api/tests/test_semantic_index_worker.py -q`

Expected: FAIL，因为 semantic worker 和 snapshot contract 尚不存在。

- [ ] **Step 3: 扩展 IndexBuildRequest**

```python
@dataclass(frozen=True)
class IndexBuildRequest:
    knowledge_base_id: UUID
    document_version_ids: tuple[UUID, ...]
    created_by_user_id: UUID
    source_change_set_id: UUID | None = None
    source_snapshot_hash: str | None = None
    semantic_plan_id: UUID | None = None
```

基础阶段从所有非 tombstone Vault Markdown/附件投影建立 deterministic chunks；语义阶段用 validated plan 替换/丰富 chunk metadata、candidate concepts/terms/links。不得在 load 阶段使用 `LIMIT 20` 或只选前 N 个知识点。

- [ ] **Step 4: 实现 planner worker**

Worker 为每个变更 snapshot 计算 canonical hash，复用已有成功同 hash plan；否则调用 Agent provider 生成 JSON，保存 raw sidecar、validated payload、provider/model/schema/prompt hash 和错误。source hash 在 provider 返回后变化则标记 stale 并重新排队，不激活旧计划。

- [ ] **Step 5: 保持原子激活**

继续使用 `prepare_index_build()`、`_validate_persisted_index()`、`_lock_knowledge_base()`、`_activate_building_index()`；只有 deterministic + semantic 数据全部持久化并校验后，将旧 active 标记 superseded、building 标记 active。任何异常 rollback building index，旧 active 不变。

- [ ] **Step 6: 运行测试**

Run: `python -m pytest apps/api/tests/test_knowledge_indexing.py apps/api/tests/test_semantic_index_worker.py apps/api/tests/test_knowledge_worker.py -q`

Expected: PASS，包括 100+ 文件、250+ chunks、planner stale/retry、provider failure、embedding failure 和旧 index 保留。

- [ ] **Step 7: 提交**

```powershell
git add apps/api/src/tutor_api/knowledge apps/api/src/tutor_api/worker_main.py apps/api/tests
git commit -m "feat: add two-stage vault semantic indexing"
```

### Task 3: 实现旧数据库/MinIO 到永久 Vault 的可逆迁移

**Files:**
- Create: `apps/api/src/tutor_api/vault/migration.py`
- Create: `apps/api/src/tutor_api/vault/migration_cli.py`
- Create: `apps/api/tests/test_vault_migration.py`
- Create: `artifacts/agent-migration/.gitkeep`
- Modify: `README.md`

- [ ] **Step 1: 写 inventory/hash 失败测试**

```python
def test_migration_preserves_file_count_size_and_hash(migrator, legacy_notes):
    manifest = migrator.inventory()
    result = migrator.copy_and_verify(manifest)
    assert result.source_file_count == result.vault_file_count
    assert result.source_total_bytes == result.vault_total_bytes
    assert result.hash_mismatches == []


def test_conflict_does_not_overwrite_existing_vault_file(migrator, existing_vault_file):
    result = migrator.copy_one(existing_vault_file.source)
    assert result.state == "conflict"
    assert existing_vault_file.path.read_text() == "existing"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_vault_migration.py -q`

Expected: FAIL，因为 migrator 尚不存在。

- [ ] **Step 3: 实现四阶段命令**

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vault-migration")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "copy", "verify", "activate-shadow", "cutover", "rollback"):
        command = subcommands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.set_defaults(handler={
            "inventory": inventory_command,
            "copy": copy_command,
            "verify": verify_command,
            "activate-shadow": activate_shadow_command,
            "cutover": cutover_command,
            "rollback": rollback_command,
        }[name])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args) or 0)
```

`inventory` 写 JSONL manifest，包含 KB/note/revision/source object/path/bytes/hash；`copy` 原子写 Vault 且不覆盖冲突；`verify` 比较 count/bytes/hash；`activate-shadow` 让旧 API 写入同时产生 change set；`cutover` 仅在 verify 全绿后把 Vault 标记 authoritative；`rollback` 恢复旧 active index/legacy read path，但不删除 Vault 新文件。

- [ ] **Step 4: 保存 provenance 和冲突**

每个迁移文件创建稳定 `VaultFile`、migration change set 和关联 revision；现有 Vault 路径不同 hash 时保存冲突报告和建议新路径，不自动覆盖。manifest 写入 `artifacts/agent-migration/<timestamp>/`，供回滚和审计。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest apps/api/tests/test_vault_migration.py apps/api/tests/test_knowledge_markdown.py -q`

Expected: PASS，包括 empty KB、Unicode/Windows path、duplicate title、conflict、resume after crash 和 rollback。

- [ ] **Step 6: 提交**

```powershell
git add apps/api/src/tutor_api/vault apps/api/tests/test_vault_migration.py artifacts/agent-migration/.gitkeep README.md
git commit -m "feat: migrate knowledge content into permanent vaults"
```

### Task 4: 配置宿主机 Runtime 和高容量资源参数

**Files:**
- Modify: `.env.example`
- Modify: `compose.yaml`
- Modify: `README.md`
- Create: `scripts/install-agent-runtime.ps1`
- Create: `scripts/start-agent-runtime.ps1`
- Create: `scripts/smoke-agent-runtime.ps1`
- Create: `scripts/smoke-agent-runtime.sh`
- Modify: `apps/api/tests/test_config.py`
- Modify: `apps/api/tests/test_compose_security.py`

- [ ] **Step 1: 写配置失败测试**

```python
def test_agent_defaults_target_million_context_without_fixed_evidence_limits(settings):
    assert settings.agent_context_window == 1_000_000
    assert not hasattr(settings, "tutor_knowledge_sources")
    assert not hasattr(settings, "tutor_web_search_max_results")


def test_runtime_is_loopback_and_not_a_required_api_dependency(compose):
    assert compose.runtime_public_ports == []
    assert compose.api.depends_on_runtime is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_config.py apps/api/tests/test_compose_security.py -q`

Expected: FAIL，旧 Tutor 固定限制仍存在且 Runtime 配置尚未完成。

- [ ] **Step 3: 定义环境变量**

`.env.example` 加入 `AGENT_RUNTIME_URL=http://host.docker.internal:8765`、随机 `AGENT_RUNTIME_TOKEN`、`AGENT_CAPABILITY_SECRET`、`AGENT_VAULT_ROOT`、`AGENT_SIDECAR_ROOT`、`AGENT_PROVIDER=claude`、`AGENT_MODEL`、`AGENT_CONTEXT_WINDOW=1000000`、`AGENT_INLINE_EVENT_BYTES=262144`、MCP/Skills 路径和并发/backpressure 配置。删除当前新增的 Tutor prompt/history/evidence/KB/Web 结果数量变量。

- [ ] **Step 4: 实现 Windows 宿主机脚本**

`install-agent-runtime.ps1` 验证 Node `>=24 <25`、安装 frozen pnpm 依赖、创建数据目录和当前用户级后台启动配置；`start-agent-runtime.ps1` 使用 `Start-Process -WindowStyle Hidden`，PID/log 写入本地状态目录；token 通过环境/受限配置文件传入，不出现在命令行或日志。

- [ ] **Step 5: 更新 compose 隔离**

API/worker 只获得 Runtime URL/token 和 Vault path；Runtime 不作为 `depends_on`，不因其故障阻塞容器启动。开发可选 profile 可运行 Node container smoke，但生产文档明确完整 Bash/宿主机能力使用 host service。Vault 目录不暴露给 Web 容器。 Linux Docker API/worker 增加 `extra_hosts: ["host.docker.internal:host-gateway"]`，Windows Docker Desktop 保持同一 URL；Runtime 端口只绑定宿主机 loopback。

- [ ] **Step 6: 运行配置和 smoke**

Run: `python -m pytest apps/api/tests/test_config.py apps/api/tests/test_compose_security.py -q`

Expected: PASS。

Run: `powershell -ExecutionPolicy Bypass -File scripts/smoke-agent-runtime.ps1`

Expected: Node 24 health、session、Vault 临时文件、Bash、公开 Web、Stop 和 restart recovery 成功。

- [ ] **Step 7: 提交**

```powershell
git add .env.example compose.yaml README.md scripts apps/api/tests/test_config.py apps/api/tests/test_compose_security.py
git commit -m "build: configure host agent runtime and vault storage"
```

### Task 5: 暴露诊断、指标和故障恢复状态

**Files:**
- Create: `apps/api/src/tutor_api/agent/diagnostics.py`
- Modify: `apps/api/src/tutor_api/agent/router.py`
- Modify: `apps/agent-runtime/src/server.ts`
- Create: `apps/api/tests/test_agent_diagnostics.py`
- Create: `apps/agent-runtime/tests/diagnostics.test.ts`

- [ ] **Step 1: 写诊断失败测试**

```python
def test_diagnostics_reports_runtime_and_backlogs_without_secrets(client):
    body = client.get("/api/v1/agent/diagnostics").json()
    assert "runtime" in body and "watcher_backlog" in body and "index_backlog" in body
    assert "agent_runtime_token" not in json.dumps(body)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_agent_diagnostics.py -q`

Expected: FAIL，因为 diagnostics 尚不存在。

- [ ] **Step 3: 实现指标快照**

返回 Runtime/version/provider/MCP health、active/warm/queued sessions、event persistence latency、WebSocket replay、tool latency/error、sidecar bytes、watcher/index backlog、index activation latency、Vault/DB conflict、recovery rate、capability/SSRF rejection 和 disk free。所有值带 correlation IDs 或 aggregate labels，不包含 prompt、secret 或未脱敏命令环境。

- [ ] **Step 4: 实现恢复状态**

Runtime unavailable、database unavailable、watcher backlog、disk low、MCP/Web/process failure 映射到明确 degraded 状态和 retry hint。非 Agent health 仍由 `/api/v1/health` 独立返回 ok；Agent diagnostics 的 503 不传播到登录/知识/题库。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest apps/api/tests/test_agent_diagnostics.py apps/api/tests/test_health.py -q && pnpm --dir apps/agent-runtime test -- diagnostics`

Expected: PASS，包括 secret redaction、runtime down、disk low 和 non-Agent health isolation。

- [ ] **Step 6: 提交**

```powershell
git add apps/api/src/tutor_api/agent apps/api/tests/test_agent_diagnostics.py apps/agent-runtime/src apps/agent-runtime/tests
git commit -m "feat: expose agent runtime and vault diagnostics"
```

### Task 6: 扩展跨平台 CI 和发行包检查

**Files:**
- Modify: `.github/workflows/quality.yml`
- Modify: `package.json`
- Modify: `apps/agent-runtime/package.json`
- Create: `apps/agent-runtime/scripts/package.mjs`
- Create: `apps/agent-runtime/tests/package.test.ts`

- [ ] **Step 1: 写发行包失败测试**

```ts
it("ships provenance but keeps it out of the browser bundle", async () => {
  const files = await packageFiles();
  expect(files).toContain("THIRD_PARTY_NOTICES.md");
  expect(files).toContain("licenses/claudian-MIT.txt");
  expect(await webBundleContains("d190786d11cc0b067475dcffbf8c334ee565d208")).toBe(false);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm --dir apps/agent-runtime test -- package`

Expected: FAIL，因为 package script 和发行检查尚不存在。

- [ ] **Step 3: 增加 CI jobs**

保留现有 API/Web/Docker jobs；新增 `agent-runtime-linux`（Node 24）、`agent-runtime-windows`（Node 24）、`claudian-conformance`、`vault-migration-smoke`。Runtime jobs 执行 frozen install、test、typecheck、lint、package 和 smoke；Windows job验证 PowerShell/路径/进程树，Linux job 验证 symlink/信号。Web job继续 Node 22.22.2 或 24，Runtime job固定 Node 24。

- [ ] **Step 4: 实现发行包**

package script 复制 compiled runtime、package metadata、`UPSTREAM.md`、`PATCHES.md`、`FILES.json`、`THIRD_PARTY_NOTICES.md` 和 licenses；生成 hash manifest。不得复制 `.env`、token、Vault 内容、session JSONL 或 sidecar。

- [ ] **Step 5: 运行本地 CI 等价命令**

Run: `pnpm --dir apps/agent-runtime test && pnpm --dir apps/agent-runtime typecheck && pnpm --dir apps/agent-runtime lint && pnpm --dir apps/agent-runtime package`

Expected: PASS，发行包 provenance 完整且无 secret/user data。

Run: `python -m pytest apps/api/tests/test_semantic_index_plan.py apps/api/tests/test_semantic_index_worker.py apps/api/tests/test_vault_migration.py apps/api/tests/test_agent_diagnostics.py apps/api/tests/test_compose_security.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add .github/workflows/quality.yml package.json apps/agent-runtime
git commit -m "ci: add cross-platform agent runtime release gates"
```
