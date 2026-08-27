from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tutor_api.core.database import session_scope
from tutor_api.identity.router import CurrentUser, _session_factory
from tutor_api.knowledge.access import get_readable_knowledge_base
from tutor_api.tutor.models import TutorConversation, TutorMessage
from tutor_api.tutor.schemas import (
    TutorConversationResponse,
    TutorMessageResponse,
    TutorSendRequest,
    TutorStatusResponse,
)
from tutor_api.tutor.service import TutorServiceError, send_tutor_message

router = APIRouter(tags=["tutor"])


def _configured(request: Request) -> bool:
    return bool(request.app.state.settings.faro_api_key.get_secret_value().strip())


def _require_configured(request: Request) -> None:
    if not _configured(request):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="tutor_provider_unavailable",
        )


def _service_error(error: TutorServiceError) -> HTTPException:
    status_code = {
        "tutor_conversation_not_found": status.HTTP_404_NOT_FOUND,
        "tutor_prompt_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
        "tutor_provider_rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
        "tutor_provider_timeout": status.HTTP_503_SERVICE_UNAVAILABLE,
        "tutor_provider_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    }.get(error.code, status.HTTP_503_SERVICE_UNAVAILABLE)
    detail = error.code if error.code in {
        "tutor_conversation_not_found",
        "tutor_prompt_invalid",
        "tutor_provider_rate_limited",
        "tutor_provider_timeout",
        "tutor_provider_unavailable",
    } else "tutor_provider_unavailable"
    return HTTPException(status_code=status_code, detail=detail)


def _load_messages(session: Session, conversation_id: UUID) -> tuple[TutorMessage, ...]:
    return tuple(
        session.scalars(
            select(TutorMessage)
            .where(TutorMessage.conversation_id == conversation_id)
            .order_by(TutorMessage.created_at, TutorMessage.id)
        )
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _response(
    conversation: TutorConversation,
    messages: tuple[TutorMessage, ...],
) -> TutorConversationResponse:
    return TutorConversationResponse(
        id=conversation.id,
        knowledge_base_id=conversation.knowledge_base_id,
        title=conversation.title,
        messages=[
            TutorMessageResponse(
                id=message.id,
                role=message.role.value,
                content=message.content,
                citations=message.citations,
                created_at=_utc(message.created_at),
            )
            for message in messages
        ],
        created_at=_utc(conversation.created_at),
        updated_at=_utc(conversation.updated_at),
    )


def _conversation_for_read(
    session: Session,
    current_user: CurrentUser,
    knowledge_base_id: UUID,
    conversation_id: UUID,
) -> TutorConversation:
    knowledge_base = get_readable_knowledge_base(session, current_user, knowledge_base_id)
    conversation = session.get(TutorConversation, conversation_id)
    if conversation is None or (
        conversation.user_id,
        conversation.space_id,
        conversation.knowledge_base_id,
    ) != (current_user.id, knowledge_base.space_id, knowledge_base.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tutor_conversation_not_found",
        )
    return conversation


@router.get("/api/v1/tutor/status", response_model=TutorStatusResponse)
def get_tutor_status(request: Request, current_user: CurrentUser) -> TutorStatusResponse:
    del current_user
    settings = request.app.state.settings
    return TutorStatusResponse(configured=_configured(request), model=settings.faro_model)


@router.post(
    "/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations",
    response_model=TutorConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_tutor_conversation(
    knowledge_base_id: UUID,
    payload: TutorSendRequest,
    request: Request,
    current_user: CurrentUser,
) -> TutorConversationResponse:
    _require_configured(request)
    with session_scope(_session_factory(request)) as session:
        try:
            result = send_tutor_message(
                session,
                current_user,
                knowledge_base_id,
                prompt=payload.prompt,
                conversation_id=None,
                adapter=request.app.state.tutor_adapter,
                embedding_adapter=request.app.state.embedding_adapter,
                citation_secret=request.app.state.settings.effective_citation_hmac_secret,
                concurrency_semaphore=request.app.state.tutor_semaphore,
            )
        except TutorServiceError as error:
            raise _service_error(error) from None
        return _response(result.conversation, _load_messages(session, result.conversation.id))


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations/{conversation_id}",
    response_model=TutorConversationResponse,
)
def get_tutor_conversation(
    knowledge_base_id: UUID,
    conversation_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> TutorConversationResponse:
    with session_scope(_session_factory(request)) as session:
        conversation = _conversation_for_read(
            session, current_user, knowledge_base_id, conversation_id
        )
        return _response(conversation, _load_messages(session, conversation.id))


@router.post(
    "/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations/{conversation_id}/messages",
    response_model=TutorConversationResponse,
)
def post_tutor_message(
    knowledge_base_id: UUID,
    conversation_id: UUID,
    payload: TutorSendRequest,
    request: Request,
    current_user: CurrentUser,
) -> TutorConversationResponse:
    _require_configured(request)
    with session_scope(_session_factory(request)) as session:
        try:
            result = send_tutor_message(
                session,
                current_user,
                knowledge_base_id,
                prompt=payload.prompt,
                conversation_id=conversation_id,
                adapter=request.app.state.tutor_adapter,
                embedding_adapter=request.app.state.embedding_adapter,
                citation_secret=request.app.state.settings.effective_citation_hmac_secret,
                concurrency_semaphore=request.app.state.tutor_semaphore,
            )
        except TutorServiceError as error:
            raise _service_error(error) from None
        return _response(result.conversation, _load_messages(session, result.conversation.id))