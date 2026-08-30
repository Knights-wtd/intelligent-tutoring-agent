from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from tutor_api.core.database import session_scope
from tutor_api.identity.router import CurrentUser, _session_factory
from tutor_api.tutor.schemas import TutorConversationResponse
from tutor_api.tutor.service import (
    LegacyTutorConversationNotFound,
    get_legacy_tutor_conversation,
    list_legacy_tutor_conversations,
)

router = APIRouter(tags=["tutor"])
_RETIRED_RESPONSE = {
    "code": "legacy_tutor_retired",
    "replacement": "/api/v1/agent",
}


def _retired() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content=_RETIRED_RESPONSE,
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="tutor_conversation_not_found",
    )


@router.get(
    "/api/v1/tutor/conversations",
    response_model=list[TutorConversationResponse],
)
def get_all_tutor_conversations(
    request: Request,
    current_user: CurrentUser,
) -> list[TutorConversationResponse]:
    with session_scope(_session_factory(request)) as session:
        return list_legacy_tutor_conversations(session, current_user)


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations",
    response_model=list[TutorConversationResponse],
)
def get_tutor_conversations(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> list[TutorConversationResponse]:
    with session_scope(_session_factory(request)) as session:
        return list_legacy_tutor_conversations(
            session,
            current_user,
            knowledge_base_id=knowledge_base_id,
        )


@router.get(
    "/api/v1/tutor/conversations/{conversation_id}",
    response_model=TutorConversationResponse,
)
def get_tutor_conversation_by_id(
    conversation_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> TutorConversationResponse:
    with session_scope(_session_factory(request)) as session:
        try:
            return get_legacy_tutor_conversation(
                session,
                current_user,
                conversation_id,
            )
        except LegacyTutorConversationNotFound:
            raise _not_found() from None


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
        try:
            return get_legacy_tutor_conversation(
                session,
                current_user,
                conversation_id,
                knowledge_base_id=knowledge_base_id,
            )
        except LegacyTutorConversationNotFound:
            raise _not_found() from None


@router.post("/api/v1/tutor/conversations")
def post_global_tutor_conversation(current_user: CurrentUser) -> JSONResponse:
    del current_user
    return _retired()


@router.post("/api/v1/tutor/messages")
def post_global_tutor_message(current_user: CurrentUser) -> JSONResponse:
    del current_user
    return _retired()


@router.post("/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations")
def post_tutor_conversation(
    knowledge_base_id: UUID,
    current_user: CurrentUser,
) -> JSONResponse:
    del knowledge_base_id, current_user
    return _retired()


@router.post(
    "/api/v1/knowledge-bases/{knowledge_base_id}/tutor/conversations/{conversation_id}/messages"
)
def post_tutor_message(
    knowledge_base_id: UUID,
    conversation_id: UUID,
    current_user: CurrentUser,
) -> JSONResponse:
    del knowledge_base_id, conversation_id, current_user
    return _retired()
