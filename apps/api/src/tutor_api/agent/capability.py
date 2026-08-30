from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.classrooms.models import Classroom, ClassroomMembership, ClassroomRole
from tutor_api.identity.models import User
from tutor_api.knowledge.access import list_readable_knowledge_bases
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.spaces.models import Space, SpaceKind


class CapabilityError(ValueError):
    """A stable, non-secret capability validation failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WorkspaceGrant:
    knowledge_base_id: UUID
    vault_root: str
    actions: tuple[str, ...]


_AGENT_TOOL_CATEGORIES = ("vault", "shell", "web", "mcp", "skills", "subagents")
_AGENT_KNOWLEDGE_BASE_ACTIONS = {"read", "write", "delete"}


def _secret(value: Any) -> str:
    getter = getattr(value, "get_secret_value", None)
    return getter() if getter else str(value)


def _setting(settings: Any, name: str, default: Any = None) -> Any:
    return getattr(settings, name, default)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _vault_path(root: Path, space_id: UUID, knowledge_base_id: UUID) -> str:
    return str((root / "spaces" / str(space_id) / str(knowledge_base_id)).resolve())


def _can_write(session: Session, user: User, knowledge_base: KnowledgeBase) -> bool:
    space = session.get(Space, knowledge_base.space_id)
    if space is None:
        return False
    if space.kind is SpaceKind.PERSONAL:
        return space.owner_id == user.id
    role = session.scalar(
        select(ClassroomMembership.role)
        .join(Classroom, Classroom.id == ClassroomMembership.classroom_id)
        .where(
            Classroom.space_id == space.id,
            ClassroomMembership.user_id == user.id,
        )
    )
    return role in {ClassroomRole.OWNER, ClassroomRole.TEACHER}


def issue_workspace_capability(
    session: Session,
    user: User,
    *,
    session_id: UUID,
    settings: Any,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=UTC)
    ttl = int(_setting(settings, "agent_capability_ttl_seconds", 300))
    if not 30 <= ttl <= 3600:
        raise CapabilityError("capability_ttl_invalid")
    root = Path(_setting(settings, "agent_vault_root", Path.cwd() / ".agent-vault"))
    grants: list[WorkspaceGrant] = []
    for kb in list_readable_knowledge_bases(session, user):
        writable = _can_write(session, user, kb)
        grants.append(
            WorkspaceGrant(
                knowledge_base_id=kb.id,
                vault_root=_vault_path(root, kb.space_id, kb.id),
                actions=("read", "write", "delete") if writable else ("read",),
            )
        )
    payload = {
        "version": "1.0",
        "user_id": str(user.id),
        "session_id": str(session_id),
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(seconds=ttl)).isoformat(),
        "nonce": secrets.token_urlsafe(24),
        "grants": [
            {
                "knowledge_base_id": str(grant.knowledge_base_id),
                "actions": list(grant.actions),
            }
            for grant in grants
        ],
        "tool_categories": list(_AGENT_TOOL_CATEGORIES),
        "vault_roots": [grant.vault_root for grant in grants],
    }
    body = _b64(_canonical(payload))
    secret = _secret(_setting(settings, "agent_capability_secret"))
    if len(secret) < 32:
        raise CapabilityError("capability_secret_invalid")
    signature = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_workspace_capability(
    token: str,
    *,
    settings: Any,
    expected_session_id: UUID | None = None,
    expected_user_id: UUID | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        body, supplied = token.split(".", 1)
        secret = _secret(_setting(settings, "agent_capability_secret"))
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            raise CapabilityError("capability_signature_invalid")
        payload = json.loads(_unb64(body))
    except CapabilityError:
        raise
    except Exception as error:
        raise CapabilityError("capability_invalid") from error
    grants = payload.get("grants")
    tool_categories = payload.get("tool_categories")
    vault_roots = payload.get("vault_roots")
    if (
        payload.get("version") != "1.0"
        or not isinstance(grants, list)
        or not isinstance(tool_categories, list)
        or not isinstance(vault_roots, list)
        or any(
            not isinstance(grant, dict)
            or not isinstance(grant.get("knowledge_base_id"), str)
            or not isinstance(grant.get("actions"), list)
            or any(action not in _AGENT_KNOWLEDGE_BASE_ACTIONS for action in grant["actions"])
            for grant in grants
        )
        or any(category not in _AGENT_TOOL_CATEGORIES for category in tool_categories)
        or any(not isinstance(root, str) or not root for root in vault_roots)
    ):
        raise CapabilityError("capability_invalid")
    current = now or datetime.now(UTC)
    expires = datetime.fromisoformat(payload["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if current >= expires:
        raise CapabilityError("capability_expired")
    if expected_session_id is not None and payload.get("session_id") != str(expected_session_id):
        raise CapabilityError("capability_session_mismatch")
    if expected_user_id is not None and payload.get("user_id") != str(expected_user_id):
        raise CapabilityError("capability_user_mismatch")
    return payload
