from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.agent.models import (
    AgentAuditEvent,
    AgentSession,
    AgentSessionEvent,
    AgentSessionState,
    AgentTurn,
    AgentTurnState,
    AgentUsageRecord,
)
from tutor_api.agent.schemas import EventAck, RuntimeEvent


class EventStoreError(RuntimeError):
    def __init__(self, code: str, *, expected_sequence: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.expected_sequence = expected_sequence


_SECRET_KEYS = {"authorization", "cookie", "password", "secret", "token", "api_key", "apikey"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if key.casefold() in _SECRET_KEYS else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _same(existing: AgentSessionEvent, event: RuntimeEvent) -> bool:
    return (
        existing.event_id == event.event_id
        and existing.event_type == event.event_type
        and _utc(existing.timestamp) == _utc(event.timestamp)
        and existing.payload == redact(event.payload)
        and existing.turn_id == event.turn_id
    )


def _derive_state(session: AgentSession, turn: AgentTurn | None, event: RuntimeEvent) -> None:
    mapping = {
        "turn_completed": AgentTurnState.COMPLETED,
        "turn_failed": AgentTurnState.FAILED,
        "turn_stopped": AgentTurnState.STOPPED,
        "waiting_input": AgentTurnState.WAITING_INPUT,
    }
    session_mapping = {
        "turn_failed": AgentSessionState.FAILED,
        "turn_stopped": AgentSessionState.STOPPED,
        "waiting_input": AgentSessionState.WAITING_INPUT,
        "turn_completed": AgentSessionState.WAITING_INPUT,
    }
    if turn is not None and event.event_type in mapping:
        turn.state = mapping[event.event_type]
    if event.event_type in session_mapping:
        session.state = session_mapping[event.event_type]
    if event.event_type == "session_resumed":
        session.state = AgentSessionState.RUNNING
    if event.event_type == "session_state":
        runtime_state = event.payload.get("state")
        state_mapping = {
            "completed": (AgentTurnState.COMPLETED, AgentSessionState.WAITING_INPUT),
            "failed": (AgentTurnState.FAILED, AgentSessionState.FAILED),
            "waiting_input": (
                AgentTurnState.WAITING_INPUT,
                AgentSessionState.WAITING_INPUT,
            ),
        }
        states = state_mapping.get(runtime_state)
        if states is not None:
            turn_state, session_state = states
            if turn is not None:
                turn.state = turn_state
                if turn_state in {AgentTurnState.COMPLETED, AgentTurnState.FAILED}:
                    turn.completed_at = event.timestamp
            session.state = session_state


def _usage(db: Session, owner: AgentSession, event: RuntimeEvent) -> None:
    if event.event_type != "usage":
        return
    p = event.payload
    record = AgentUsageRecord(
        session_id=owner.id,
        turn_id=event.turn_id,
        provider=owner.provider,
        model=owner.model,
        input_tokens=max(0, int(p.get("input_tokens", 0))),
        output_tokens=max(0, int(p.get("output_tokens", 0))),
        cache_read_tokens=max(0, int(p.get("cache_read_tokens", 0))),
        cache_write_tokens=max(0, int(p.get("cache_write_tokens", 0))),
        compaction_count=max(0, int(p.get("compaction_count", 0))),
        tool_call_count=max(0, int(p.get("tool_call_count", 0))),
        web_request_count=max(0, int(p.get("web_request_count", 0))),
        file_read_bytes=max(0, int(p.get("file_read_bytes", 0))),
        command_duration_ms=max(0, int(p.get("command_duration_ms", 0))),
        sidecar_bytes=max(0, int(p.get("sidecar_bytes", 0))),
        session_duration_ms=max(0, int(p.get("session_duration_ms", 0))),
    )
    db.add(record)


def persist_runtime_event(db: Session, event: RuntimeEvent | dict[str, Any]) -> AgentSessionEvent:
    parsed = event if isinstance(event, RuntimeEvent) else RuntimeEvent.model_validate(event)
    duplicate = db.scalar(
        select(AgentSessionEvent).where(AgentSessionEvent.idempotency_key == parsed.idempotency_key)
    )
    if duplicate is not None:
        if _same(duplicate, parsed) and duplicate.sequence == parsed.sequence:
            return duplicate
        raise EventStoreError("event_idempotency_conflict")
    owner = db.scalar(
        select(AgentSession).where(AgentSession.id == parsed.session_id).with_for_update()
    )
    if owner is None:
        raise EventStoreError("agent_session_not_found")
    by_sequence = db.scalar(
        select(AgentSessionEvent).where(
            AgentSessionEvent.session_id == parsed.session_id,
            AgentSessionEvent.sequence == parsed.sequence,
        )
    )
    if by_sequence is not None:
        if _same(by_sequence, parsed):
            return by_sequence
        raise EventStoreError(
            "event_sequence_conflict", expected_sequence=owner.last_event_sequence + 1
        )
    expected = owner.last_event_sequence + 1
    if parsed.sequence != expected:
        raise EventStoreError("event_sequence_gap", expected_sequence=expected)
    stored = AgentSessionEvent(
        session_id=parsed.session_id,
        sequence=parsed.sequence,
        event_id=parsed.event_id,
        event_type=parsed.event_type,
        timestamp=parsed.timestamp,
        payload=redact(parsed.payload),
        turn_id=parsed.turn_id,
        tool_call_id=parsed.tool_call_id,
        subagent_id=parsed.subagent_id,
        completed=parsed.completed,
        sidecar_reference=parsed.sidecar_reference,
        idempotency_key=parsed.idempotency_key,
    )
    db.add(stored)
    owner.last_event_sequence = parsed.sequence
    turn = db.get(AgentTurn, parsed.turn_id) if parsed.turn_id else None
    _derive_state(owner, turn, parsed)
    _usage(db, owner, parsed)
    if parsed.event_type in {"tool_completed", "tool_failed", "file_changed", "command_completed"}:
        db.add(
            AgentAuditEvent(
                user_id=owner.user_id,
                session_id=owner.id,
                turn_id=parsed.turn_id,
                event_type=parsed.event_type,
                tool_name=str(parsed.payload.get("tool_name", "")) or None,
                tool_call_id=parsed.tool_call_id,
                status="failed" if parsed.event_type.endswith("failed") else "completed",
                arguments_summary=redact(parsed.payload.get("arguments", {})),
                result_summary=json.dumps(redact(parsed.payload.get("result")), ensure_ascii=False)[
                    :2000
                ]
                if "result" in parsed.payload
                else None,
                sidecar_reference=parsed.sidecar_reference,
            )
        )
    db.flush()
    return stored


def acknowledge_runtime_event(db: Session, event: RuntimeEvent | dict[str, Any]) -> EventAck:
    parsed = event if isinstance(event, RuntimeEvent) else RuntimeEvent.model_validate(event)
    before = db.scalar(
        select(AgentSessionEvent).where(AgentSessionEvent.idempotency_key == parsed.idempotency_key)
    )
    stored = persist_runtime_event(db, parsed)
    return EventAck(accepted_sequence=stored.sequence, duplicate=before is not None)


def list_events(db: Session, session_id, *, after: int = 0) -> list[AgentSessionEvent]:
    return list(
        db.scalars(
            select(AgentSessionEvent)
            .where(AgentSessionEvent.session_id == session_id, AgentSessionEvent.sequence > after)
            .order_by(AgentSessionEvent.sequence)
        )
    )
