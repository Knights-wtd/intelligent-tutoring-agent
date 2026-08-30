import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_readable_knowledge_base
from tutor_api.knowledge.indexing import EmbeddingAdapter
from tutor_api.knowledge.retrieval import MAX_QUERY_CHARACTERS, SearchHit, search_knowledge
from tutor_api.llm.ports import LlmProviderError, TutorChatAdapter, TutorChatMessage
from tutor_api.llm.prompt_library import (
    TUTOR_FORCED_ANSWER_SYSTEM_PROMPT,
    TUTOR_GROUNDED_SYSTEM_PROMPT,
    TUTOR_NO_EVIDENCE_SYSTEM_PROMPT,
    build_grounded_user_prompt,
    build_no_evidence_user_prompt,
    is_clarify_response,
)
from tutor_api.tutor.models import (
    TutorConversation,
    TutorMessage,
    TutorMessageKind,
    TutorMessageRole,
)

MAX_TUTOR_PROMPT_CHARACTERS = MAX_QUERY_CHARACTERS
MAX_TUTOR_HISTORY_MESSAGES = 10
# 导师的证据来自整个知识库:取全库融合排序的前 12 个块,并以完整原文块(而非
# 500 字符的检索摘要)投喂模型;总量预算防止超出模型上下文窗口。
MAX_TUTOR_SOURCES = 12
MAX_TUTOR_EVIDENCE_CHARACTERS = 20000
_TUTOR_EXCERPT_OVERHEAD_CHARACTERS = 160
# grill 式追问的连续轮次上限:达到后强制作答并声明假设,防止无限追问。
MAX_TUTOR_CLARIFY_ROUNDS = 2


class TutorServiceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class TutorConversationResult:
    conversation: TutorConversation
    messages: tuple[TutorMessage, ...]


def _normalized_prompt(prompt: str) -> str:
    normalized = prompt.strip()
    if not normalized or len(normalized) > MAX_TUTOR_PROMPT_CHARACTERS:
        raise TutorServiceError("tutor_prompt_invalid")
    return normalized


def _conversation_for_scope(
    session: Session,
    *,
    conversation_id: UUID,
    user_id: UUID,
    space_id: UUID,
    knowledge_base_id: UUID,
) -> TutorConversation:
    conversation = session.get(TutorConversation, conversation_id)
    if conversation is None or (
        conversation.user_id,
        conversation.space_id,
        conversation.knowledge_base_id,
    ) != (user_id, space_id, knowledge_base_id):
        raise TutorServiceError("tutor_conversation_not_found")
    return conversation


def _recent_messages(session: Session, conversation_id: UUID) -> tuple[TutorMessage, ...]:
    newest_first = tuple(
        session.scalars(
            select(TutorMessage)
            .where(TutorMessage.conversation_id == conversation_id)
            .order_by(TutorMessage.created_at.desc(), TutorMessage.id.desc())
            .limit(MAX_TUTOR_HISTORY_MESSAGES)
        )
    )
    return tuple(reversed(newest_first))


def _retrieval_query(normalized_prompt: str, history: tuple[TutorMessage, ...]) -> str:
    """Build the retrieval query from the prompt plus recent conversation context.

    Follow-up questions such as “为什么？” carry no topic keywords of their
    own, so the last few history messages anchor retrieval to the topic under
    discussion. The tail of the combined string is kept so the current
    question always survives truncation intact.
    """
    context = [message.content for message in history][-3:]
    combined = "\n".join([*context, normalized_prompt])
    return combined[-MAX_QUERY_CHARACTERS:]


def _trailing_clarify_rounds(history: tuple[TutorMessage, ...]) -> int:
    """Count clarify rounds issued since the last substantive answer.

    User replies sit between clarify rounds, so the walk skips them and only
    stops at an assistant answer; every clarify encountered before that point
    consumes one round of the grill budget.
    """
    rounds = 0
    for message in reversed(history):
        if message.role is not TutorMessageRole.ASSISTANT:
            continue
        if message.kind is not TutorMessageKind.CLARIFY:
            break
        rounds += 1
    return rounds


def _tutor_system_prompt(
    *, has_evidence: bool, clarify_rounds_used: int
) -> str:
    if not has_evidence:
        return TUTOR_NO_EVIDENCE_SYSTEM_PROMPT
    if clarify_rounds_used >= MAX_TUTOR_CLARIFY_ROUNDS:
        return TUTOR_FORCED_ANSWER_SYSTEM_PROMPT
    return TUTOR_GROUNDED_SYSTEM_PROMPT


def _evidence_within_budget(hits: list[SearchHit]) -> list[SearchHit]:
    """Keep the widest set of hits whose excerpts fit the evidence budget.

    Retrieval already ordered the hits by relevance, so truncation drops the
    tail; at least one hit always survives.
    """

    kept: list[SearchHit] = []
    used = 0
    for hit in hits:
        cost = len(hit.excerpt) + _TUTOR_EXCERPT_OVERHEAD_CHARACTERS
        if kept and used + cost > MAX_TUTOR_EVIDENCE_CHARACTERS:
            break
        kept.append(hit)
        used += cost
    return kept


def _message_timestamps(history: tuple[TutorMessage, ...]) -> tuple[datetime, datetime]:
    user_created_at = datetime.now(UTC)
    if history:
        latest_history_time = max(
            message.created_at.replace(tzinfo=UTC)
            if message.created_at.tzinfo is None
            else message.created_at.astimezone(UTC)
            for message in history
        )
        if user_created_at <= latest_history_time:
            user_created_at = latest_history_time + timedelta(microseconds=1)
    return user_created_at, user_created_at + timedelta(microseconds=1)


def _citation_payload(hit: SearchHit) -> dict[str, object]:
    return {
        "id": hit.citation.id,
        "source_name": hit.citation.source_name,
        "page_number": hit.citation.page_number,
    }


def _provider_service_code(provider_code: str) -> str:
    if provider_code == "llm_timeout":
        return "tutor_provider_timeout"
    if provider_code == "llm_rate_limited":
        return "tutor_provider_rate_limited"
    if provider_code == "llm_unauthorized":
        # 401 means the configured key is wrong; surfacing it as generic
        # "unavailable" sends users chasing network problems that don't exist.
        return "tutor_provider_key_invalid"
    return "tutor_provider_unavailable"


def send_tutor_message(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    *,
    prompt: str,
    conversation_id: UUID | None,
    adapter: TutorChatAdapter,
    embedding_adapter: EmbeddingAdapter,
    citation_secret: str,
    concurrency_semaphore: threading.Semaphore | None = None,
) -> TutorConversationResult:
    """Ground and answer a tutor prompt, persisting the exchange.

    The provider call is intentionally executed AFTER the read-only part of the
    transaction is committed (``session.commit()`` below) so the potentially
    long-running LLM request never holds a database transaction or connection;
    messages are written afterwards in a fresh transaction.

    `concurrency_semaphore` bounds concurrent provider calls; the production
    router always passes the per-app semaphore built from
    ``Settings.faro_max_concurrency``. Callers that omit it (legacy test
    callers) run without a bound.
    """
    normalized_prompt = _normalized_prompt(prompt)
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    conversation = (
        _conversation_for_scope(
            session,
            conversation_id=conversation_id,
            user_id=user.id,
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
        )
        if conversation_id is not None
        else TutorConversation(
            user_id=user.id,
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            title=normalized_prompt[:200],
        )
    )
    history = _recent_messages(session, conversation.id) if conversation_id is not None else ()
    hits = _evidence_within_budget(
        list(
            search_knowledge(
                session,
                user,
                knowledge_base.id,
                query=_retrieval_query(normalized_prompt, history),
                limit=MAX_TUTOR_SOURCES,
                embedding_adapter=embedding_adapter,
                citation_secret=citation_secret,
                full_content=True,
            )
        )
    )
    clarify_rounds_used = _trailing_clarify_rounds(history)
    system_prompt = _tutor_system_prompt(
        has_evidence=bool(hits), clarify_rounds_used=clarify_rounds_used
    )
    user_content = (
        build_grounded_user_prompt(normalized_prompt, hits)
        if hits
        else build_no_evidence_user_prompt(normalized_prompt)
    )
    adapter_messages = tuple(
        TutorChatMessage(role=message.role.value, content=message.content) for message in history
    ) + (TutorChatMessage(role="user", content=user_content),)
    # End the read-only transaction before the provider call: the LLM request
    # may take faro_timeout_seconds (default 60s) and must not hold a DB
    # connection or lock for that duration. Nothing has been written yet, so
    # committing here is a no-op persist-wise; writes happen below.
    session.commit()
    if concurrency_semaphore is not None:
        concurrency_semaphore.acquire()
    try:
        completion = adapter.complete_tutor(adapter_messages, system_prompt=system_prompt)
    except LlmProviderError as error:
        raise TutorServiceError(_provider_service_code(error.code)) from None
    finally:
        if concurrency_semaphore is not None:
            concurrency_semaphore.release()

    # 追问预算耗尽后不再落库追问形态:模型若仍输出追问标记,按最终作答处理。
    if clarify_rounds_used >= MAX_TUTOR_CLARIFY_ROUNDS:
        message_kind = TutorMessageKind.ANSWER
    elif is_clarify_response(completion.text):
        message_kind = TutorMessageKind.CLARIFY
    else:
        message_kind = TutorMessageKind.ANSWER

    user_created_at, assistant_created_at = _message_timestamps(history)
    with session.begin_nested():
        if conversation_id is None:
            session.add(conversation)
            session.flush()
        user_message = TutorMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            role=TutorMessageRole.USER,
            content=normalized_prompt,
            citations=[],
            created_at=user_created_at,
        )
        assistant_message = TutorMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            role=TutorMessageRole.ASSISTANT,
            kind=message_kind,
            content=completion.text,
            citations=[_citation_payload(hit) for hit in hits],
            provider_request_id=completion.request_id,
            prompt_tokens=completion.usage.prompt_tokens,
            completion_tokens=completion.usage.completion_tokens,
            created_at=assistant_created_at,
        )
        if conversation_id is not None:
            previous_updated_at = (
                conversation.updated_at.replace(tzinfo=UTC)
                if conversation.updated_at.tzinfo is None
                else conversation.updated_at.astimezone(UTC)
            )
            conversation.updated_at = max(
                previous_updated_at + timedelta(microseconds=1), assistant_created_at
            )
        session.add_all((user_message, assistant_message))
        session.flush()

    return TutorConversationResult(
        conversation=conversation, messages=(user_message, assistant_message)
    )
