from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from tutor_api.agent.diagnostics import collect_agent_diagnostics
from tutor_api.agent.event_store import EventStoreError, acknowledge_runtime_event, list_events
from tutor_api.agent.legacy import get_legacy_session, list_legacy_sessions
from tutor_api.agent.models import AgentProviderSetting, AgentSession, AgentSessionState
from tutor_api.agent.runtime_client import RuntimeClient, RuntimeErrorBase
from tutor_api.agent.schemas import (
    AGENT_CONTEXT_WINDOW,
    AGENT_MODEL,
    AGENT_PROVIDER,
    AgentWorkspaceSettings,
    RewindRequest,
    RuntimeEvent,
    SessionCreateRequest,
    TurnCreateRequest,
)
from tutor_api.agent.service import create_session, fork_session, owned_session, prepare_turn
from tutor_api.core.database import session_scope
from tutor_api.identity.models import User, UserSession
from tutor_api.identity.router import CurrentUser, _session_factory

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])
_subscribers: dict[UUID, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)


def _runtime(request: Request) -> RuntimeClient:
    client = getattr(request.app.state, "agent_runtime_client", None)
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="runtime_unavailable",
            headers={"Retry-After": "1"},
        )
    return client


def _response(item: AgentSession) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": "AI 助教会话",
        "knowledge_base_id": item.knowledge_base_id,
        "space_id": item.space_id,
        "provider": item.provider,
        "model": item.model,
        "permission_mode": item.permission_mode,
        "native_session_id": item.native_session_id,
        "state": item.state.value,
        "parent_session_id": item.parent_session_id,
        "last_event_sequence": item.last_event_sequence,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "legacy": False,
        "is_legacy": False,
    }


def _event(item) -> dict[str, Any]:
    timestamp = item.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return {
        "session_id": str(item.session_id),
        "sequence": item.sequence,
        "event_id": str(item.event_id),
        "event_type": item.event_type,
        "timestamp": timestamp.isoformat(),
        "payload": item.payload,
        "turn_id": str(item.turn_id) if item.turn_id else None,
        "tool_call_id": item.tool_call_id,
        "subagent_id": item.subagent_id,
        "completed": item.completed,
        "sidecar_reference": item.sidecar_reference,
        "idempotency_key": item.idempotency_key,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _runtime_error(error: RuntimeErrorBase) -> HTTPException:
    status_code = 503 if error.code == "runtime_unavailable" else error.status_code
    return HTTPException(
        status_code=status_code,
        detail=error.code,
        headers={"Retry-After": "1"} if status_code == 503 else None,
    )


@router.post("/sessions", status_code=201)
def post_session(payload: SessionCreateRequest, request: Request, current_user: CurrentUser):
    with session_scope(_session_factory(request)) as db:
        return _response(create_session(db, current_user, payload))


@router.get("/sessions")
def get_sessions(request: Request, current_user: CurrentUser, include_legacy: bool = True):
    with session_scope(_session_factory(request)) as db:
        rows = db.scalars(
            select(AgentSession)
            .where(AgentSession.user_id == current_user.id)
            .order_by(AgentSession.updated_at.desc())
        ).all()
        result = [_response(row) for row in rows]
        if include_legacy:
            result.extend(list_legacy_sessions(db, current_user.id))
        return result


@router.get("/sessions/{session_id}")
def get_session(session_id: UUID, request: Request, current_user: CurrentUser):
    with session_scope(_session_factory(request)) as db:
        try:
            return _response(owned_session(db, current_user, session_id))
        except HTTPException as error:
            legacy = get_legacy_session(db, current_user.id, session_id)
            if legacy is not None:
                return legacy
            raise error


@router.delete("/sessions/{session_id}", status_code=204)
def archive_session(session_id: UUID, request: Request, current_user: CurrentUser):
    with session_scope(_session_factory(request)) as db:
        owner = owned_session(db, current_user, session_id)
        owner.state = AgentSessionState.ARCHIVED


@router.post("/sessions/{session_id}/turns", status_code=202)
async def post_turn(
    session_id: UUID, payload: TurnCreateRequest, request: Request, current_user: CurrentUser
):
    callback = str(request.url_for("runtime_event_callback"))
    with session_scope(_session_factory(request)) as db:
        turn, runtime_payload = prepare_turn(
            db, current_user, session_id, payload, request.app.state.settings, callback
        )
        turn_id = turn.id
    try:
        accepted = await _runtime(request).start_turn(
            runtime_payload, request_id=request.headers.get("x-request-id")
        )
    except RuntimeErrorBase as error:
        with session_scope(_session_factory(request)) as db:
            owner = owned_session(db, current_user, session_id)
            owner.state = AgentSessionState.FAILED
        raise _runtime_error(error) from None
    with session_scope(_session_factory(request)) as db:
        owner = owned_session(db, current_user, session_id)
        owner.native_session_id = accepted.native_session_id
    return {"turn_id": turn_id, **accepted.model_dump(mode="json")}


@router.post("/sessions/{session_id}/stop", status_code=204)
async def stop(session_id: UUID, request: Request, current_user: CurrentUser):
    with session_scope(_session_factory(request)) as db:
        owned_session(db, current_user, session_id)
    try:
        await _runtime(request).stop(session_id)
    except RuntimeErrorBase as error:
        raise _runtime_error(error) from None
    with session_scope(_session_factory(request)) as db:
        owned_session(db, current_user, session_id).state = AgentSessionState.STOPPED


@router.post("/sessions/{session_id}/resume", status_code=204)
async def resume(session_id: UUID, request: Request, current_user: CurrentUser):
    with session_scope(_session_factory(request)) as db:
        owner = owned_session(db, current_user, session_id)
        if owner.native_session_id is None:
            raise HTTPException(status_code=409, detail="agent_session_not_resumable")
    try:
        await _runtime(request).resume(session_id)
    except RuntimeErrorBase as error:
        raise _runtime_error(error) from None
    with session_scope(_session_factory(request)) as db:
        owned_session(db, current_user, session_id).state = AgentSessionState.RUNNING


@router.post("/sessions/{session_id}/rewind", status_code=204)
async def rewind(
    session_id: UUID, payload: RewindRequest, request: Request, current_user: CurrentUser
):
    with session_scope(_session_factory(request)) as db:
        owned_session(db, current_user, session_id)
    try:
        await _runtime(request).rewind(session_id, payload.checkpoint_id)
    except RuntimeErrorBase as error:
        raise _runtime_error(error) from None
    with session_scope(_session_factory(request)) as db:
        owned_session(db, current_user, session_id).rewind_checkpoint_id = payload.checkpoint_id


@router.post("/sessions/{session_id}/fork", status_code=201)
async def fork(
    session_id: UUID, payload: RewindRequest, request: Request, current_user: CurrentUser
):
    with session_scope(_session_factory(request)) as db:
        source = owned_session(db, current_user, session_id)
    try:
        result = await _runtime(request).fork(session_id, payload.checkpoint_id)
    except RuntimeErrorBase as error:
        raise _runtime_error(error) from None
    with session_scope(_session_factory(request)) as db:
        source = owned_session(db, current_user, session_id)
        return _response(
            fork_session(db, current_user, source, result.native_session_id, payload.checkpoint_id)
        )


@router.get("/sessions/{session_id}/events")
def events(
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    after: int = Query(default=0, ge=0),
):
    with session_scope(_session_factory(request)) as db:
        owned_session(db, current_user, session_id)
        return [_event(item) for item in list_events(db, session_id, after=after)]


def _expected_runtime_token(request: Request) -> str:
    value = getattr(request.app.state.settings, "agent_runtime_token", "")
    getter = getattr(value, "get_secret_value", None)
    return getter() if getter else str(value)


@router.post("/runtime/events", name="runtime_event_callback")
async def runtime_event_callback(
    event: RuntimeEvent, request: Request, authorization: str | None = Header(default=None)
):
    expected = f"Bearer {_expected_runtime_token(request)}"
    if not authorization or not __import__("hmac").compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="runtime_unauthorized")
    try:
        with session_scope(_session_factory(request)) as db:
            ack = acknowledge_runtime_event(db, event)
            stored = db.scalar(
                select(
                    __import__(
                        "tutor_api.agent.models", fromlist=["AgentSessionEvent"]
                    ).AgentSessionEvent
                ).where(
                    __import__(
                        "tutor_api.agent.models", fromlist=["AgentSessionEvent"]
                    ).AgentSessionEvent.session_id
                    == event.session_id,
                    __import__(
                        "tutor_api.agent.models", fromlist=["AgentSessionEvent"]
                    ).AgentSessionEvent.sequence
                    == event.sequence,
                )
            )
            message = _event(stored)
    except EventStoreError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": error.code, "expected_sequence": error.expected_sequence},
        ) from None
    for queue in tuple(_subscribers[event.session_id]):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            _subscribers[event.session_id].discard(queue)
    return ack.model_dump()


@router.get("/sidecars/{sidecar_id}")
async def sidecar(sidecar_id: UUID, request: Request, current_user: CurrentUser):
    del current_user
    iterator = _runtime(request).get_sidecar(sidecar_id, range_header=request.headers.get("range"))
    return StreamingResponse(
        iterator,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )


def _default_workspace_settings(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "provider": settings.agent_provider,
        "model": settings.agent_model,
        "context_window": settings.agent_context_window,
        "permission_mode": "bypassPermissions",
        "workspace_roots": [str(request.app.state.vault_root)],
        "mcp_enabled": bool(settings.agent_mcp_config_paths),
        "skills_enabled": bool(settings.agent_skill_paths),
        "subagents_enabled": settings.agent_subagent_concurrency > 0,
        "web_enabled": True,
    }


def _workspace_settings_response(
    request: Request, row: AgentProviderSetting | None
) -> dict[str, Any]:
    result = _default_workspace_settings(request)
    if (
        row is not None
        and row.enabled
        and row.provider == AGENT_PROVIDER
        and row.model == AGENT_MODEL
        and row.context_window == AGENT_CONTEXT_WINDOW
    ):
        result.update(
            {
                "provider": row.provider,
                "model": row.model,
                "context_window": row.context_window,
            }
        )
    return result


def _active_workspace_setting(
    rows: list[AgentProviderSetting], current_user: CurrentUser
) -> AgentProviderSetting | None:
    user_rows = [
        row
        for row in rows
        if row.user_id == current_user.id
        and row.enabled
        and row.provider == AGENT_PROVIDER
        and row.model == AGENT_MODEL
        and row.context_window == AGENT_CONTEXT_WINDOW
    ]
    if user_rows:
        return user_rows[0]
    return next(
        (
            row
            for row in rows
            if row.user_id is None
            and row.enabled
            and row.provider == AGENT_PROVIDER
            and row.model == AGENT_MODEL
            and row.context_window == AGENT_CONTEXT_WINDOW
        ),
        None,
    )


@router.get("/settings")
def settings(request: Request, current_user: CurrentUser):
    with session_scope(_session_factory(request)) as db:
        rows = db.scalars(
            select(AgentProviderSetting)
            .where(
                (AgentProviderSetting.user_id == current_user.id)
                | (AgentProviderSetting.user_id.is_(None))
            )
            .order_by(AgentProviderSetting.updated_at.desc(), AgentProviderSetting.provider)
        ).all()
        return _workspace_settings_response(
            request, _active_workspace_setting(list(rows), current_user)
        )


@router.put("/settings")
def update_workspace_settings(
    payload: AgentWorkspaceSettings, request: Request, current_user: CurrentUser
):
    values = payload.model_dump()
    provider = values["provider"]
    if provider != AGENT_PROVIDER:
        raise HTTPException(status_code=422, detail="agent_provider_must_be_faro")
    with session_scope(_session_factory(request)) as db:
        row = db.scalar(
            select(AgentProviderSetting).where(
                AgentProviderSetting.user_id == current_user.id,
                AgentProviderSetting.provider == provider,
            )
        )
        if row is None:
            row = AgentProviderSetting(
                user_id=current_user.id,
                provider=provider,
                model=values["model"],
                context_window=values["context_window"],
            )
            db.add(row)
        row.model = AGENT_MODEL
        row.context_window = AGENT_CONTEXT_WINDOW
        row.enabled = True
        row.config_version = (row.config_version or 0) + 1
        db.flush()
        return _workspace_settings_response(request, row)


@router.put("/settings/{provider}")
def update_settings(
    provider: str, payload: dict[str, Any], request: Request, current_user: CurrentUser
):
    if provider != AGENT_PROVIDER:
        raise HTTPException(status_code=422, detail="agent_provider_must_be_faro")
    allowed = {"model", "context_window", "available_tools", "enabled", "secret_reference"}
    if set(payload) - allowed:
        raise HTTPException(status_code=422, detail="agent_setting_invalid")
    if payload.get("model", AGENT_MODEL) != AGENT_MODEL:
        raise HTTPException(status_code=422, detail="agent_model_must_be_gemini_3_7_flash")
    if payload.get("context_window", AGENT_CONTEXT_WINDOW) != AGENT_CONTEXT_WINDOW:
        raise HTTPException(status_code=422, detail="agent_context_window_must_be_32000")
    with session_scope(_session_factory(request)) as db:
        row = db.scalar(
            select(AgentProviderSetting).where(
                AgentProviderSetting.user_id == current_user.id,
                AgentProviderSetting.provider == provider,
            )
        )
        if row is None:
            row = AgentProviderSetting(
                user_id=current_user.id,
                provider=provider,
                model=AGENT_MODEL,
                context_window=AGENT_CONTEXT_WINDOW,
            )
            db.add(row)
        for key, value in payload.items():
            setattr(row, key, value)
        row.model = AGENT_MODEL
        row.context_window = AGENT_CONTEXT_WINDOW
        row.config_version = (row.config_version or 0) + 1
        db.flush()
        return {
            "provider": row.provider,
            "model": row.model,
            "context_window": row.context_window,
            "available_tools": row.available_tools,
            "enabled": row.enabled,
            "config_version": row.config_version,
        }


@router.get("/mcp")
async def mcp(request: Request, current_user: CurrentUser):
    del current_user
    try:
        return await _runtime(request).proxy("GET", "/v1/mcp")
    except RuntimeErrorBase as error:
        raise _runtime_error(error) from None


@router.get("/skills")
async def skills(request: Request, current_user: CurrentUser):
    del current_user
    try:
        return await _runtime(request).proxy("GET", "/v1/skills")
    except RuntimeErrorBase as error:
        raise _runtime_error(error) from None


@router.get("/diagnostics")
async def diagnostics(request: Request, current_user: CurrentUser):
    del current_user
    return await collect_agent_diagnostics(request)


def _websocket_user(websocket: WebSocket) -> User | None:
    token = websocket.cookies.get(websocket.app.state.settings.session_cookie_name)
    if not token or websocket.app.state.session_factory is None:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    with session_scope(websocket.app.state.session_factory) as db:
        user_session = db.scalar(select(UserSession).where(UserSession.token_digest == digest))
        if user_session is None or user_session.revoked_at is not None:
            return None
        expires = user_session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= datetime.now(UTC):
            return None
        user = db.get(User, user_session.user_id)
        if user:
            db.expunge(user)
        return user


@router.websocket("/ws/{session_id}")
async def websocket_events(websocket: WebSocket, session_id: UUID, after: int = 0):
    user = _websocket_user(websocket)
    if user is None:
        await websocket.close(code=4401)
        return
    with session_scope(websocket.app.state.session_factory) as db:
        try:
            owned_session(db, user, session_id)
        except HTTPException:
            await websocket.close(code=4404)
            return
        replay = [_event(item) for item in list_events(db, session_id, after=max(0, after))]
    await websocket.accept()
    for item in replay:
        await websocket.send_json(item)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    _subscribers[session_id].add(queue)
    try:
        while True:
            await websocket.send_json(await queue.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _subscribers[session_id].discard(queue)
