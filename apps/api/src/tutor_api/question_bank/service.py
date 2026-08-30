import base64
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, load_only

from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_readable_knowledge_base, get_writable_knowledge_base
from tutor_api.knowledge.models import (
    Chunk,
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    IndexVersion,
    IndexVersionState,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeBase,
)
from tutor_api.knowledge.retrieval import chunk_id_from_citation
from tutor_api.question_bank.assessment import (
    QuestionRubric,
    assess_answer,
    compute_mastery_snapshot,
    schedule_review,
)
from tutor_api.question_bank.assessment import QuestionType as AssessmentQuestionType
from tutor_api.question_bank.models import (
    AssessmentErrorType,
    Question,
    QuestionAttempt,
    QuestionAttemptAssessment,
    QuestionVersion,
)
from tutor_api.question_bank.schemas import CreateAttemptRequest, CreateQuestionRequest


@dataclass(frozen=True)
class QuestionResult:
    question: Question
    version: QuestionVersion


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")


def _source_for_citation(
    session: Session, knowledge_base: KnowledgeBase, citation_id: str, secret: str
) -> tuple[Chunk, IndexVersion, DocumentVersion, Document]:
    chunk_id = chunk_id_from_citation(citation_id, knowledge_base.id, secret)
    if chunk_id is None:
        raise _not_found()
    source = session.execute(
        select(Chunk, IndexVersion, DocumentVersion, Document)
        .join(
            IndexVersion,
            and_(
                IndexVersion.id == Chunk.index_version_id,
                IndexVersion.knowledge_base_id == Chunk.knowledge_base_id,
                IndexVersion.space_id == Chunk.space_id,
            ),
        )
        .join(
            DocumentVersion,
            and_(
                DocumentVersion.id == Chunk.document_version_id,
                DocumentVersion.knowledge_base_id == Chunk.knowledge_base_id,
                DocumentVersion.space_id == Chunk.space_id,
            ),
        )
        .join(
            Document,
            and_(
                Document.id == DocumentVersion.document_id,
                Document.knowledge_base_id == DocumentVersion.knowledge_base_id,
                Document.space_id == DocumentVersion.space_id,
            ),
        )
        .where(
            Chunk.id == chunk_id,
            Chunk.knowledge_base_id == knowledge_base.id,
            Chunk.space_id == knowledge_base.space_id,
            IndexVersion.knowledge_base_id == knowledge_base.id,
            IndexVersion.space_id == knowledge_base.space_id,
            IndexVersion.state == IndexVersionState.ACTIVE,
            DocumentVersion.knowledge_base_id == knowledge_base.id,
            DocumentVersion.space_id == knowledge_base.space_id,
            DocumentVersion.state == DocumentVersionState.READY,
            Document.knowledge_base_id == knowledge_base.id,
            Document.space_id == knowledge_base.space_id,
            Document.state == DocumentState.ACTIVE,
        )
    ).one_or_none()
    if source is None:
        raise _not_found()
    return source


def create_question(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    payload: CreateQuestionRequest,
    citation_secret: str,
) -> QuestionResult:
    knowledge_base = get_writable_knowledge_base(session, user, knowledge_base_id)
    chunk, index, document_version, _document = _source_for_citation(
        session, knowledge_base, payload.source_citation_id, citation_secret
    )
    question = Question(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        owner_user_id=knowledge_base.owner_user_id,
        created_by_user_id=user.id,
    )
    session.add(question)
    session.flush()
    version = QuestionVersion(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        question_id=question.id,
        version_number=1,
        document_version_id=document_version.id,
        question_type=payload.question_type,
        prompt=payload.prompt,
        expected_answer=payload.expected_answer,
        expected_keywords=payload.expected_keywords,
        source_chunk_id=chunk.id,
        source_chunk_ordinal=chunk.ordinal,
        source_pointer=chunk.source_pointer,
        source_content_sha256=hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
        source_index_signature=index.index_signature,
        created_by_user_id=user.id,
    )
    session.add(version)
    session.flush()
    return QuestionResult(question=question, version=version)


def list_questions(session: Session, user: User, knowledge_base_id: UUID) -> list[QuestionResult]:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    rows = session.execute(
        select(Question, QuestionVersion)
        .options(
            load_only(
                Question.id,
                Question.knowledge_base_id,
                Question.space_id,
                Question.created_at,
            ),
            load_only(
                QuestionVersion.id,
                QuestionVersion.version_number,
                QuestionVersion.question_type,
                QuestionVersion.prompt,
                QuestionVersion.choices,
                QuestionVersion.difficulty,
            ),
        )
        .join(
            QuestionVersion,
            and_(
                QuestionVersion.question_id == Question.id,
                QuestionVersion.knowledge_base_id == Question.knowledge_base_id,
                QuestionVersion.space_id == Question.space_id,
            ),
        )
        .where(
            Question.knowledge_base_id == knowledge_base.id,
            Question.space_id == knowledge_base.space_id,
            QuestionVersion.version_number == 1,
        )
        # 生成题目带难度（1-5）：按由简到难排列；手动题目无难度排在后面。
        .order_by(
            QuestionVersion.difficulty.asc().nulls_last(),
            Question.created_at,
            Question.id,
        )
    ).all()
    return [QuestionResult(question=question, version=version) for question, version in rows]


def get_question(
    session: Session, user: User, knowledge_base_id: UUID, question_id: UUID
) -> QuestionResult:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    row = session.execute(
        select(Question, QuestionVersion)
        .options(
            load_only(
                Question.id,
                Question.knowledge_base_id,
                Question.space_id,
                Question.created_at,
            ),
            load_only(
                QuestionVersion.id,
                QuestionVersion.version_number,
                QuestionVersion.question_type,
                QuestionVersion.prompt,
                QuestionVersion.choices,
                QuestionVersion.difficulty,
            ),
        )
        .join(
            QuestionVersion,
            and_(
                QuestionVersion.question_id == Question.id,
                QuestionVersion.knowledge_base_id == Question.knowledge_base_id,
                QuestionVersion.space_id == Question.space_id,
            ),
        )
        .where(
            Question.id == question_id,
            Question.knowledge_base_id == knowledge_base.id,
            Question.space_id == knowledge_base.space_id,
            QuestionVersion.version_number == 1,
        )
    ).one_or_none()
    if row is None:
        raise _not_found()
    question, version = row
    return QuestionResult(question=question, version=version)


def _active_index_or_none(session: Session, knowledge_base: KnowledgeBase) -> IndexVersion | None:
    return session.scalar(
        select(IndexVersion).where(
            IndexVersion.knowledge_base_id == knowledge_base.id,
            IndexVersion.space_id == knowledge_base.space_id,
            IndexVersion.state == IndexVersionState.ACTIVE,
        )
    )


def create_question_generation(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    *,
    requested_question_count: int,
) -> IngestionJob:
    """为整个知识库入队一次 AI 课后题生成（由简到难的选择题）。

    同一用户在同一知识库上的进行中任务会被复用，避免重复入队；
    没有可检索分块时拒绝而不是入队一个注定失败的任务。
    """

    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    existing = session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.knowledge_base_id == knowledge_base.id,
            IngestionJob.space_id == knowledge_base.space_id,
            IngestionJob.kind == IngestionJobKind.GENERATE_QUESTIONS,
            IngestionJob.created_by_user_id == user.id,
            IngestionJob.state.in_(
                (
                    IngestionJobState.QUEUED,
                    IngestionJobState.RUNNING,
                    IngestionJobState.RETRY_WAIT,
                )
            ),
        )
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
        .limit(1)
    )
    if existing is not None:
        return existing
    active_index = _active_index_or_none(session, knowledge_base)
    chunk_count = 0
    if active_index is not None:
        chunk_count = session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(
                Chunk.index_version_id == active_index.id,
                Chunk.knowledge_base_id == knowledge_base.id,
                Chunk.space_id == knowledge_base.space_id,
            )
        )
    if not chunk_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="知识库还没有可出题的内容，请先上传资料并等待解析完成。",
        )
    job = IngestionJob(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        kind=IngestionJobKind.GENERATE_QUESTIONS,
        state=IngestionJobState.QUEUED,
        idempotency_key=f"questions:{knowledge_base.id}:{user.id}:{uuid4()}",
        checkpoint={"requested_question_count": requested_question_count},
        created_by_user_id=user.id,
    )
    session.add(job)
    session.flush()
    return job


def get_question_generation(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    generation_id: UUID,
) -> IngestionJob:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    job = session.scalar(
        select(IngestionJob).where(
            IngestionJob.id == generation_id,
            IngestionJob.knowledge_base_id == knowledge_base.id,
            IngestionJob.space_id == knowledge_base.space_id,
            IngestionJob.kind == IngestionJobKind.GENERATE_QUESTIONS,
        )
    )
    if job is None:
        raise _not_found()
    return job


_IDEMPOTENCY_VALUE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


@dataclass(frozen=True)
class AttemptResult:
    attempt: QuestionAttempt
    assessment: QuestionAttemptAssessment
    replayed: bool
    # 答题后才揭示的正确答案与解析（教学要求）；列表/详情接口仍不泄露。
    expected_answer: str | None
    explanation: str | None


@dataclass(frozen=True)
class ReviewItemResult:
    assessment: QuestionAttemptAssessment
    version: QuestionVersion
    question: Question


@dataclass(frozen=True)
class ReviewItemsResult:
    items: list[ReviewItemResult]
    next_cursor: str | None


@dataclass(frozen=True)
class AttemptHistoryItemResult:
    assessment: QuestionAttemptAssessment
    version: QuestionVersion
    question: Question
    attempted_at: datetime


@dataclass(frozen=True)
class AttemptHistoryResult:
    items: list[AttemptHistoryItemResult]
    next_cursor: str | None


def _request_key_hash(value: str) -> str:
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid idempotency key",
        )
    normalized = value.strip()
    if not 1 <= len(normalized) <= 255 or not _IDEMPOTENCY_VALUE.fullmatch(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid idempotency key",
        )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()



def _submission_lock_key(user_id: UUID, question_version_id: UUID) -> int:
    digest = hashlib.sha256(user_id.bytes + question_version_id.bytes).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _lock_submission(session: Session, user_id: UUID, question_version_id: UUID) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _submission_lock_key(user_id, question_version_id)},
    )

def _legacy_attempt_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="attempt assessment is unavailable",
    )


def _replayed_attempt_result(
    session: Session,
    *,
    user_id: UUID,
    version: QuestionVersion,
    request_key_hash: str,
) -> AttemptResult | None:
    row = session.execute(
        select(QuestionAttempt, QuestionAttemptAssessment)
        .outerjoin(
            QuestionAttemptAssessment,
            and_(
                QuestionAttemptAssessment.question_attempt_id == QuestionAttempt.id,
                QuestionAttemptAssessment.space_id == QuestionAttempt.space_id,
                QuestionAttemptAssessment.knowledge_base_id
                == QuestionAttempt.knowledge_base_id,
                QuestionAttemptAssessment.question_version_id
                == QuestionAttempt.question_version_id,
                QuestionAttemptAssessment.user_id == QuestionAttempt.user_id,
            ),
        )
        .where(
            QuestionAttempt.user_id == user_id,
            QuestionAttempt.question_version_id == version.id,
            QuestionAttempt.request_key_hash == request_key_hash,
        )
    ).one_or_none()
    if row is None:
        return None
    attempt, assessment = row
    if assessment is None:
        raise _legacy_attempt_conflict()
    return AttemptResult(
        attempt=attempt,
        assessment=assessment,
        replayed=True,
        expected_answer=version.expected_answer,
        explanation=version.explanation,
    )


def _private_question_version(
    session: Session, knowledge_base: KnowledgeBase, question_version_id: UUID
) -> QuestionVersion:
    version = session.scalar(
        select(QuestionVersion)
        .options(
            load_only(
                QuestionVersion.id,
                QuestionVersion.space_id,
                QuestionVersion.knowledge_base_id,
                QuestionVersion.question_type,
                QuestionVersion.expected_answer,
                QuestionVersion.expected_keywords,
                QuestionVersion.explanation,
            )
        )
        .where(
            QuestionVersion.id == question_version_id,
            QuestionVersion.knowledge_base_id == knowledge_base.id,
            QuestionVersion.space_id == knowledge_base.space_id,
        )
    )
    if version is None:
        raise _not_found()
    return version


def _new_attempt_assessment(**kwargs: object) -> QuestionAttemptAssessment:
    return QuestionAttemptAssessment(**kwargs)

def record_attempt(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    question_version_id: UUID,
    payload: CreateAttemptRequest,
    idempotency_key: str,
) -> AttemptResult:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    version = _private_question_version(session, knowledge_base, question_version_id)
    request_key_hash = _request_key_hash(idempotency_key)
    _lock_submission(session, user.id, version.id)
    replay = _replayed_attempt_result(
        session,
        user_id=user.id,
        version=version,
        request_key_hash=request_key_hash,
    )
    if replay is not None:
        return replay

    rubric = QuestionRubric(
        question_type=AssessmentQuestionType(version.question_type.value),
        expected_answer=version.expected_answer,
        expected_keywords=tuple(version.expected_keywords or ()),
    )
    grading = assess_answer(rubric, payload.answer)
    prior_assessments = session.scalars(
        select(QuestionAttemptAssessment)
        .where(
            QuestionAttemptAssessment.user_id == user.id,
            QuestionAttemptAssessment.question_version_id == version.id,
        )
        .order_by(
            QuestionAttemptAssessment.created_at.desc(),
            QuestionAttemptAssessment.id.desc(),
        )
        .limit(5)
    ).all()
    mastery = compute_mastery_snapshot(
        (assessment.score_basis_points for assessment in reversed(prior_assessments)),
        grading.score_basis_points,
    )
    review = schedule_review(grading.score_basis_points, now=datetime.now(UTC))
    prior_correct_streak = (
        prior_assessments[0].next_correct_streak if prior_assessments else 0
    )
    next_correct_streak = prior_correct_streak + 1 if grading.correct else 0
    attempt = QuestionAttempt(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        question_version_id=version.id,
        user_id=user.id,
        request_key_hash=request_key_hash,
        answer=payload.answer,
    )
    try:
        with session.begin_nested():
            session.add(attempt)
            session.flush()
            assessment = _new_attempt_assessment(
                space_id=knowledge_base.space_id,
                knowledge_base_id=knowledge_base.id,
                question_version_id=version.id,
                user_id=user.id,
                question_attempt_id=attempt.id,
                correct=grading.correct,
                score_basis_points=grading.score_basis_points,
                error_type=AssessmentErrorType(grading.error_type.value),
                needs_review=grading.needs_review,
                mastery_basis_points=mastery.mastery_basis_points,
                mastery_evidence_count=mastery.evidence_count,
                prior_correct_streak=prior_correct_streak,
                next_correct_streak=next_correct_streak,
                review_due_at=review.review_due_at,
                review_interval_days=review.review_interval_days,
                grading_contract_version=grading.grading_contract_version,
                mastery_contract_version=mastery.mastery_contract_version,
                review_policy_version=review.review_policy_version,
            )
            session.add(assessment)
            session.flush()
    except IntegrityError:
        replay = _replayed_attempt_result(
            session,
            user_id=user.id,
            version=version,
            request_key_hash=request_key_hash,
        )
        if replay is None:
            raise
        return replay
    return AttemptResult(
        attempt=attempt,
        assessment=assessment,
        replayed=False,
        expected_answer=version.expected_answer,
        explanation=version.explanation,
    )

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _invalid_review_cursor() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="invalid review cursor",
    )


def _encode_review_cursor(assessment: QuestionAttemptAssessment) -> str:
    payload = json.dumps(
        [
            _as_utc(assessment.review_due_at).isoformat(),
            _as_utc(assessment.created_at).isoformat(),
            str(assessment.id),
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_review_cursor(cursor: str) -> tuple[datetime, datetime, UUID]:
    if not cursor or len(cursor) > 256:
        raise _invalid_review_cursor()
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = base64.b64decode(
            cursor.encode("ascii") + padding.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        review_due_at, created_at, assessment_id = json.loads(payload)
        if not all(isinstance(value, str) for value in (review_due_at, created_at, assessment_id)):
            raise ValueError
        due_at = datetime.fromisoformat(review_due_at)
        attempted_at = datetime.fromisoformat(created_at)
        if due_at.tzinfo is None or attempted_at.tzinfo is None:
            raise ValueError
        return _as_utc(due_at), _as_utc(attempted_at), UUID(assessment_id)
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise _invalid_review_cursor() from None


def list_review_items(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    *,
    scope: str,
    limit: int,
    cursor: str | None,
) -> ReviewItemsResult:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    cursor_values = _decode_review_cursor(cursor) if cursor is not None else None
    newer_assessment = aliased(QuestionAttemptAssessment)
    latest_assessment = ~exists(
        select(newer_assessment.id).where(
            newer_assessment.user_id == QuestionAttemptAssessment.user_id,
            newer_assessment.question_version_id == QuestionAttemptAssessment.question_version_id,
            newer_assessment.knowledge_base_id == QuestionAttemptAssessment.knowledge_base_id,
            newer_assessment.space_id == QuestionAttemptAssessment.space_id,
            or_(
                newer_assessment.created_at > QuestionAttemptAssessment.created_at,
                and_(
                    newer_assessment.created_at == QuestionAttemptAssessment.created_at,
                    newer_assessment.id > QuestionAttemptAssessment.id,
                ),
            ),
        )
    )
    statement = (
        select(QuestionAttemptAssessment, QuestionVersion, Question)
        .join(
            QuestionVersion,
            and_(
                QuestionVersion.id == QuestionAttemptAssessment.question_version_id,
                QuestionVersion.knowledge_base_id
                == QuestionAttemptAssessment.knowledge_base_id,
                QuestionVersion.space_id == QuestionAttemptAssessment.space_id,
            ),
        )
        .join(
            Question,
            and_(
                Question.id == QuestionVersion.question_id,
                Question.knowledge_base_id == QuestionVersion.knowledge_base_id,
                Question.space_id == QuestionVersion.space_id,
            ),
        )
        .options(
            load_only(
                QuestionAttemptAssessment.id,
                QuestionAttemptAssessment.question_version_id,
                QuestionAttemptAssessment.correct,
                QuestionAttemptAssessment.score_basis_points,
                QuestionAttemptAssessment.error_type,
                QuestionAttemptAssessment.needs_review,
                QuestionAttemptAssessment.mastery_basis_points,
                QuestionAttemptAssessment.mastery_evidence_count,
                QuestionAttemptAssessment.review_due_at,
                QuestionAttemptAssessment.review_interval_days,
                QuestionAttemptAssessment.grading_contract_version,
                QuestionAttemptAssessment.mastery_contract_version,
                QuestionAttemptAssessment.review_policy_version,
                QuestionAttemptAssessment.created_at,
            ),
            load_only(
                QuestionVersion.id,
                QuestionVersion.question_id,
                QuestionVersion.question_type,
                QuestionVersion.prompt,
            ),
            load_only(Question.id),
        )
        .where(
            QuestionAttemptAssessment.user_id == user.id,
            QuestionAttemptAssessment.knowledge_base_id == knowledge_base.id,
            QuestionAttemptAssessment.space_id == knowledge_base.space_id,
            QuestionAttemptAssessment.needs_review.is_(True),
            latest_assessment,
        )
    )
    if scope == "due":
        statement = statement.where(QuestionAttemptAssessment.review_due_at <= datetime.now(UTC))
    if cursor_values is not None:
        review_due_at, created_at, assessment_id = cursor_values
        statement = statement.where(
            or_(
                QuestionAttemptAssessment.review_due_at > review_due_at,
                and_(
                    QuestionAttemptAssessment.review_due_at == review_due_at,
                    QuestionAttemptAssessment.created_at > created_at,
                ),
                and_(
                    QuestionAttemptAssessment.review_due_at == review_due_at,
                    QuestionAttemptAssessment.created_at == created_at,
                    QuestionAttemptAssessment.id > assessment_id,
                ),
            )
        )
    rows = session.execute(
        statement.order_by(
            QuestionAttemptAssessment.review_due_at,
            QuestionAttemptAssessment.created_at,
            QuestionAttemptAssessment.id,
        ).limit(limit + 1)
    ).all()
    items = [
        ReviewItemResult(assessment, version, question)
        for assessment, version, question in rows[:limit]
    ]
    next_cursor = _encode_review_cursor(items[-1].assessment) if len(rows) > limit else None
    return ReviewItemsResult(items=items, next_cursor=next_cursor)

def _invalid_attempt_history_cursor() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="invalid attempt history cursor",
    )


def _encode_attempt_history_cursor(item: AttemptHistoryItemResult) -> str:
    payload = json.dumps(
        [_as_utc(item.attempted_at).isoformat(), str(item.assessment.id)],
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_attempt_history_cursor(cursor: str) -> tuple[datetime, UUID]:
    if not cursor or len(cursor) > 256:
        raise _invalid_attempt_history_cursor()
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = base64.b64decode(
            cursor.encode("ascii") + padding.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        attempted_at, assessment_id = json.loads(payload)
        if not isinstance(attempted_at, str) or not isinstance(assessment_id, str):
            raise ValueError
        value = datetime.fromisoformat(attempted_at)
        if value.tzinfo is None:
            raise ValueError
        return _as_utc(value), UUID(assessment_id)
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError, TypeError, json.JSONDecodeError):
        raise _invalid_attempt_history_cursor() from None


def list_attempt_history(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    question_version_id: UUID,
    *,
    limit: int,
    cursor: str | None,
) -> AttemptHistoryResult:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    version_exists = session.scalar(
        select(QuestionVersion)
        .options(load_only(QuestionVersion.id))
        .where(
            QuestionVersion.id == question_version_id,
            QuestionVersion.knowledge_base_id == knowledge_base.id,
            QuestionVersion.space_id == knowledge_base.space_id,
        )
    )
    if version_exists is None:
        raise _not_found()
    cursor_values = _decode_attempt_history_cursor(cursor) if cursor is not None else None
    statement = (
        select(
            QuestionAttemptAssessment,
            QuestionVersion,
            Question,
            QuestionAttempt.created_at,
        )
        .join(
            QuestionAttempt,
            and_(
                QuestionAttempt.id == QuestionAttemptAssessment.question_attempt_id,
                QuestionAttempt.user_id == QuestionAttemptAssessment.user_id,
                QuestionAttempt.question_version_id
                == QuestionAttemptAssessment.question_version_id,
                QuestionAttempt.knowledge_base_id
                == QuestionAttemptAssessment.knowledge_base_id,
                QuestionAttempt.space_id == QuestionAttemptAssessment.space_id,
            ),
        )
        .join(
            QuestionVersion,
            and_(
                QuestionVersion.id == QuestionAttemptAssessment.question_version_id,
                QuestionVersion.knowledge_base_id
                == QuestionAttemptAssessment.knowledge_base_id,
                QuestionVersion.space_id == QuestionAttemptAssessment.space_id,
            ),
        )
        .join(
            Question,
            and_(
                Question.id == QuestionVersion.question_id,
                Question.knowledge_base_id == QuestionVersion.knowledge_base_id,
                Question.space_id == QuestionVersion.space_id,
            ),
        )
        .options(
            load_only(
                QuestionAttemptAssessment.id,
                QuestionAttemptAssessment.question_version_id,
                QuestionAttemptAssessment.correct,
                QuestionAttemptAssessment.score_basis_points,
                QuestionAttemptAssessment.error_type,
                QuestionAttemptAssessment.needs_review,
                QuestionAttemptAssessment.mastery_basis_points,
                QuestionAttemptAssessment.mastery_evidence_count,
                QuestionAttemptAssessment.review_due_at,
                QuestionAttemptAssessment.review_interval_days,
                QuestionAttemptAssessment.grading_contract_version,
                QuestionAttemptAssessment.mastery_contract_version,
                QuestionAttemptAssessment.review_policy_version,
            ),
            load_only(
                QuestionVersion.id,
                QuestionVersion.question_id,
                QuestionVersion.question_type,
                QuestionVersion.prompt,
            ),
            load_only(Question.id),
        )
        .where(
            QuestionAttemptAssessment.user_id == user.id,
            QuestionAttemptAssessment.question_version_id == question_version_id,
            QuestionAttemptAssessment.knowledge_base_id == knowledge_base.id,
            QuestionAttemptAssessment.space_id == knowledge_base.space_id,
        )
    )
    if cursor_values is not None:
        attempted_at, assessment_id = cursor_values
        statement = statement.where(
            or_(
                QuestionAttempt.created_at < attempted_at,
                and_(
                    QuestionAttempt.created_at == attempted_at,
                    QuestionAttemptAssessment.id < assessment_id,
                ),
            )
        )
    rows = session.execute(
        statement.order_by(
            QuestionAttempt.created_at.desc(),
            QuestionAttemptAssessment.id.desc(),
        ).limit(limit + 1)
    ).all()
    items = [
        AttemptHistoryItemResult(assessment, version, question, attempted_at)
        for assessment, version, question, attempted_at in rows[:limit]
    ]
    next_cursor = _encode_attempt_history_cursor(items[-1]) if len(rows) > limit else None
    return AttemptHistoryResult(items=items, next_cursor=next_cursor)
