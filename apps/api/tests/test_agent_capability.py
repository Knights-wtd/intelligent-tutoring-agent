from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from tutor_api.agent import models as agent_models  # noqa: F401
from tutor_api.agent.capability import (
    CapabilityError,
    issue_workspace_capability,
    verify_workspace_capability,
)
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import KnowledgeBase
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.vault import models as vault_models  # noqa: F401


def test_capability_contains_all_and_only_readable_knowledge_bases(tmp_path: Path) -> None:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(email="owner-cap@example.com", username="owner-cap", password_hash="h")
        foreign = User(email="foreign-cap@example.com", username="foreign-cap", password_hash="h")
        db.add_all([owner, foreign])
        db.flush()
        own_space = Space(owner_id=owner.id, kind=SpaceKind.PERSONAL, name="Own")
        foreign_space = Space(owner_id=foreign.id, kind=SpaceKind.PERSONAL, name="Foreign")
        db.add_all([own_space, foreign_space])
        db.flush()
        own = KnowledgeBase(
            space_id=own_space.id, owner_user_id=owner.id, created_by_user_id=owner.id, name="Own"
        )
        other = KnowledgeBase(
            space_id=foreign_space.id,
            owner_user_id=foreign.id,
            created_by_user_id=foreign.id,
            name="Other",
        )
        db.add_all([own, other])
        db.flush()
        settings = SimpleNamespace(
            agent_capability_secret=SecretStr("x" * 32),
            agent_capability_ttl_seconds=300,
            agent_vault_root=tmp_path,
        )
        token = issue_workspace_capability(db, owner, session_id=own.id, settings=settings)
        payload = verify_workspace_capability(token, settings=settings, expected_user_id=owner.id)
        assert {grant["knowledge_base_id"] for grant in payload["grants"]} == {str(own.id)}
        assert str(other.id) not in token
        assert payload["grants"][0]["actions"] == ["read", "write", "delete"]
        assert payload["tool_categories"] == [
            "vault",
            "shell",
            "web",
            "mcp",
            "skills",
            "subagents",
        ]
        assert payload["vault_roots"] == [
            str((tmp_path / "spaces" / str(own_space.id) / str(own.id)).resolve())
        ]
    Base.metadata.drop_all(engine)


def test_expired_and_tampered_capabilities_are_rejected(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        agent_capability_secret=SecretStr("x" * 32),
        agent_capability_ttl_seconds=300,
        agent_vault_root=tmp_path,
    )

    class EmptySession:
        def scalars(self, *_args, **_kwargs):
            return []

    user = SimpleNamespace(id=__import__("uuid").uuid4())
    now = datetime.now(UTC)
    token = issue_workspace_capability(
        EmptySession(), user, session_id=__import__("uuid").uuid4(), settings=settings, now=now
    )
    with pytest.raises(CapabilityError, match="capability_expired"):
        verify_workspace_capability(token, settings=settings, now=now + timedelta(seconds=301))
    with pytest.raises(CapabilityError, match="capability_signature_invalid"):
        verify_workspace_capability(
            token[:-1] + ("a" if token[-1] != "a" else "b"), settings=settings
        )
