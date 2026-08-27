from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status

from tutor_api.core.database import session_scope
from tutor_api.identity.router import CurrentUser, _session_factory
from tutor_api.question_bank.schemas import (
    AttemptHistoryItemResponse,
    AttemptHistoryResponse,
    CreateAttemptRequest,
    CreateQuestionRequest,
    QuestionAttemptAssessmentResponse,
    QuestionResponse,
    ReviewItemResponse,
    ReviewItemsResponse,
)
from tutor_api.question_bank.service import (
    QuestionResult,
    create_question,
    list_attempt_history,
    list_questions,
    list_review_items,
    record_attempt,
)
from tutor_api.question_bank.service import (
    get_question as get_question_service,
)

router = APIRouter(tags=["question bank"])


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

def _citation_secret(request: Request) -> str:
    return request.app.state.settings.object_storage_secret_key.get_secret_value()


def _question_response(result: QuestionResult) -> QuestionResponse:
    return QuestionResponse(
        id=result.question.id,
        question_version_id=result.version.id,
        knowledge_base_id=result.question.knowledge_base_id,
        space_id=result.question.space_id,
        version_number=result.version.version_number,
        question_type=result.version.question_type,
        prompt=result.version.prompt,
        created_at=result.question.created_at,
    )


@router.post(
    "/api/v1/knowledge-bases/{knowledge_base_id}/questions",
    response_model=QuestionResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_question(
    knowledge_base_id: UUID,
    payload: CreateQuestionRequest,
    request: Request,
    current_user: CurrentUser,
) -> QuestionResponse:
    with session_scope(_session_factory(request)) as session:
        result = create_question(
            session,
            current_user,
            knowledge_base_id,
            payload,
            _citation_secret(request),
        )
        return _question_response(result)


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/questions",
    response_model=list[QuestionResponse],
)
def get_questions(
    knowledge_base_id: UUID, request: Request, current_user: CurrentUser
) -> list[QuestionResponse]:
    with session_scope(_session_factory(request)) as session:
        results = list_questions(session, current_user, knowledge_base_id)
        return [_question_response(result) for result in results]


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/questions/{question_id}",
    response_model=QuestionResponse,
)
def get_question(
    knowledge_base_id: UUID, question_id: UUID, request: Request, current_user: CurrentUser
) -> QuestionResponse:
    with session_scope(_session_factory(request)) as session:
        result = get_question_service(session, current_user, knowledge_base_id, question_id)
        return _question_response(result)


@router.post(
    "/api/v1/knowledge-bases/{knowledge_base_id}/question-versions/{question_version_id}/attempts",
    response_model=QuestionAttemptAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_attempt(
    knowledge_base_id: UUID,
    question_version_id: UUID,
    payload: CreateAttemptRequest,
    request: Request,
    response: Response,
    current_user: CurrentUser,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> QuestionAttemptAssessmentResponse:
    with session_scope(_session_factory(request)) as session:
        result = record_attempt(
            session,
            current_user,
            knowledge_base_id,
            question_version_id,
            payload,
            idempotency_key,
        )
        if result.replayed:
            response.status_code = status.HTTP_200_OK
        return QuestionAttemptAssessmentResponse(
            id=result.attempt.id,
            question_version_id=result.attempt.question_version_id,
            created_at=_as_utc(result.attempt.created_at),
            correct=result.assessment.correct,
            score_basis_points=result.assessment.score_basis_points,
            error_type=result.assessment.error_type,
            needs_review=result.assessment.needs_review,
            mastery_basis_points=result.assessment.mastery_basis_points,
            mastery_evidence_count=result.assessment.mastery_evidence_count,
            review_due_at=_as_utc(result.assessment.review_due_at),
            review_interval_days=result.assessment.review_interval_days,
            grading_contract_version=result.assessment.grading_contract_version,
            mastery_contract_version=result.assessment.mastery_contract_version,
            review_policy_version=result.assessment.review_policy_version,
        )


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/review-items",
    response_model=ReviewItemsResponse,
)
def get_review_items(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
    scope: Annotated[Literal["all", "due"], Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> ReviewItemsResponse:
    with session_scope(_session_factory(request)) as session:
        result = list_review_items(
            session,
            current_user,
            knowledge_base_id,
            scope=scope,
            limit=limit,
            cursor=cursor,
        )
        return ReviewItemsResponse(
            items=[
                ReviewItemResponse(
                    question_id=item.question.id,
                    question_version_id=item.version.id,
                    question_type=item.version.question_type,
                    prompt=item.version.prompt,
                    attempted_at=_as_utc(item.assessment.created_at),
                    correct=item.assessment.correct,
                    score_basis_points=item.assessment.score_basis_points,
                    error_type=item.assessment.error_type,
                    needs_review=item.assessment.needs_review,
                    mastery_basis_points=item.assessment.mastery_basis_points,
                    mastery_evidence_count=item.assessment.mastery_evidence_count,
                    review_due_at=_as_utc(item.assessment.review_due_at),
                    review_interval_days=item.assessment.review_interval_days,
                    grading_contract_version=item.assessment.grading_contract_version,
                    mastery_contract_version=item.assessment.mastery_contract_version,
                    review_policy_version=item.assessment.review_policy_version,
                )
                for item in result.items
            ],
            next_cursor=result.next_cursor,
        )

@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/question-versions/"
    "{question_version_id}/attempt-history",
    response_model=AttemptHistoryResponse,
)
def get_attempt_history(
    knowledge_base_id: UUID,
    question_version_id: UUID,
    request: Request,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> AttemptHistoryResponse:
    with session_scope(_session_factory(request)) as session:
        result = list_attempt_history(
            session,
            current_user,
            knowledge_base_id,
            question_version_id,
            limit=limit,
            cursor=cursor,
        )
        return AttemptHistoryResponse(
            items=[
                AttemptHistoryItemResponse(
                    question_id=item.question.id,
                    question_version_id=item.version.id,
                    question_type=item.version.question_type,
                    prompt=item.version.prompt,
                    attempted_at=_as_utc(item.attempted_at),
                    correct=item.assessment.correct,
                    score_basis_points=item.assessment.score_basis_points,
                    error_type=item.assessment.error_type,
                    needs_review=item.assessment.needs_review,
                    mastery_basis_points=item.assessment.mastery_basis_points,
                    mastery_evidence_count=item.assessment.mastery_evidence_count,
                    review_due_at=_as_utc(item.assessment.review_due_at),
                    review_interval_days=item.assessment.review_interval_days,
                    grading_contract_version=item.assessment.grading_contract_version,
                    mastery_contract_version=item.assessment.mastery_contract_version,
                    review_policy_version=item.assessment.review_policy_version,
                )
                for item in result.items
            ],
            next_cursor=result.next_cursor,
        )
