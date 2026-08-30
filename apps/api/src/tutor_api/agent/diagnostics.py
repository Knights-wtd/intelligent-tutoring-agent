from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from tutor_api.agent.models import (
    AgentProviderSetting,
    AgentSession,
    AgentSessionEvent,
    AgentUsageRecord,
)
from tutor_api.agent.runtime_client import RuntimeErrorBase
from tutor_api.core.database import session_scope
from tutor_api.knowledge.models import IndexVersion
from tutor_api.vault.models import (
    SemanticIndexPlan,
    VaultChangeSet,
    VaultChangeSetState,
    VaultFile,
    VaultSyncCursor,
    VaultSyncState,
)

_RUNTIME_FIELDS = {
    "status",
    "protocol_version",
    "version",
    "active_sessions",
    "warm_sessions",
    "queued_sessions",
    "persisted_sessions",
}
_PROVIDER_FIELDS = {
    "id",
    "name",
    "provider",
    "model",
    "enabled",
    "status",
    "health",
    "healthy",
    "context_window",
}
_MCP_FIELDS = {"id", "name", "server", "enabled", "status", "health", "healthy"}
_HEALTHY = {"ok", "healthy", "ready", "connected", "running", "warm"}


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _safe_record(value: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in allowed:
        if key not in value:
            continue
        safe = _safe_scalar(value[key])
        if safe is not None:
            result[key] = safe
    return result


def _safe_records(value: Any, allowed: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [record for item in value if (record := _safe_record(item, allowed))]


def _state_counts(db, model, column) -> dict[str, int]:
    rows = db.execute(select(column, func.count(model.id)).group_by(column)).all()
    return {
        (state.value if hasattr(state, "value") else str(state)): int(count)
        for state, count in rows
    }


def _filesystem_bytes(root: Path) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    total = 0
    try:
        for directory, directories, files in os.walk(root, followlinks=False):
            base = Path(directory)
            directories[:] = [name for name in directories if not (base / name).is_symlink()]
            for name in files:
                candidate = base / name
                if candidate.is_symlink():
                    continue
                try:
                    total += candidate.stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def _local_diagnostics(request: Request) -> dict[str, Any]:
    factory = getattr(request.app.state, "agent_event_store", None)
    if factory is None:
        factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return {
            "events": {"persisted": 0, "sequence_lag": 0},
            "sidecars": {"recorded_bytes": 0, "filesystem_bytes": 0},
            "vault": {
                "pending_change_sets": 0,
                "conflicts": 0,
                "pending_files": 0,
                "watcher_backlog": 0,
                "full_scans_required": 0,
            },
            "index": {"states": {}, "activation": {}},
            "planner": {},
            "control_plane": {"status": "unavailable"},
        }

    try:
        with session_scope(factory) as db:
            persisted = int(db.scalar(select(func.count(AgentSessionEvent.id))) or 0)
            latest_event_sequence = (
                select(
                    AgentSessionEvent.session_id,
                    func.max(AgentSessionEvent.sequence).label("max_sequence"),
                )
                .group_by(AgentSessionEvent.session_id)
                .subquery()
            )
            sequence_rows = db.execute(
                select(
                    AgentSession.last_event_sequence,
                    func.coalesce(latest_event_sequence.c.max_sequence, 0),
                ).outerjoin(
                    latest_event_sequence,
                    latest_event_sequence.c.session_id == AgentSession.id,
                )
            ).all()
            sequence_lag = sum(
                max(0, int(last_sequence or 0) - int(persisted_sequence or 0))
                for last_sequence, persisted_sequence in sequence_rows
            )
            latest_event = db.scalar(select(func.max(AgentSessionEvent.created_at)))
            event_age_seconds = 0.0
            if latest_event is not None:
                if latest_event.tzinfo is None:
                    latest_event = latest_event.replace(tzinfo=UTC)
                event_age_seconds = max(0.0, (datetime.now(UTC) - latest_event).total_seconds())

            recorded_sidecar_bytes = int(
                db.scalar(select(func.sum(AgentUsageRecord.sidecar_bytes))) or 0
            )
            pending_change_sets = int(
                db.scalar(
                    select(func.count(VaultChangeSet.id)).where(
                        VaultChangeSet.state.in_(
                            (
                                VaultChangeSetState.PENDING,
                                VaultChangeSetState.APPLYING,
                                VaultChangeSetState.INDEXING,
                            )
                        )
                    )
                )
                or 0
            )
            conflicts = int(
                db.scalar(
                    select(func.count(VaultChangeSet.id)).where(
                        VaultChangeSet.state == VaultChangeSetState.CONFLICTED
                    )
                )
                or 0
            )
            pending_files = int(
                db.scalar(
                    select(func.count(VaultFile.id)).where(
                        VaultFile.sync_state == VaultSyncState.PENDING
                    )
                )
                or 0
            )
            watcher_backlog = int(db.scalar(select(func.sum(VaultSyncCursor.pending_count))) or 0)
            full_scans_required = int(
                db.scalar(
                    select(func.count(VaultSyncCursor.id)).where(
                        VaultSyncCursor.requires_full_scan.is_(True)
                    )
                )
                or 0
            )
            provider_health = _state_counts(
                db, AgentProviderSetting, AgentProviderSetting.health_status
            )
            index_states = _state_counts(db, IndexVersion, IndexVersion.state)
            activation_states = _state_counts(db, IndexVersion, IndexVersion.activation_status)
            planner_states = _state_counts(db, SemanticIndexPlan, SemanticIndexPlan.state)
    except SQLAlchemyError:
        return {
            "events": {"persisted": 0, "sequence_lag": 0},
            "sidecars": {"recorded_bytes": 0, "filesystem_bytes": 0},
            "vault": {
                "pending_change_sets": 0,
                "conflicts": 0,
                "pending_files": 0,
                "watcher_backlog": 0,
                "full_scans_required": 0,
            },
            "index": {"states": {}, "activation": {}},
            "planner": {},
            "provider_health": {},
            "control_plane": {"status": "unavailable"},
        }

    sidecar_root = Path(
        getattr(
            request.app.state,
            "agent_sidecar_root",
            getattr(request.app.state.settings, "agent_sidecar_root", ".agent-data/sidecars"),
        )
    )
    return {
        "events": {
            "persisted": persisted,
            "sequence_lag": sequence_lag,
            "latest_event_age_seconds": round(event_age_seconds, 3),
        },
        "sidecars": {
            "recorded_bytes": recorded_sidecar_bytes,
            "filesystem_bytes": _filesystem_bytes(sidecar_root),
        },
        "vault": {
            "pending_change_sets": pending_change_sets,
            "conflicts": conflicts,
            "pending_files": pending_files,
            "watcher_backlog": watcher_backlog,
            "full_scans_required": full_scans_required,
        },
        "index": {"states": index_states, "activation": activation_states},
        "planner": planner_states,
        "provider_health": provider_health,
        "control_plane": {"status": "ok"},
    }


async def collect_agent_diagnostics(request: Request) -> dict[str, Any]:
    runtime_client = getattr(request.app.state, "agent_runtime_client", None)
    runtime: dict[str, Any]
    providers: list[dict[str, Any]] = []
    mcp: list[dict[str, Any]] = []
    if runtime_client is None:
        state = getattr(request.app.state, "agent_runtime_status", None)
        runtime = {
            "status": getattr(state, "status", "unavailable"),
            "code": getattr(state, "code", "runtime_unavailable"),
        }
    else:
        try:
            raw = await runtime_client.proxy("GET", "/v1/diagnostics")
            runtime = _safe_record(raw, _RUNTIME_FIELDS)
            runtime.setdefault("status", "unknown")
            providers = _safe_records(raw.get("providers"), _PROVIDER_FIELDS)
            mcp = _safe_records(raw.get("mcp", raw.get("mcp_servers")), _MCP_FIELDS)
        except RuntimeErrorBase as error:
            runtime = {"status": "unavailable", "code": error.code}
        except Exception:
            runtime = {"status": "unavailable", "code": "runtime_diagnostics_failed"}

    local = _local_diagnostics(request)
    runtime_status = str(runtime.get("status", "unknown")).casefold()
    provider_degraded = any(
        str(item.get("status", item.get("health", "unknown"))).casefold() not in _HEALTHY
        for item in providers
    )
    mcp_degraded = any(
        str(item.get("status", item.get("health", "unknown"))).casefold() not in _HEALTHY
        for item in mcp
    )
    control_plane_degraded = local.get("control_plane", {}).get("status") != "ok"
    status = (
        "ok"
        if runtime_status in _HEALTHY
        and not provider_degraded
        and not mcp_degraded
        and not control_plane_degraded
        else "degraded"
    )
    return {"status": status, "runtime": runtime, "providers": providers, "mcp": mcp, **local}
