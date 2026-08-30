# Agent Control Plane and Vault Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 FastAPI 中建立 Agent 会话、事件、capability、审计和永久 Vault 控制面，使 Runtime 获得用户有权读取/写入的完整知识库范围，同时不绕过现有 ACL。

**Architecture:** 新增 `agent` 与 `vault` 边界模块；FastAPI 继续拥有身份、ACL 和数据库事务，Runtime 只持有短期签名 capability。Vault 文件正文为事实来源，数据库保留稳定文件身份、revision、change set、同步 cursor、事件和搜索投影；所有 Agent 故障以结构化错误隔离于非 Agent API。

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL, httpx, WebSocket

---

### Task 1: 新增 Agent/Vault 数据模型和迁移

**Files:**
- Create: `apps/api/src/tutor_api/agent/__init__.py`
- Create: `apps/api/src/tutor_api/agent/models.py`
- Create: `apps/api/src/tutor_api/vault/__init__.py`
- Create: `apps/api/src/tutor_api/vault/models.py`
- Modify: `apps/api/src/tutor_api/knowledge/models.py:425-660`
- Create: `apps/api/migrations/versions/0016_agent_workspace.py`
- Modify: `apps/api/migrations/env.py`
- Create: `apps/api/tests/test_agent_models.py`
- Create: `apps/api/tests/test_vault_models.py`
- Modify: `apps/api/tests/test_schema.py`

- [ ] **Step 1: 写模型失败测试**

```python
def test_agent_event_sequence_is_unique_per_session(session, agent_session):
    session.add_all([
        AgentSessionEvent(session_id=agent_session.id, sequence=1, event_id=uuid4(), event_type="turn_started", payload={}, idempotency_key="a"),
        AgentSessionEvent(session_id=agent_session.id, sequence=1, event_id=uuid4(), event_type="model_text_delta", payload={}, idempotency_key="b"),
    ])
    with pytest.raises(IntegrityError):
        session.flush()


def test_vault_file_path_is_unique_per_knowledge_base(session, knowledge_base):
    first = VaultFile(knowledge_base_id=knowledge_base.id, relative_path="notes/a.md", file_kind="markdown", content_hash="0" * 64)
    second = VaultFile(knowledge_base_id=knowledge_base.id, relative_path="notes/a.md", file_kind="markdown", content_hash="1" * 64)
    session.add_all([first, second])
    with pytest.raises(IntegrityError):
        session.flush()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_agent_models.py apps/api/tests/test_vault_models.py -q`

Expected: FAIL，因为模型尚不存在。

- [ ] **Step 3: 实现 Agent 模型**

```python
class AgentSessionState(StrEnum):
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    STOPPED = "stopped"
    FAILED = "failed"
    ARCHIVED = "archived"

class AgentSession(Base):
    __tablename__ = "agent_sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    knowledge_base_id: Mapped[UUID] = mapped_column(index=True)
    provider: Mapped[str] = mapped_column(String(100), default="claude")
    model: Mapped[str] = mapped_column(String(255))
    permission_mode: Mapped[str] = mapped_column(String(100), default="bypassPermissions")
    native_session_id: Mapped[str | None] = mapped_column(String(512), index=True)
    state: Mapped[AgentSessionState] = mapped_column(_enum(AgentSessionState, "agent_session_state"))
    parent_session_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_sessions.id"))
    forked_from_turn_id: Mapped[UUID | None] = mapped_column()
    rewind_checkpoint_id: Mapped[str | None] = mapped_column(String(512))
    last_event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    recovery: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=dict
    )
```

同文件完整定义 `AgentTurn`、`AgentSessionEvent`、`AgentWorkspaceGrant`、`AgentAuditEvent`、`AgentProviderSetting`、`AgentUsageRecord`。约束包括：session 所有权复合 FK、`(session_id, sequence)` 唯一、event_id 唯一、idempotency_key 唯一、token/计数非负、secret 仅保存引用。

- [ ] **Step 4: 实现 Vault 模型并扩展知识模型**

`VaultFile`、`VaultChangeSet`、`VaultChangeEntry`、`VaultSyncCursor`、`SemanticIndexPlan` 使用 UUID、knowledge base/space 复合约束、规范化相对路径、before/after hash、状态、重试和审计关联。按设计向 `MarkdownNote`、`MarkdownRevision`、`IndexVersion` 增加字段；新增字段先 nullable 或有安全 server default，使现有数据可无停机升级。

- [ ] **Step 5: 编写 0016 migration**

迁移先建 Agent/Vault 表，再加现有表列和索引；downgrade 只删除新增投影和列，不删除旧 Tutor 表或旧正文。PostgreSQL JSON 使用 JSONB variant，SQLite 测试使用 JSON。

- [ ] **Step 6: 运行测试和迁移往返**

Run: `python -m pytest apps/api/tests/test_agent_models.py apps/api/tests/test_vault_models.py apps/api/tests/test_schema.py -q`

Expected: PASS。

Run: `Push-Location apps/api; python -m alembic upgrade head; Pop-Location`

Expected: schema head 为 `0016_agent_workspace`，既有数据表仍存在。

- [ ] **Step 7: 提交**

```powershell
git add apps/api/src/tutor_api/agent apps/api/src/tutor_api/vault apps/api/src/tutor_api/knowledge/models.py apps/api/migrations apps/api/tests
git commit -m "feat: add agent and vault persistence models"
```

### Task 2: 签发完整 ACL capability

**Files:**
- Modify: `apps/api/src/tutor_api/knowledge/access.py:68-158`
- Create: `apps/api/src/tutor_api/agent/capability.py`
- Modify: `apps/api/src/tutor_api/core/config.py:90-150`
- Create: `apps/api/tests/test_agent_capability.py`
- Modify: `apps/api/tests/test_config.py`

- [ ] **Step 1: 写授权范围失败测试**

```python
def test_capability_contains_every_readable_knowledge_base_without_cross_tenant_access(
    session, user, own_personal_kb, joined_classroom_kb, foreign_kb, settings
):
    token = issue_workspace_capability(session, user, session_id=uuid4(), settings=settings)
    payload = verify_workspace_capability(token, settings=settings)
    assert {grant["knowledge_base_id"] for grant in payload["grants"]} == {
        str(own_personal_kb.id), str(joined_classroom_kb.id)
    }
    assert str(foreign_kb.id) not in token
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_agent_capability.py apps/api/tests/test_config.py -q`

Expected: FAIL，因为 capability 模块和新配置尚不存在。

- [ ] **Step 3: 定义配置**

```python
agent_runtime_url: AnyHttpUrl = "http://127.0.0.1:8765"
agent_runtime_token: SecretStr
agent_capability_secret: SecretStr
agent_capability_ttl_seconds: int = Field(default=300, ge=30, le=3600)
agent_vault_root: Path
agent_sidecar_root: Path
agent_provider: str = "claude"
agent_model: str
agent_context_window: int = Field(default=1_000_000, ge=32_000)
agent_inline_event_bytes: int = Field(default=262_144, ge=16_384)
agent_runtime_timeout_seconds: float = Field(default=30.0, ge=1.0)
```

移除 `tutor_prompt_max_characters`、`tutor_history_messages`、`tutor_knowledge_sources`、`tutor_knowledge_base_limit`、`tutor_web_search_max_results` 等新加固定限制；保留旧 Tutor 运行所需的兼容默认，但它们不得进入 Agent request。

- [ ] **Step 4: 实现 capability 签发和校验**

```python
@dataclass(frozen=True)
class WorkspaceGrant:
    knowledge_base_id: UUID
    space_id: UUID
    vault_root: str
    read: bool
    write: bool
    delete: bool


def issue_workspace_capability(session: Session, user: User, *, session_id: UUID, settings: Settings) -> str:
    readable = list_readable_knowledge_bases(session, user)
    grants = [grant_for(user, knowledge_base, settings.agent_vault_root) for knowledge_base in readable]
    payload = capability_payload(user.id, session_id, grants, expires_in=settings.agent_capability_ttl_seconds)
    return sign_canonical_json(payload, settings.agent_capability_secret.get_secret_value())
```

`grant_for` 复用 `get_writable_knowledge_base` 的角色语义确定 write/delete；个人库 owner 可写，班级权限按现有角色规则，不通过异常探测扩大权限。签名使用 canonical JSON + HMAC-SHA256 + constant-time compare。

- [ ] **Step 5: 运行 ACL 测试**

Run: `python -m pytest apps/api/tests/test_agent_capability.py apps/api/tests/test_knowledge_bases.py apps/api/tests/test_classrooms.py -q`

Expected: PASS；个人、已加入班级、退出班级、归档库、跨用户和过期 token 均符合 ACL。

- [ ] **Step 6: 提交**

```powershell
git add apps/api/src/tutor_api/knowledge/access.py apps/api/src/tutor_api/agent/capability.py apps/api/src/tutor_api/core/config.py apps/api/tests
git commit -m "feat: issue full-workspace agent capabilities"
```

### Task 3: 实现 Runtime client、事件持久化和 sidecar 代理

**Files:**
- Create: `apps/api/src/tutor_api/agent/runtime_client.py`
- Create: `apps/api/src/tutor_api/agent/event_store.py`
- Create: `apps/api/src/tutor_api/agent/schemas.py`
- Create: `apps/api/tests/test_agent_runtime_client.py`
- Create: `apps/api/tests/test_agent_event_store.py`

- [ ] **Step 1: 写幂等和故障失败测试**

```python
def test_duplicate_runtime_event_is_acknowledged_once(session, agent_session, event_payload):
    first = persist_runtime_event(session, event_payload)
    second = persist_runtime_event(session, event_payload)
    assert first.id == second.id
    assert session.scalar(select(func.count(AgentSessionEvent.id))) == 1


def test_runtime_unavailable_has_stable_error(fake_httpx):
    fake_httpx.raise_connect_error()
    with pytest.raises(RuntimeUnavailable) as error:
        runtime_client.start_turn(request)
    assert error.value.code == "runtime_unavailable"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_agent_runtime_client.py apps/api/tests/test_agent_event_store.py -q`

Expected: FAIL，因为 client/store 尚不存在。

- [ ] **Step 3: 实现 RuntimeClient**

```python
class RuntimeStartRequest(BaseModel):
    session_id: UUID
    turn_id: UUID
    input: list[dict[str, Any]]
    workspace_roots: list[str]
    provider: str
    model: str
    permission_mode: Literal["bypassPermissions"]
    capability: str
    callback_url: AnyHttpUrl
    idempotency_key: str

class RuntimeStartResponse(BaseModel):
    execution_id: str
    native_session_id: str
    accepted_sequence: int

class RuntimeForkResponse(BaseModel):
    native_session_id: str

class RuntimeHealth(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    protocol_version: str
    upstream_commit: str

class RuntimeClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._base_url = str(settings.agent_runtime_url).rstrip("/")
        self._headers = {"Authorization": f"Bearer {settings.agent_runtime_token.get_secret_value()}"}

    async def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await self._client.post(f"{self._base_url}{path}", json=payload, headers=self._headers)
            response.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as error:
            raise RuntimeUnavailable(code="runtime_unavailable") from error
        return response.json()

    async def start_turn(self, payload: RuntimeStartRequest) -> RuntimeStartResponse:
        return RuntimeStartResponse.model_validate(await self._post("/v1/sessions/start", payload.model_dump(mode="json")))

    async def stop(self, session_id: UUID) -> None:
        await self._post(f"/v1/sessions/{session_id}/stop")

    async def resume(self, session_id: UUID) -> None:
        await self._post(f"/v1/sessions/{session_id}/resume")

    async def rewind(self, session_id: UUID, checkpoint_id: str) -> None:
        await self._post(f"/v1/sessions/{session_id}/rewind", {"checkpoint_id": checkpoint_id})

    async def fork(self, session_id: UUID, checkpoint_id: str) -> RuntimeForkResponse:
        return RuntimeForkResponse.model_validate(
            await self._post(f"/v1/sessions/{session_id}/fork", {"checkpoint_id": checkpoint_id})
        )

    async def health(self) -> RuntimeHealth:
        try:
            response = await self._client.get(f"{self._base_url}/v1/health")
            response.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as error:
            raise RuntimeUnavailable(code="runtime_unavailable") from error
        return RuntimeHealth.model_validate(response.json())

    async def get_sidecar(self, sidecar_id: UUID) -> AsyncIterator[bytes]:
        try:
            async with self._client.stream(
                "GET", f"{self._base_url}/v1/sidecars/{sidecar_id}", headers=self._headers
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
        except (httpx.ConnectError, httpx.TimeoutException) as error:
            raise RuntimeUnavailable(code="runtime_unavailable") from error
```

httpx client 仅访问配置的 loopback URL，附 Runtime bearer token 和 correlation ID；连接错误映射为 503 `runtime_unavailable`，不得影响 FastAPI app lifespan 或其他 router。

- [ ] **Step 4: 实现 EventStore**

在单个数据库事务中：锁定 `AgentSession`；如果 idempotency_key 已存在则返回原 ACK；要求 sequence 等于 `last_event_sequence + 1`，或已存在同 sequence/same event；插入事件；更新 session/turn 状态和 last sequence；写 usage/audit 派生记录；commit 后返回 `{persisted:true,sequence}`。gap 返回 `event_sequence_gap` 并要求 Runtime 从 cursor 重放。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest apps/api/tests/test_agent_runtime_client.py apps/api/tests/test_agent_event_store.py -q`

Expected: PASS，包括 duplicate、gap、out-of-order、large sidecar、redaction 和连接失败。

- [ ] **Step 6: 提交**

```powershell
git add apps/api/src/tutor_api/agent apps/api/tests/test_agent_runtime_client.py apps/api/tests/test_agent_event_store.py
git commit -m "feat: persist replayable agent runtime events"
```

### Task 4: 实现 Agent REST/WebSocket API 和 legacy history 投影

**Files:**
- Create: `apps/api/src/tutor_api/agent/service.py`
- Create: `apps/api/src/tutor_api/agent/router.py`
- Create: `apps/api/src/tutor_api/agent/legacy.py`
- Modify: `apps/api/src/tutor_api/main.py:40-140`
- Create: `apps/api/tests/test_agent_api.py`
- Create: `apps/api/tests/test_agent_websocket.py`
- Modify: `apps/api/tests/test_tutor.py`

- [ ] **Step 1: 写 session/API 失败测试**

```python
def test_create_session_uses_all_readable_kbs_and_million_context(client, login, knowledge_base):
    response = client.post("/api/v1/agent/sessions", json={
        "knowledge_base_id": str(knowledge_base.id), "provider": "claude", "model": "claude", "context_window": 1_000_000
    })
    assert response.status_code == 201
    assert response.json()["permission_mode"] == "bypassPermissions"


def test_foreign_session_is_not_found(client, foreign_session):
    assert client.get(f"/api/v1/agent/sessions/{foreign_session.id}").status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_agent_api.py apps/api/tests/test_agent_websocket.py -q`

Expected: FAIL，因为 router 尚不存在。

- [ ] **Step 3: 实现 `/api/v1/agent/*`**

路由包括 session create/list/get/archive；turn send；Stop/Resume/Rewind/Fork；events cursor list；WebSocket `/api/v1/agent/ws/{session_id}?after=<sequence>`；sidecar preview；provider/settings；MCP/Skills；diagnostics；Runtime event callback。每个用户路由先验证 session ownership 和 knowledge base ACL；Runtime callback 使用独立 bearer token，不依赖浏览器 cookie。

- [ ] **Step 4: 实现 WebSocket replay**

连接后先从数据库发送 `sequence > after` 的持久事件，再订阅应用内 broadcaster；每次发送前按 session owner 验证。断线不取消 Runtime turn；重连从 cursor 补发。队列溢出关闭连接并给出可重连 code，不删除数据库事件。

- [ ] **Step 5: 实现旧 Tutor history 重建**

`legacy.py` 把旧 `TutorConversation/TutorMessage` 映射为只读 legacy session summary；不伪造 tool events，不删除旧表。新 Agent 列表可显示“旧助教记录”并允许打开文本/citation，但不能 Resume 为 Claude 原生 session。

- [ ] **Step 6: 运行测试**

Run: `python -m pytest apps/api/tests/test_agent_api.py apps/api/tests/test_agent_websocket.py apps/api/tests/test_tutor.py -q`

Expected: PASS，包括 refresh replay、foreign session 404、idempotent send、Stop/Resume/Rewind/Fork、Runtime 503 和 legacy history。

- [ ] **Step 7: 提交**

```powershell
git add apps/api/src/tutor_api/agent apps/api/src/tutor_api/main.py apps/api/tests
git commit -m "feat: expose agent sessions and replay APIs"
```

### Task 5: 实现永久 Vault 原子存储与 CRUD

**Files:**
- Create: `apps/api/src/tutor_api/vault/storage.py`
- Create: `apps/api/src/tutor_api/vault/service.py`
- Create: `apps/api/src/tutor_api/vault/router.py`
- Modify: `apps/api/src/tutor_api/main.py`
- Create: `apps/api/tests/test_vault_storage.py`
- Create: `apps/api/tests/test_vault_api.py`

- [ ] **Step 1: 写 Vault 为真和冲突失败测试**

```python
def test_vault_content_wins_but_database_revision_is_preserved(vault_service, note):
    vault_service.external_write(note.path, "vault version")
    result = vault_service.reconcile(note.id, database_markdown="database version")
    assert result.markdown == "vault version"
    assert result.conflict_revision.markdown == "database version"


def test_create_move_delete_updates_stable_vault_file_id(vault_service):
    created = vault_service.create("a.md", "alpha")
    moved = vault_service.move("a.md", "folder/b.md", expected_hash=created.after_hash)
    assert moved.vault_file_id == created.vault_file_id
    vault_service.delete("folder/b.md", expected_hash=moved.after_hash)
    assert vault_service.get_file(created.vault_file_id).is_tombstoned is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_vault_storage.py apps/api/tests/test_vault_api.py -q`

Expected: FAIL，因为 Vault storage/service 尚不存在。

- [ ] **Step 3: 实现路径布局和原子操作**

根布局固定为 `<AGENT_VAULT_ROOT>/spaces/<space-id>/<knowledge-base-id>/`。所有输入先按 POSIX 相对路径规范化，再在 Windows/Linux 上 resolve；拒绝绝对路径、`..`、device path、UNC、symlink/junction 逃逸。写入采用同目录临时文件 + fsync + replace，move 保留 `VaultFile.id`，delete 先写 change set 和 tombstone，再移除正文。

- [ ] **Step 4: 实现 revision/change set**

每个 API/Agent/Shell/Git/external edit 变化归入 `VaultChangeSet`，每个文件变化保存 before/after hash、source、session/turn/tool call。数据库旧正文与 Vault 冲突时：先创建 `MarkdownRevision(change_source="conflict_backup")` 保存数据库内容，再以 Vault 生成新 active revision，并写审计。

- [ ] **Step 5: 实现用户 Vault API**

提供 list/read/create/update/move/delete 和 change-set status；读取要求 `get_readable_knowledge_base`，写/移动/删除要求 `get_writable_knowledge_base`。API 返回 stable `vault_file_id`、relative_path、hash、revision 和 sync/index 状态。

- [ ] **Step 6: 运行测试**

Run: `python -m pytest apps/api/tests/test_vault_storage.py apps/api/tests/test_vault_api.py apps/api/tests/test_knowledge_markdown.py -q`

Expected: PASS；原子写、冲突备份、稳定 ID、跨盘拒绝、ACL 和旧 Markdown API 回归通过。

- [ ] **Step 7: 提交**

```powershell
git add apps/api/src/tutor_api/vault apps/api/src/tutor_api/main.py apps/api/tests
git commit -m "feat: make permanent vault the markdown source of truth"
```

### Task 6: 实现 watcher、hash 去环和恢复 cursor

**Files:**
- Create: `apps/api/src/tutor_api/vault/sync.py`
- Modify: `apps/api/src/tutor_api/knowledge/worker.py`
- Modify: `apps/api/src/tutor_api/worker_main.py`
- Create: `apps/api/tests/test_vault_sync.py`
- Modify: `apps/api/tests/test_knowledge_worker.py`

- [ ] **Step 1: 写 watcher 失败测试**

```python
def test_external_file_is_auto_enrolled_once(sync_service, vault_root):
    (vault_root / "new-concept.md").write_text("# New concept", encoding="utf-8")
    sync_service.scan()
    sync_service.scan()
    assert sync_service.files("new-concept.md").count == 1
    assert sync_service.pending_index_jobs("new-concept.md").count == 1


def test_runtime_echo_hash_does_not_create_sync_loop(sync_service, change_set):
    sync_service.observe(change_set.path, change_set.after_hash)
    assert sync_service.created_change_sets == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_vault_sync.py -q`

Expected: FAIL，因为 sync service 尚不存在。

- [ ] **Step 3: 实现变化归并**

Watcher 事件先按 knowledge base 和 debounce window 归并，再以完整扫描/hash 校正丢失或重复 OS 事件。所有支持文件自动建立 `VaultFile`，AI 不决定是否收录。rename 优先使用 file identity/old-new hash 匹配，无法确认时记录 delete+create；hash 与已知 change set after_hash 相同则只推进 cursor，不生成回声 change set。

- [ ] **Step 4: 扩展 durable worker**

为现有数据库 lease 队列加入 `vault_scan`、`vault_project`、`semantic_plan` job kind；handler 必须幂等、可重试、支持 dead-letter 状态。`VaultSyncCursor` 保存 watcher/database/index cursor、pending count、last success/error 和 full-scan flag；Runtime 或 API 重启后从 cursor 恢复。

- [ ] **Step 5: 运行同步和 worker 测试**

Run: `python -m pytest apps/api/tests/test_vault_sync.py apps/api/tests/test_knowledge_worker.py apps/api/tests/test_knowledge_markdown_worker.py -q`

Expected: PASS，包括 create/edit/rename/move/delete、storm debounce、丢事件全扫、hash 去环、重试和重启恢复。

- [ ] **Step 6: 运行控制面回归**

Run: `python -m pytest apps/api/tests/test_agent_models.py apps/api/tests/test_agent_capability.py apps/api/tests/test_agent_runtime_client.py apps/api/tests/test_agent_event_store.py apps/api/tests/test_agent_api.py apps/api/tests/test_agent_websocket.py apps/api/tests/test_vault_storage.py apps/api/tests/test_vault_api.py apps/api/tests/test_vault_sync.py -q`

Expected: 全部通过。

- [ ] **Step 7: 提交**

```powershell
git add apps/api/src/tutor_api/vault apps/api/src/tutor_api/knowledge apps/api/src/tutor_api/worker_main.py apps/api/tests
git commit -m "feat: synchronize vault changes into the knowledge control plane"
```
