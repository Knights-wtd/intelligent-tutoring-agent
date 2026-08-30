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
from tutor_api.knowledge.embeddings import EmbeddingAdapter
from tutor_api.knowledge.retrieval import SearchHit, search_knowledge
from tutor_api.vault.models import VaultFile
from tutor_api.vault.storage import VaultStorage

AGENT_CONTEXT_RESULTS_PER_KB = 4
AGENT_CONTEXT_MAX_CHARACTERS = 4_000


def _linked_context_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")


def _linked_knowledge_base_ids(db: Session, user: User, payload: TurnCreateRequest) -> list[UUID]:
    resolved: list[UUID] = []
    seen: set[UUID] = set()
    for context in payload.linked_contexts:
        knowledge_base = (
            get_readable_knowledge_base(db, user, context.knowledge_base_id)
            if context.knowledge_base_id is not None
            else None
        )
        if context.vault_file_id is not None:
            filters = [VaultFile.id == context.vault_file_id, VaultFile.is_tombstoned.is_(False)]
            if knowledge_base is not None:
                filters.extend(
                    [
                        VaultFile.knowledge_base_id == knowledge_base.id,
                        VaultFile.space_id == knowledge_base.space_id,
                    ]
                )
            vault_file = db.scalar(select(VaultFile).where(*filters))
            if vault_file is None:
                raise _linked_context_not_found()
            file_knowledge_base = get_readable_knowledge_base(
                db, user, vault_file.knowledge_base_id
            )
            if knowledge_base is not None and file_knowledge_base.id != knowledge_base.id:
                raise _linked_context_not_found()
            knowledge_base = file_knowledge_base
        if knowledge_base is None:
            raise _linked_context_not_found()
        if knowledge_base.id not in seen:
            seen.add(knowledge_base.id)
            resolved.append(knowledge_base.id)
    return resolved


def _format_context_hits(hits: list[SearchHit]) -> str | None:
    if not hits:
        return None
    text = "以下内容来自用户有权访问的知识库，仅作为参考："
    for hit in hits:
        page = f"，第 {hit.citation.page_number} 页" if hit.citation.page_number is not None else ""
        label = f"【来源：{hit.citation.source_name}{page}】"
        remaining = AGENT_CONTEXT_MAX_CHARACTERS - len(text) - 2
        if remaining <= len(label) + 1:
            break
        excerpt = hit.excerpt[: remaining - len(label) - 1]
        if not excerpt:
            break
        text = f"{text}\n\n{label}\n{excerpt}"
    return text if "【来源：" in text else None


def _runtime_input_with_linked_context(
    db: Session,
    user: User,
    payload: TurnCreateRequest,
    *,
    embedding_adapter: EmbeddingAdapter,
    citation_secret: str,
) -> list[dict]:
    runtime_input = list(payload.input or [{"type": "text", "text": payload.prompt}])
    knowledge_base_ids = _linked_knowledge_base_ids(db, user, payload)
    if not knowledge_base_ids:
        return runtime_input
    hits: list[SearchHit] = []
    try:
        for knowledge_base_id in knowledge_base_ids:
            hits.extend(
                search_knowledge(
                    db,
                    user,
                    knowledge_base_id,
                    query=payload.prompt,
                    limit=AGENT_CONTEXT_RESULTS_PER_KB,
                    embedding_adapter=embedding_adapter,
                    citation_secret=citation_secret,
                )
            )
    except ValueError:
        return runtime_input
    context_text = _format_context_hits(hits)
    if context_text is not None:
        runtime_input.append({"type": "text", "text": context_text})
    return runtime_input


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
    *,
    embedding_adapter: EmbeddingAdapter,
    citation_secret: str,
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
        input=_runtime_input_with_linked_context(
            db,
            user,
            payload,
            embedding_adapter=embedding_adapter,
            citation_secret=citation_secret,
        ),
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
    db: Session,
    user: User,
    source: AgentSession,
    fork_session_id: UUID,
    native_session_id: str,
    checkpoint_id: str,
) -> AgentSession:
    owned_session(db, user, source.id)
    forked = AgentSession(
        id=fork_session_id,
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
