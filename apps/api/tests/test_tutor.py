from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.indexing import (
    _embedding_contract_signature,
    content_sha256,
    normalize_lexical_terms,
)
from tutor_api.knowledge.models import (
    Chunk,
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    IndexVersion,
    IndexVersionState,
    KnowledgeBase,
)
from tutor_api.llm.ports import (
    LlmCompletion,
    LlmProviderError,
    LlmUsage,
    TutorChatMessage,
)
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.tutor.models import TutorConversation, TutorMessage, TutorMessageRole
from tutor_api.tutor.schemas import TutorSendRequest
from tutor_api.tutor.service import (
    MAX_TUTOR_HISTORY_MESSAGES,
    MAX_TUTOR_PROMPT_CHARACTERS,
    MAX_TUTOR_SOURCES,
    TutorServiceError,
    send_tutor_message,
)


class FixedEmbeddingAdapter:
    def __init__(
        self,
        vectors: dict[str, list[float]] | None = None,
        *,
        backend: str = "hash",
        model: str = "feature-hash-v1",
        dimension: int = 8,
        signature: str = "hash:feature-hash-v1:8",
    ) -> None:
        self.vectors = vectors or {}
        self.backend = backend
        self.model = model
        self.dimension = dimension
        self.signature = signature

    def embed(self, text: str) -> list[float]:
        return self.vectors.get(text, [1.0] + [0.0] * (self.dimension - 1))


class RecordingTutorAdapter:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.messages: tuple[TutorChatMessage, ...] = ()

    def complete_tutor(self, messages: Sequence[TutorChatMessage]) -> LlmCompletion:
        self.messages = tuple(messages)
        return LlmCompletion(
            text=self.response_text,
            request_id="tutor-test",
            usage=LlmUsage(10, 5, 15),
        )


class FailingTutorAdapter:
    def __init__(self, code: str, detail: str = "provider body secret") -> None:
        self.code = code
        self.detail = detail

    def complete_tutor(self, messages: Sequence[TutorChatMessage]) -> LlmCompletion:
        del messages
        error = LlmProviderError(self.code)
        error.add_note(self.detail)
        raise error


@pytest.fixture
def session() -> Session:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as database_session:
        yield database_session
    engine.dispose()


def seed_searchable_knowledge_base(session: Session) -> tuple[User, KnowledgeBase]:
    owner = User(
        email="tutor-owner@example.com",
        username="tutor-owner",
        password_hash="not-used",
    )
    session.add(owner)
    session.flush()
    space = Space(owner_id=owner.id, kind=SpaceKind.PERSONAL, name="Tutor owner")
    session.add(space)
    session.flush()
    knowledge_base = KnowledgeBase(
        space_id=space.id,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        name="Wireless textbook",
    )
    session.add(knowledge_base)
    session.flush()
    document = Document(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        title="wireless.pdf",
        source_kind="upload",
        source_key="wireless.pdf",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    text = "path loss increases as wireless transmission distance increases"
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        version_number=1,
        content_sha256=content_sha256(text),
        object_key="objects/wireless.pdf",
        content_type="application/pdf",
        state=DocumentVersionState.READY,
        created_by_user_id=owner.id,
    )
    session.add(version)
    session.flush()
    from tutor_api.knowledge.models import Page

    page = Page(
        space_id=space.id,
        document_version_id=version.id,
        page_number=7,
        source_pointer="wireless.pdf#page=7",
        content_sha256=content_sha256(text),
        source_metadata={},
    )
    session.add(page)
    session.flush()
    embedding = FixedEmbeddingAdapter()
    index = IndexVersion(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        version_number=1,
        state=IndexVersionState.ACTIVE,
        parser_signature="parser:1",
        ocr_signature="ocr:1",
        chunking_signature="chunking:1",
        embedding_backend=embedding.backend,
        embedding_model=embedding.model,
        embedding_dimension=embedding.dimension,
        embedding_contract_signature=_embedding_contract_signature(embedding),
        index_signature="index:1",
        created_by_user_id=owner.id,
        completed_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
    )
    session.add(index)
    session.flush()
    session.add(
        Chunk(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            index_version_id=index.id,
            document_version_id=version.id,
            page_id=page.id,
            block_id=None,
            ordinal=0,
            source_pointer="wireless.pdf#page=7#chunk=0",
            content_sha256=content_sha256(text),
            content=text,
            lexical_terms=normalize_lexical_terms(text),
            embedding_dimension=embedding.dimension,
            index_signature=index.index_signature,
            embedding=embedding.embed(text),
        )
    )
    session.commit()
    return owner, knowledge_base


def test_send_message_retrieves_sources_and_persists_both_roles(session: Session) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)
    adapter = RecordingTutorAdapter("Path loss grows with distance. [1]")

    result = send_tutor_message(
        session,
        owner,
        knowledge_base.id,
        prompt="  path loss  ",
        conversation_id=None,
        adapter=adapter,
        embedding_adapter=FixedEmbeddingAdapter(),
        citation_secret="test-secret",
    )

    assert [message.role for message in result.messages] == [
        TutorMessageRole.USER,
        TutorMessageRole.ASSISTANT,
    ]
    assert result.messages[0].content == "path loss"
    assistant = result.messages[-1]
    assert assistant.citations == [
        {
            "id": assistant.citations[0]["id"],
            "source_name": "wireless.pdf",
            "page_number": 7,
        }
    ]
    assert str(assistant.citations[0]["id"]).startswith("cite_")
    assert assistant.provider_request_id == "tutor-test"
    assert (assistant.prompt_tokens, assistant.completion_tokens) == (10, 5)
    assert adapter.messages[-1].role == "user"
    assert "untrusted" in adapter.messages[-1].content.casefold()
    assert "[1]" in adapter.messages[-1].content
    assert "wireless.pdf" in adapter.messages[-1].content
    assert session.scalar(select(func.count()).select_from(TutorMessage)) == 2


def test_existing_conversation_requires_exact_scope_and_authorizes_first(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)
    outsider = User(email="outsider@example.com", username="outsider", password_hash="x")
    session.add(outsider)
    session.commit()
    conversation = TutorConversation(
        user_id=owner.id,
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        title="Scope",
    )
    session.add(conversation)
    session.commit()
    loads: list[object] = []
    original_get = session.get

    def recording_get(entity: object, key: object):
        if entity is TutorConversation:
            loads.append(key)
        return original_get(entity, key)

    monkeypatch.setattr(session, "get", recording_get)

    with pytest.raises(HTTPException) as error:
        send_tutor_message(
            session,
            outsider,
            knowledge_base.id,
            prompt="private",
            conversation_id=conversation.id,
            adapter=RecordingTutorAdapter("never"),
            embedding_adapter=FixedEmbeddingAdapter(),
            citation_secret="test-secret",
        )

    assert error.value.status_code == 404
    assert loads == []


def test_mismatched_conversation_is_stable_not_found(session: Session) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)
    other_user = User(email="other@example.com", username="other", password_hash="x")
    session.add(other_user)
    session.flush()
    conversation = TutorConversation(
        user_id=other_user.id,
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        title="Wrong owner",
    )
    session.add(conversation)
    session.commit()

    with pytest.raises(TutorServiceError) as error:
        send_tutor_message(
            session,
            owner,
            knowledge_base.id,
            prompt="path loss",
            conversation_id=conversation.id,
            adapter=RecordingTutorAdapter("never"),
            embedding_adapter=FixedEmbeddingAdapter(),
            citation_secret="test-secret",
        )

    assert error.value.code == "tutor_conversation_not_found"


def test_next_send_reads_previous_user_before_assistant(
    session: Session,
) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)
    first = send_tutor_message(
        session,
        owner,
        knowledge_base.id,
        prompt="first question",
        conversation_id=None,
        adapter=RecordingTutorAdapter("first answer"),
        embedding_adapter=FixedEmbeddingAdapter(),
        citation_secret="test-secret",
    )
    assert first.messages[0].created_at < first.messages[1].created_at
    session.commit()
    second_adapter = RecordingTutorAdapter("second answer")

    send_tutor_message(
        session,
        owner,
        knowledge_base.id,
        prompt="second question",
        conversation_id=first.conversation.id,
        adapter=second_adapter,
        embedding_adapter=FixedEmbeddingAdapter(),
        citation_secret="test-secret",
    )

    assert [(message.role, message.content) for message in second_adapter.messages[:2]] == [
        ("user", "first question"),
        ("assistant", "first answer"),
    ]
    assert second_adapter.messages[-1].role == "user"
    assert "second question" in second_adapter.messages[-1].content
def test_history_is_bounded_and_ordered_before_current_grounded_prompt(session: Session) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)
    conversation = TutorConversation(
        user_id=owner.id,
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        title="History",
    )
    session.add(conversation)
    session.flush()
    for ordinal in range(MAX_TUTOR_HISTORY_MESSAGES + 2):
        session.add(
            TutorMessage(
                conversation_id=conversation.id,
                user_id=owner.id,
                space_id=knowledge_base.space_id,
                knowledge_base_id=knowledge_base.id,
                role=(
                    TutorMessageRole.USER
                    if ordinal % 2 == 0
                    else TutorMessageRole.ASSISTANT
                ),
                content=f"history-{ordinal:02d}",
                citations=[],
                created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=ordinal),
            )
        )
        session.flush()
    session.commit()
    adapter = RecordingTutorAdapter("answer")

    send_tutor_message(
        session,
        owner,
        knowledge_base.id,
        prompt="path loss",
        conversation_id=conversation.id,
        adapter=adapter,
        embedding_adapter=FixedEmbeddingAdapter(),
        citation_secret="test-secret",
    )

    assert [message.content for message in adapter.messages[:-1]] == [
        f"history-{ordinal:02d}" for ordinal in range(2, 12)
    ]
    assert adapter.messages[-1].content.startswith("The following textbook excerpts")
    assert len(adapter.messages) == MAX_TUTOR_HISTORY_MESSAGES + 1


@pytest.mark.parametrize("prompt", ["   ", "x" * (MAX_TUTOR_PROMPT_CHARACTERS + 1)])
def test_prompt_is_nonempty_and_bounded(session: Session, prompt: str) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)

    with pytest.raises(TutorServiceError) as error:
        send_tutor_message(
            session,
            owner,
            knowledge_base.id,
            prompt=prompt,
            conversation_id=None,
            adapter=RecordingTutorAdapter("never"),
            embedding_adapter=FixedEmbeddingAdapter(),
            citation_secret="test-secret",
        )

    assert error.value.code == "tutor_prompt_invalid"


def test_search_uses_exact_source_limit(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)
    observed: dict[str, int] = {}

    def fake_search(*args: object, limit: int, **kwargs: object) -> list[object]:
        del args, kwargs
        observed["limit"] = limit
        return []

    monkeypatch.setattr("tutor_api.tutor.service.search_knowledge", fake_search)

    send_tutor_message(
        session,
        owner,
        knowledge_base.id,
        prompt="path loss",
        conversation_id=None,
        adapter=RecordingTutorAdapter("No evidence available."),
        embedding_adapter=FixedEmbeddingAdapter(),
        citation_secret="test-secret",
    )

    assert observed == {"limit": MAX_TUTOR_SOURCES}


def test_empty_search_still_calls_adapter_with_no_evidence_instruction(
    session: Session,
) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)
    session.query(IndexVersion).delete()
    session.commit()
    adapter = RecordingTutorAdapter("The textbook evidence is unavailable.")

    result = send_tutor_message(
        session,
        owner,
        knowledge_base.id,
        prompt="path loss",
        conversation_id=None,
        adapter=adapter,
        embedding_adapter=FixedEmbeddingAdapter(),
        citation_secret="test-secret",
    )

    assert "evidence is unavailable" in adapter.messages[-1].content.casefold()
    assert result.messages[-1].citations == []


@pytest.mark.parametrize(
    ("provider_code", "service_code"),
    [
        ("llm_timeout", "tutor_provider_timeout"),
        ("llm_rate_limited", "tutor_provider_rate_limited"),
        ("llm_unauthorized", "tutor_provider_unavailable"),
        ("llm_provider_error", "tutor_provider_unavailable"),
    ],
)
def test_provider_errors_are_safe_and_atomic(
    session: Session, provider_code: str, service_code: str
) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)

    with pytest.raises(TutorServiceError) as error:
        send_tutor_message(
            session,
            owner,
            knowledge_base.id,
            prompt="path loss",
            conversation_id=None,
            adapter=FailingTutorAdapter(provider_code),
            embedding_adapter=FixedEmbeddingAdapter(),
            citation_secret="test-secret",
        )

    assert error.value.code == service_code
    assert "provider body secret" not in str(error.value)
    assert session.scalar(select(func.count()).select_from(TutorConversation)) == 0
    assert session.scalar(select(func.count()).select_from(TutorMessage)) == 0


def test_send_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        TutorSendRequest(prompt="path loss", provider_api_key="must-not-be-client-controlled")
