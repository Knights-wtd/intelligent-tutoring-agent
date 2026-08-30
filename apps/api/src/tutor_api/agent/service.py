from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.agent.capability import issue_workspace_capability, verify_workspace_capability
from tutor_api.agent.models import AgentSession, AgentSessionState, AgentTurn
from tutor_api.agent.schemas import (
    AGENT_CONTEXT_WINDOW,
    AGENT_MODEL,
    AGENT_PROVIDER,
    RuntimeStartRequest,
    SessionCreateRequest,
    TurnCreateRequest,
)
from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_readable_knowledge_base
from tutor_api.vault.storage import VaultStorage


def owned_session(db: Session, user: User, session_id: UUID) -> AgentSession:
    value = db.scalar(
        select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id)
    )
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_session_not_found")
    get_readable_knowledge_base(db, user, value.knowledge_base_id)
    return value


def create_session(db: Session, user: User, payload: SessionCreateRequest) -> AgentSession:
    kb = get_readable_knowledge_base(db, user, payload.knowledge_base_id)
    value = AgentSession(
        user_id=user.id,
        space_id=kb.space_id,
        knowledge_base_id=kb.id,
        provider=AGENT_PROVIDER,
        model=AGENT_MODEL,
        permission_mode="bypassPermissions",
        state=AgentSessionState.WAITING_INPUT,
        recovery={"context_window": AGENT_CONTEXT_WINDOW},
    )
    db.add(value)
    db.flush()
    return value


def prepare_turn(
    db: Session,
    user: User,
    session_id: UUID,
    payload: TurnCreateRequest,
    settings,
    callback_url: str,
) -> tuple[AgentTurn, RuntimeStartRequest]:
    owner = owned_session(db, user, session_id)
    if owner.state == AgentSessionState.ARCHIVED:
        raise HTTPException(status_code=409, detail="agent_session_archived")
    if owner.provider != AGENT_PROVIDER or owner.model != AGENT_MODEL:
        raise HTTPException(status_code=409, detail="agent_session_provider_retired")
    turn = None
    if payload.idempotency_key:
        candidates = db.scalars(
            select(AgentTurn).where(AgentTurn.session_id == owner.id).order_by(AgentTurn.created_at)
        ).all()
        turn = next(
            (
                candidate
                for candidate in candidates
                if candidate.context_statistics.get("idempotency_key") == payload.idempotency_key
            ),
            None,
        )
    if turn is None:
        turn = AgentTurn(
            session_id=owner.id,
            user_message=payload.prompt,
            model=owner.model,
            context_statistics=(
                {"idempotency_key": payload.idempotency_key} if payload.idempotency_key else {}
            ),
        )
        db.add(turn)
        db.flush()
    capability = issue_workspace_capability(db, user, session_id=owner.id, settings=settings)
    verified = verify_workspace_capability(
        capability, settings=settings, expected_session_id=owner.id, expected_user_id=user.id
    )
    vault_root = Path(settings.agent_vault_root)
    vault_root.mkdir(parents=True, exist_ok=True)
    for workspace_root in verified["vault_roots"]:
        VaultStorage(Path(workspace_root), anchor_root=vault_root)
    request = RuntimeStartRequest(
        session_id=owner.id,
        turn_id=turn.id,
        input=payload.input or [{"type": "text", "text": payload.prompt}],
        workspace_roots=verified["vault_roots"],
        provider=owner.provider,
        model=owner.model,
        capability=capability,
        callback_url=callback_url,
        idempotency_key=payload.idempotency_key or f"turn:{turn.id}",
    )
    owner.state = AgentSessionState.RUNNING
    return turn, request


def fork_session(
    db: Session, user: User, source: AgentSession, native_session_id: str, checkpoint_id: str
) -> AgentSession:
    owned_session(db, user, source.id)
    forked = AgentSession(
        user_id=user.id,
        space_id=source.space_id,
        knowledge_base_id=source.knowledge_base_id,
        provider=source.provider,
        model=source.model,
        permission_mode="bypassPermissions",
        native_session_id=native_session_id,
        state=AgentSessionState.WAITING_INPUT,
        parent_session_id=source.id,
        rewind_checkpoint_id=checkpoint_id,
        recovery=dict(source.recovery),
    )
    db.add(forked)
    db.flush()
    return forked
