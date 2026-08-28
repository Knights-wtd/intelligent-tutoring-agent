from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
from tutor_api.core.config import Settings
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
from tutor_api.main import create_app
from tutor_api.spaces.models import Space, SpaceKind
from tutor_api.tutor.models import TutorConversation, TutorMessage, TutorMessageRole
from tutor_api.tutor.schemas import TutorSendRequest
from tutor_api.tutor.service import (
    MAX_TUTOR_HISTORY_MESSAGES,
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


def test_provider_call_is_bounded_by_concurrency_semaphore(session: Session) -> None:
    import threading

    owner, knowledge_base = seed_searchable_knowledge_base(session)
    entered = threading.Event()
    release = threading.Event()
    completion = LlmCompletion(text="ok", request_id="r", usage=LlmUsage(1, 1, 2))

    class BlockingTutorAdapter:
        def complete_tutor(self, messages: Sequence[TutorChatMessage]) -> LlmCompletion:
            del messages
            entered.set()
            assert release.wait(timeout=10), "adapter was never released"
            return completion

    semaphore = threading.Semaphore(1)
    failures: list[BaseException] = []

    def worker() -> None:
        try:
            send_tutor_message(
                session,
                owner,
                knowledge_base.id,
                prompt="path loss",
                conversation_id=None,
                adapter=BlockingTutorAdapter(),
                embedding_adapter=FixedEmbeddingAdapter(),
                citation_secret="test-secret",
                concurrency_semaphore=semaphore,
            )
        except BaseException as error:  # noqa: BLE001 - re-raised for the test
            failures.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=10), "provider call never started"
    # While the provider call is in flight the semaphore must be held, so a
    # second concurrent call would queue instead of hitting the provider.
    assert not semaphore.acquire(blocking=False), "semaphore not held during provider call"
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert failures == []
    # ...and released once the call returns.
    assert semaphore.acquire(blocking=False)
    semaphore.release()


def test_provider_call_runs_after_read_transaction_is_committed(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    owner, knowledge_base = seed_searchable_knowledge_base(session)
    commit_seen = threading.Event()
    completion = LlmCompletion(text="ok", request_id="r", usage=LlmUsage(1, 1, 2))
    original_commit = session.commit

    def recording_commit() -> None:
        original_commit()
        commit_seen.set()

    monkeypatch.setattr(session, "commit", recording_commit)

    class OrderingAdapter:
        def complete_tutor(self, messages: Sequence[TutorChatMessage]) -> LlmCompletion:
            del messages
            assert commit_seen.wait(timeout=5), (
                "provider call started before the read transaction was committed"
            )
            return completion

    result = send_tutor_message(
        session,
        owner,
        knowledge_base.id,
        prompt="path loss",
        conversation_id=None,
        adapter=OrderingAdapter(),
        embedding_adapter=FixedEmbeddingAdapter(),
        citation_secret="test-secret",
    )

    assert commit_seen.is_set()
    assert len(result.messages) == 2
    assert session.scalar(select(func.count()).select_from(TutorMessage)) == 2


def test_app_state_exposes_tutor_semaphore_from_settings() -> None:
    import threading

    active_client, _, engine, _ = make_tutor_client(False)
    try:
        semaphore = active_client.app.state.tutor_semaphore
        assert isinstance(semaphore, threading.Semaphore)
        assert semaphore._value == Settings(app_env="test").faro_max_concurrency
    finally:
        active_client.close()
        engine.dispose()


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


def test_appending_message_advances_conversation_updated_at(session: Session) -> None:
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
    session.commit()
    session.refresh(first.conversation)
    original_updated_at = first.conversation.updated_at

    second = send_tutor_message(
        session,
        owner,
        knowledge_base.id,
        prompt="second question",
        conversation_id=first.conversation.id,
        adapter=RecordingTutorAdapter("second answer"),
        embedding_adapter=FixedEmbeddingAdapter(),
        citation_secret="test-secret",
    )
    session.flush()
    session.refresh(first.conversation)
    session.refresh(second.messages[-1])

    def as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    assert as_utc(first.conversation.updated_at) > as_utc(original_updated_at)
    assert as_utc(first.conversation.updated_at) >= as_utc(second.messages[-1].created_at)


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


def test_prompt_is_nonempty(session: Session) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)

    with pytest.raises(TutorServiceError) as error:
        send_tutor_message(
            session,
            owner,
            knowledge_base.id,
            prompt="   ",
            conversation_id=None,
            adapter=RecordingTutorAdapter("never"),
            embedding_adapter=FixedEmbeddingAdapter(),
            citation_secret="test-secret",
        )

    assert error.value.code == "tutor_prompt_invalid"


def test_prompt_at_retrieval_limit_is_accepted(session: Session) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)

    result = send_tutor_message(
        session,
        owner,
        knowledge_base.id,
        prompt="x" * 500,
        conversation_id=None,
        adapter=RecordingTutorAdapter("answer"),
        embedding_adapter=FixedEmbeddingAdapter(),
        citation_secret="test-secret",
    )

    assert result.messages[0].content == "x" * 500


def test_prompt_above_retrieval_limit_is_rejected(session: Session) -> None:
    owner, knowledge_base = seed_searchable_knowledge_base(session)

    with pytest.raises(TutorServiceError) as error:
        send_tutor_message(
            session,
            owner,
            knowledge_base.id,
            prompt="x" * 501,
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
        ("llm_unauthorized", "tutor_provider_key_invalid"),
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

def register(client: TestClient, username: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "password": "Correct horse battery staple 9",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_knowledge_base(client: TestClient, space_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases",
        json={"name": f"Tutor textbook {uuid4().hex}"},
    )
    assert response.status_code == 201
    return response.json()


def seed_http_knowledge_base(
    engine: object,
    registration: dict[str, object],
    knowledge_base_data: dict[str, object],
) -> None:
    from tutor_api.knowledge.models import Page

    with sessionmaker(bind=engine)() as database_session:
        owner = database_session.get(User, UUID(str(registration["user"]["id"])))
        knowledge_base = database_session.get(
            KnowledgeBase, UUID(str(knowledge_base_data["id"]))
        )
        assert owner is not None
        assert knowledge_base is not None
        text = "path loss increases as wireless transmission distance increases"
        document = Document(
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            owner_user_id=owner.id,
            created_by_user_id=owner.id,
            title="wireless.pdf",
            source_kind="upload",
            source_key="wireless.pdf",
            state=DocumentState.ACTIVE,
        )
        database_session.add(document)
        database_session.flush()
        version = DocumentVersion(
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            version_number=1,
            content_sha256=content_sha256(text),
            object_key="objects/wireless.pdf",
            content_type="application/pdf",
            state=DocumentVersionState.READY,
            created_by_user_id=owner.id,
        )
        database_session.add(version)
        database_session.flush()
        page = Page(
            space_id=knowledge_base.space_id,
            document_version_id=version.id,
            page_number=7,
            source_pointer="wireless.pdf#page=7",
            content_sha256=content_sha256(text),
            source_metadata={},
        )
        database_session.add(page)
        database_session.flush()
        embedding = FixedEmbeddingAdapter()
        index = IndexVersion(
            space_id=knowledge_base.space_id,
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
        database_session.add(index)
        database_session.flush()
        database_session.add(
            Chunk(
                space_id=knowledge_base.space_id,
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
        database_session.commit()

def make_tutor_client(
    configured: bool,
    *,
    adapter: object | None = None,
    faro_api_key: str | None = None,
) -> tuple[TestClient, dict[str, object], object, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    active_adapter = adapter or RecordingTutorAdapter(
        "Grounded answer from textbook evidence. [1]"
    )
    settings = Settings(
        app_env="test",
        faro_api_key=SecretStr(
            faro_api_key if faro_api_key is not None else ("sk-test" if configured else "")
        ),
    )
    app = create_app(settings, sessionmaker(bind=engine))
    app.state.tutor_adapter = active_adapter
    app.state.embedding_adapter = FixedEmbeddingAdapter()
    client = TestClient(app)
    registration = register(client, "tutor-http")
    knowledge_base = create_knowledge_base(client, str(registration["personal_space"]["id"]))
    seed_http_knowledge_base(engine, registration, knowledge_base)
    return client, knowledge_base, engine, active_adapter


@pytest.fixture
def client() -> TestClient:
    active_client, _, engine, _ = make_tutor_client(False)
    try:
        yield active_client
    finally:
        active_client.close()
        engine.dispose()


@pytest.fixture
def configured_client() -> tuple[TestClient, dict[str, object], object]:
    active_client, knowledge_base, engine, adapter = make_tutor_client(True)
    try:
        yield active_client, knowledge_base, adapter
    finally:
        active_client.close()
        engine.dispose()


def test_tutor_status_reports_missing_key_without_secrets(client: TestClient) -> None:
    response = client.get("/api/v1/tutor/status")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "model": "gemini-3.7-flash-tiered",
    }
    for secret_name in ("api_key", "base_url", "secret"):
        assert secret_name not in response.text.casefold()


def test_tutor_status_reports_configured_model(
    configured_client: tuple[TestClient, dict[str, object], object],
) -> None:
    active_client, _, _ = configured_client
    response = active_client.get("/api/v1/tutor/status")

    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "model": "gemini-3.7-flash-tiered",
    }


def test_placeholder_api_key_reports_unconfigured_and_never_calls_adapter() -> None:
    active_client, knowledge_base, engine, adapter = make_tutor_client(
        False, faro_api_key="placeholder-faro-key"
    )
    try:
        status = active_client.get("/api/v1/tutor/status")
        assert status.status_code == 200
        assert status.json()["configured"] is False

        response = active_client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/tutor/conversations",
            json={"prompt": "path loss"},
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "tutor_provider_unavailable"}
        assert adapter.messages == ()
    finally:
        active_client.close()
        engine.dispose()


def test_unconfigured_create_is_safe_and_does_not_call_adapter(client: TestClient) -> None:
    personal_space_id = client.get("/api/v1/auth/me").json()["personal_space"]["id"]
    knowledge_base = create_knowledge_base(client, personal_space_id)
    adapter = client.app.state.tutor_adapter

    response = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/tutor/conversations",
        json={"prompt": "path loss"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "tutor_provider_unavailable"}
    assert adapter.messages == ()


def test_create_get_and_send_conversation_returns_only_public_messages(
    configured_client: tuple[TestClient, dict[str, object], object],
) -> None:
    active_client, knowledge_base, _ = configured_client
    created = active_client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/tutor/conversations",
        json={"prompt": "explain path loss"},
    )

    assert created.status_code == 201
    body = created.json()
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert body["messages"][-1]["content"] == "Grounded answer from textbook evidence. [1]"
    assert body["messages"][-1]["citations"][0]["source_name"] == "wireless.pdf"
    for hidden in ("api_key", "base_url", "provider body", "untrusted textbook excerpt"):
        assert hidden not in created.text.casefold()

    conversation_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/tutor/conversations/{body['id']}"
    )
    loaded = active_client.get(conversation_url)
    assert loaded.status_code == 200
    assert loaded.json() == body

    sent = active_client.post(conversation_url + "/messages", json={"prompt": "and distance?"})
    assert sent.status_code == 200
    assert [message["role"] for message in sent.json()["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_conversation_is_hidden_across_users_and_knowledge_bases(
    configured_client: tuple[TestClient, dict[str, object], object],
) -> None:
    owner, knowledge_base, _ = configured_client
    created = owner.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/tutor/conversations",
        json={"prompt": "private question"},
    ).json()
    other_base = create_knowledge_base(
        owner, owner.get("/api/v1/auth/me").json()["personal_space"]["id"]
    )
    cross_base_url = (
        f"/api/v1/knowledge-bases/{other_base['id']}/tutor/conversations/{created['id']}"
    )
    assert owner.get(cross_base_url).status_code == 404
    assert owner.post(cross_base_url + "/messages", json={"prompt": "steal"}).status_code == 404

    outsider = TestClient(owner.app)
    try:
        register(outsider, f"outsider-{uuid4().hex[:8]}")
        original_url = (
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/tutor/conversations/{created['id']}"
        )
        assert outsider.get(original_url).status_code == 404
        hidden_send = outsider.post(
            original_url + "/messages", json={"prompt": "steal"}
        )
        assert hidden_send.status_code == 404
    finally:
        outsider.close()


@pytest.mark.parametrize(
    ("provider_code", "expected_status"),
    [
        ("llm_timeout", 503),
        ("llm_unauthorized", 503),
        ("llm_provider_error", 503),
        ("llm_network_error", 503),
        ("llm_rate_limited", 429),
    ],
)
def test_provider_errors_have_stable_safe_http_mapping(
    provider_code: str, expected_status: int
) -> None:
    active_client, knowledge_base, engine, _ = make_tutor_client(
        True, adapter=FailingTutorAdapter(provider_code)
    )
    try:
        response = active_client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/tutor/conversations",
            json={"prompt": "path loss"},
        )
        assert response.status_code == expected_status
        expected_detail = {
            "llm_rate_limited": "tutor_provider_rate_limited",
            "llm_timeout": "tutor_provider_timeout",
            "llm_unauthorized": "tutor_provider_key_invalid",
        }.get(provider_code, "tutor_provider_unavailable")
        assert response.json() == {"detail": expected_detail}
        assert "provider body secret" not in response.text
    finally:
        active_client.close()
        engine.dispose()


def test_http_validation_does_not_echo_grounded_prompt_or_secrets(
    configured_client: tuple[TestClient, dict[str, object], object],
) -> None:
    active_client, knowledge_base, _ = configured_client
    response = active_client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/tutor/conversations",
        json={"provider_api_key": "sk-client-secret"},
    )

    assert response.status_code == 422
    assert "sk-client-secret" not in response.text
    assert "untrusted textbook excerpt" not in response.text.casefold()