from collections.abc import Generator
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, event
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import (
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    KnowledgeBase,
    KnowledgeBaseState,
)
from tutor_api.question_bank.models import (
    AssessmentErrorType,
    Question,
    QuestionAttempt,
    QuestionAttemptAssessment,
    QuestionType,
    QuestionVersion,
)
from tutor_api.spaces.models import Space, SpaceKind

VALID_HASH = "a" * 64
SECOND_HASH = "b" * 64


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    active_session = factory()
    try:
        yield active_session
    finally:
        active_session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_user(session: Session, suffix: str) -> User:
    user = User(
        email=f"{suffix}@example.com",
        username=suffix,
        password_hash="password-hash",
    )
    session.add(user)
    session.flush()
    return user


def create_space(session: Session, user: User, suffix: str) -> Space:
    space = Space(owner_id=user.id, kind=SpaceKind.CLASSROOM, name=f"{suffix} space")
    session.add(space)
    session.flush()
    return space


def create_knowledge_base(session: Session, user: User, space: Space, suffix: str) -> KnowledgeBase:
    knowledge_base = KnowledgeBase(
        space_id=space.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name=f"{suffix} knowledge base",
        state=KnowledgeBaseState.ACTIVE,
    )
    session.add(knowledge_base)
    session.flush()
    return knowledge_base


def create_document_version(
    session: Session,
    user: User,
    space: Space,
    knowledge_base: KnowledgeBase,
    suffix: str,
) -> DocumentVersion:
    document = Document(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        title=f"{suffix}.pdf",
        source_kind="upload",
        source_key=f"uploads/{suffix}.pdf",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        version_number=1,
        content_sha256=VALID_HASH,
        object_key=f"spaces/{space.id}/documents/{document.id}/versions/1/original.pdf",
        content_type="application/pdf",
        state=DocumentVersionState.READY,
        created_by_user_id=user.id,
    )
    session.add(version)
    return version


def create_question(
    session: Session, user: User, space: Space, knowledge_base: KnowledgeBase
) -> Question:
    question = Question(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
    )
    session.add(question)
    session.flush()
    return question


def create_question_version(
    session: Session,
    user: User,
    space: Space,
    knowledge_base: KnowledgeBase,
    question: Question,
    document_version: DocumentVersion,
    *,
    version_number: int = 1,
) -> QuestionVersion:
    version = QuestionVersion(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        question_id=question.id,
        version_number=version_number,
        document_version_id=document_version.id,
        question_type=QuestionType.SHORT,
        prompt="State the theorem.",
        expected_answer="a squared plus b squared equals c squared",
        expected_keywords=["Pythagorean", "squared"],
        source_chunk_id=uuid4(),
        source_chunk_ordinal=0,
        source_pointer="page:1/block:0/chunk:0",
        source_content_sha256=SECOND_HASH,
        source_index_signature="index:immutable-v1",
        created_by_user_id=user.id,
    )
    session.add(version)
    return version


def test_question_rejects_knowledge_base_from_another_space(session: Session) -> None:
    user = create_user(session, "question-space")
    first_space = create_space(session, user, "question-first")
    second_space = create_space(session, user, "question-second")
    knowledge_base = create_knowledge_base(session, user, first_space, "question")
    session.add(
        Question(
            space_id=second_space.id,
            knowledge_base_id=knowledge_base.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_question_version_rejects_cross_tenant_question_and_document_anchors(
    session: Session,
) -> None:
    user = create_user(session, "version-tenant")
    first_space = create_space(session, user, "version-first")
    second_space = create_space(session, user, "version-second")
    first_knowledge_base = create_knowledge_base(session, user, first_space, "version-first")
    second_knowledge_base = create_knowledge_base(session, user, first_space, "version-second")
    other_space_knowledge_base = create_knowledge_base(session, user, second_space, "version-other")
    question = create_question(session, user, first_space, first_knowledge_base)
    second_kb_document_version = create_document_version(
        session, user, first_space, second_knowledge_base, "second-kb"
    )
    other_space_document_version = create_document_version(
        session, user, second_space, other_space_knowledge_base, "other-space"
    )
    session.commit()

    for document_version in (second_kb_document_version, other_space_document_version):
        active = sessionmaker(bind=session.get_bind())()
        try:
            create_question_version(
                active,
                user,
                first_space,
                first_knowledge_base,
                active.get(Question, question.id),
                active.get(DocumentVersion, document_version.id),
            )
            with pytest.raises(IntegrityError):
                active.commit()
        finally:
            active.rollback()
            active.close()

    active = sessionmaker(bind=session.get_bind())()
    try:
        create_question_version(
            active,
            user,
            first_space,
            second_knowledge_base,
            active.get(Question, question.id),
            active.get(DocumentVersion, second_kb_document_version.id),
        )
        with pytest.raises(IntegrityError):
            active.commit()
    finally:
        active.rollback()
        active.close()


def test_question_version_number_is_unique_per_question(session: Session) -> None:
    user = create_user(session, "version-unique")
    space = create_space(session, user, "version-unique")
    knowledge_base = create_knowledge_base(session, user, space, "version-unique")
    document_version = create_document_version(
        session, user, space, knowledge_base, "version-unique"
    )
    question = create_question(session, user, space, knowledge_base)
    create_question_version(session, user, space, knowledge_base, question, document_version)
    session.commit()

    session.add(
        QuestionVersion(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            question_id=question.id,
            version_number=1,
            document_version_id=document_version.id,
            question_type=QuestionType.CHOICE,
            prompt="Duplicate version.",
            source_chunk_id=uuid4(),
            source_chunk_ordinal=1,
            source_pointer="page:1/block:0/chunk:1",
            source_content_sha256=SECOND_HASH,
            source_index_signature="index:immutable-v1",
            created_by_user_id=user.id,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_question_attempts_enforce_tenant_aware_version_link_and_idempotency(
    session: Session,
) -> None:
    user = create_user(session, "attempts")
    space = create_space(session, user, "attempts")
    other_space = create_space(session, user, "attempts-other")
    knowledge_base = create_knowledge_base(session, user, space, "attempts")
    document_version = create_document_version(session, user, space, knowledge_base, "attempts")
    question = create_question(session, user, space, knowledge_base)
    question_version = create_question_version(
        session, user, space, knowledge_base, question, document_version
    )
    session.commit()

    session.add(
        QuestionAttempt(
            space_id=other_space.id,
            knowledge_base_id=knowledge_base.id,
            question_version_id=question_version.id,
            user_id=user.id,
            request_key_hash=VALID_HASH,
            answer="cross-space answer",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    other_knowledge_base = create_knowledge_base(session, user, space, "attempts-other-kb")
    session.add(
        QuestionAttempt(
            space_id=space.id,
            knowledge_base_id=other_knowledge_base.id,
            question_version_id=question_version.id,
            user_id=user.id,
            request_key_hash=VALID_HASH,
            answer="cross-knowledge-base answer",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    first_attempt = QuestionAttempt(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        question_version_id=question_version.id,
        user_id=user.id,
        request_key_hash=VALID_HASH,
        answer="first answer",
    )
    session.add(first_attempt)
    session.commit()
    session.add(
        QuestionAttempt(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            question_version_id=question_version.id,
            user_id=user.id,
            request_key_hash=VALID_HASH,
            answer="retry answer",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_question_bank_has_no_chunk_foreign_key() -> None:
    question_bank_tables = (
        Question.__table__,
        QuestionVersion.__table__,
        QuestionAttempt.__table__,
    )
    foreign_key_targets = {
        foreign_key.target_fullname
        for table in question_bank_tables
        for foreign_key in table.foreign_keys
    }

    assert "chunks.id" not in foreign_key_targets
    assert all("chunks." not in target for target in foreign_key_targets)
    assert QuestionVersion.__table__.c.source_chunk_id.foreign_keys == set()


@pytest.mark.parametrize("invalid_hash", ["a" * 63, "a" * 65, "G" * 64, "-" * 64])
def test_question_bank_hashes_reject_invalid_values(session: Session, invalid_hash: str) -> None:
    user = create_user(session, f"hash-{len(invalid_hash)}-{invalid_hash[:1]}")
    space = create_space(session, user, "hash")
    knowledge_base = create_knowledge_base(session, user, space, "hash")
    document_version = create_document_version(session, user, space, knowledge_base, "hash")
    question = create_question(session, user, space, knowledge_base)
    question_version = create_question_version(
        session, user, space, knowledge_base, question, document_version
    )
    session.commit()
    session.add(
        QuestionAttempt(
            space_id=space.id,
            knowledge_base_id=knowledge_base.id,
            question_version_id=question_version.id,
            user_id=user.id,
            request_key_hash=invalid_hash,
            answer="invalid hash",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_question_version_source_hash_rejects_invalid_value(session: Session) -> None:
    user = create_user(session, "source-hash")
    space = create_space(session, user, "source-hash")
    knowledge_base = create_knowledge_base(session, user, space, "source-hash")
    document_version = create_document_version(session, user, space, knowledge_base, "source-hash")
    question = create_question(session, user, space, knowledge_base)
    question_version = create_question_version(
        session, user, space, knowledge_base, question, document_version
    )
    question_version.source_content_sha256 = "G" * 64

    with pytest.raises(IntegrityError):
        session.commit()


def test_expected_keywords_uses_jsonb_only_on_postgresql() -> None:
    expected_keywords_type = QuestionVersion.__table__.c.expected_keywords.type

    assert isinstance(expected_keywords_type.dialect_impl(postgresql.dialect()), JSONB)
    assert isinstance(expected_keywords_type.dialect_impl(sqlite.dialect()), JSON)
ASSESSMENT_CONTRACT = "question-bank-grading-v1"
MASTERY_CONTRACT = "question-bank-mastery-v1"
REVIEW_CONTRACT = "question-bank-review-v1"


@pytest.fixture
def assessment_session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    tables = (
        User.__table__,
        Space.__table__,
        KnowledgeBase.__table__,
        Document.__table__,
        DocumentVersion.__table__,
        Question.__table__,
        QuestionVersion.__table__,
        QuestionAttempt.__table__,
        QuestionAttemptAssessment.__table__,
    )
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine)
    active_session = factory()
    try:
        yield active_session
    finally:
        active_session.close()
        Base.metadata.drop_all(engine, tables=tuple(reversed(tables)))
        engine.dispose()


def create_question_attempt(
    session: Session,
    user: User,
    space: Space,
    knowledge_base: KnowledgeBase,
    question_version: QuestionVersion,
    *,
    request_key_hash: str = VALID_HASH,
) -> QuestionAttempt:
    attempt = QuestionAttempt(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        question_version_id=question_version.id,
        user_id=user.id,
        request_key_hash=request_key_hash,
        answer="learner answer",
    )
    session.add(attempt)
    session.flush()
    return attempt


def create_assessment(
    attempt: QuestionAttempt,
    *,
    space_id=None,
    knowledge_base_id=None,
    question_version_id=None,
    user_id=None,
    question_attempt_id=None,
    correct: bool = True,
    score_basis_points: int = 10_000,
    error_type: AssessmentErrorType | str = AssessmentErrorType.NONE,
    needs_review: bool = False,
    mastery_basis_points: int = 10_000,
    mastery_evidence_count: int = 1,
    prior_correct_streak: int = 0,
    next_correct_streak: int = 1,
    review_interval_days: int = 7,
    grading_contract_version: str = ASSESSMENT_CONTRACT,
    mastery_contract_version: str = MASTERY_CONTRACT,
    review_policy_version: str = REVIEW_CONTRACT,
) -> QuestionAttemptAssessment:
    return QuestionAttemptAssessment(
        space_id=attempt.space_id if space_id is None else space_id,
        knowledge_base_id=attempt.knowledge_base_id
        if knowledge_base_id is None
        else knowledge_base_id,
        question_version_id=attempt.question_version_id
        if question_version_id is None
        else question_version_id,
        user_id=attempt.user_id if user_id is None else user_id,
        question_attempt_id=attempt.id if question_attempt_id is None else question_attempt_id,
        correct=correct,
        score_basis_points=score_basis_points,
        error_type=error_type,
        needs_review=needs_review,
        mastery_basis_points=mastery_basis_points,
        mastery_evidence_count=mastery_evidence_count,
        prior_correct_streak=prior_correct_streak,
        next_correct_streak=next_correct_streak,
        review_due_at=datetime(2026, 8, 27, tzinfo=UTC),
        review_interval_days=review_interval_days,
        grading_contract_version=grading_contract_version,
        mastery_contract_version=mastery_contract_version,
        review_policy_version=review_policy_version,
    )


def create_attempt_context(
    session: Session, suffix: str
) -> tuple[User, Space, KnowledgeBase, QuestionVersion, QuestionAttempt]:
    user = create_user(session, f"assessment-{suffix}")
    space = create_space(session, user, f"assessment-{suffix}")
    knowledge_base = create_knowledge_base(session, user, space, f"assessment-{suffix}")
    document_version = create_document_version(
        session, user, space, knowledge_base, f"assessment-{suffix}"
    )
    question = create_question(session, user, space, knowledge_base)
    question_version = create_question_version(
        session, user, space, knowledge_base, question, document_version
    )
    session.flush()
    attempt = create_question_attempt(
        session, user, space, knowledge_base, question_version
    )
    return user, space, knowledge_base, question_version, attempt


def test_question_attempt_assessment_persists_server_determined_evidence(
    assessment_session: Session,
) -> None:
    _, _, _, _, attempt = create_attempt_context(assessment_session, "successful")
    assessment = create_assessment(attempt)
    assessment_session.add(assessment)
    assessment_session.commit()

    assert assessment.question_attempt_id == attempt.id
    assert assessment.prior_correct_streak == 0
    assert assessment.next_correct_streak == 1
    assert set(QuestionAttemptAssessment.__table__.c.keys()) == {
        "id",
        "space_id",
        "knowledge_base_id",
        "question_version_id",
        "user_id",
        "question_attempt_id",
        "correct",
        "score_basis_points",
        "error_type",
        "needs_review",
        "mastery_basis_points",
        "mastery_evidence_count",
        "prior_correct_streak",
        "next_correct_streak",
        "review_due_at",
        "review_interval_days",
        "grading_contract_version",
        "mastery_contract_version",
        "review_policy_version",
        "created_at",
    }


def test_question_attempt_assessment_rejects_cross_attempt_identity(
    assessment_session: Session,
) -> None:
    user, space, knowledge_base, question_version, attempt = create_attempt_context(
        assessment_session, "primary"
    )
    other_user, other_space, other_knowledge_base, other_question_version, other_attempt = (
        create_attempt_context(assessment_session, "other")
    )
    same_space_other_kb = create_knowledge_base(
        assessment_session, user, space, "assessment-other-kb"
    )
    other_document_version = create_document_version(
        assessment_session, user, space, knowledge_base, "assessment-other-version"
    )
    other_question = create_question(assessment_session, user, space, knowledge_base)
    same_kb_other_version = create_question_version(
        assessment_session,
        user,
        space,
        knowledge_base,
        other_question,
        other_document_version,
    )
    alternate_user = create_user(assessment_session, "assessment-alternate-user")
    assessment_session.commit()

    invalid_links = (
        {"space_id": other_space.id},
        {"knowledge_base_id": same_space_other_kb.id},
        {"question_version_id": same_kb_other_version.id},
        {"user_id": alternate_user.id},
        {"question_attempt_id": other_attempt.id},
    )
    for overrides in invalid_links:
        assessment_session.add(create_assessment(attempt, **overrides))
        with pytest.raises(IntegrityError):
            assessment_session.commit()
        assessment_session.rollback()

    assert other_user.id != user.id
    assert other_knowledge_base.id != knowledge_base.id
    assert other_question_version.id != question_version.id


def test_question_attempt_assessment_allows_only_one_evidence_row_per_attempt(
    assessment_session: Session,
) -> None:
    _, _, _, _, attempt = create_attempt_context(assessment_session, "one-to-one")
    assessment_session.add(create_assessment(attempt))
    assessment_session.commit()
    assessment_session.add(create_assessment(attempt))

    with pytest.raises(IntegrityError):
        assessment_session.commit()


@pytest.mark.parametrize(
    ("overrides", "error_types"),
    [
        ({"score_basis_points": -1}, (IntegrityError,)),
        ({"score_basis_points": 10_001}, (IntegrityError,)),
        ({"mastery_basis_points": -1}, (IntegrityError,)),
        ({"mastery_basis_points": 10_001}, (IntegrityError,)),
        ({"mastery_evidence_count": 0}, (IntegrityError,)),
        ({"mastery_evidence_count": 7}, (IntegrityError,)),
        ({"prior_correct_streak": -1}, (IntegrityError,)),
        ({"next_correct_streak": -1}, (IntegrityError,)),
        ({"review_interval_days": 0}, (IntegrityError,)),
        ({"review_interval_days": 2}, (IntegrityError,)),
        ({"grading_contract_version": ""}, (IntegrityError,)),
        ({"mastery_contract_version": ""}, (IntegrityError,)),
        ({"review_policy_version": ""}, (IntegrityError,)),
        ({"error_type": "unknown"}, (IntegrityError, StatementError)),
        (
            {
                "correct": False,
                "score_basis_points": 10_000,
                "error_type": AssessmentErrorType.APPLICATION,
                "needs_review": True,
                "review_interval_days": 1,
                "next_correct_streak": 0,
            },
            (IntegrityError,),
        ),
        (
            {
                "correct": False,
                "score_basis_points": 5_000,
                "error_type": AssessmentErrorType.NONE,
                "needs_review": True,
                "review_interval_days": 1,
                "next_correct_streak": 0,
            },
            (IntegrityError,),
        ),
        (
            {
                "correct": False,
                "score_basis_points": 5_000,
                "error_type": AssessmentErrorType.METACOGNITIVE,
                "needs_review": True,
                "review_interval_days": 1,
                "next_correct_streak": 0,
            },
            (IntegrityError,),
        ),
        (
            {
                "correct": False,
                "score_basis_points": 0,
                "error_type": AssessmentErrorType.METACOGNITIVE,
                "needs_review": False,
                "review_interval_days": 7,
                "next_correct_streak": 0,
            },
            (IntegrityError,),
        ),
        (
            {
                "correct": True,
                "score_basis_points": 10_000,
                "error_type": AssessmentErrorType.NONE,
                "needs_review": True,
                "review_interval_days": 1,
            },
            (IntegrityError,),
        ),
    ],
)
def test_question_attempt_assessment_rejects_invalid_evidence_contracts(
    assessment_session: Session,
    overrides: dict[str, object],
    error_types: tuple[type[Exception], ...],
) -> None:
    _, _, _, _, attempt = create_attempt_context(assessment_session, str(uuid4()))
    assessment_session.add(create_assessment(attempt, **overrides))

    with pytest.raises(error_types):
        assessment_session.commit()


def test_question_attempt_assessment_orm_constraints_match_v1_contract() -> None:
    assessment_table = QuestionAttemptAssessment.__table__
    constraint_names = {constraint.name for constraint in assessment_table.constraints}
    attempt_constraint_names = {
        constraint.name for constraint in QuestionAttempt.__table__.constraints
    }

    assert {
        "uq_question_attempt_assessment_attempt",
        "fk_question_attempt_assessment_attempt_identity",
        "ck_question_attempt_assessment_score_range",
        "ck_question_attempt_assessment_mastery_range",
        "ck_question_attempt_assessment_evidence_count",
        "ck_question_attempt_assessment_streaks",
        "ck_question_attempt_assessment_review_interval",
        "ck_question_attempt_assessment_review_policy",
        "ck_question_attempt_assessment_assessment_contract",
        "ck_question_attempt_assessment_contract_versions",
    }.issubset(constraint_names)
    assert "uq_question_attempt_identity" in attempt_constraint_names
    assert assessment_table.c.review_due_at.type.timezone is True
    assert assessment_table.c.grading_contract_version.type.length == 128


def test_question_attempt_assessment_migration_supports_sqlite_online_rebuild(
    tmp_path: Path,
) -> None:
    from runpy import run_path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0011_question_attempt_assessment.py"
    )
    namespace = run_path(str(migration_path))
    engine = create_engine(f"sqlite:///{tmp_path / 'assessment-migration.sqlite'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE question_attempts (
                    id CHAR(32) NOT NULL,
                    space_id CHAR(32) NOT NULL,
                    knowledge_base_id CHAR(32) NOT NULL,
                    question_version_id CHAR(32) NOT NULL,
                    user_id CHAR(32) NOT NULL,
                    PRIMARY KEY (id)
                )
                """
            )
            namespace["upgrade"].__globals__["op"] = Operations(
                MigrationContext.configure(connection)
            )
            namespace["upgrade"]()
            assert {
                constraint["name"]
                for constraint in inspect(connection).get_unique_constraints("question_attempts")
            } == {"uq_question_attempt_identity"}

            namespace["downgrade"]()
            assert inspect(connection).get_unique_constraints("question_attempts") == []
    finally:
        engine.dispose()

def test_question_attempt_assessment_migration_renders_postgresql_upgrade_and_downgrade_sql(
    ) -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0011_question_attempt_assessment.py"
    )
    migration_source = migration_path.read_text(encoding="utf-8")
    assert 'revision: str = "0011_question_attempt_assessment"' in migration_source
    assert (
        'down_revision: str | Sequence[str] | None = "0010_question_bank_foundation"'
        in migration_source
    )

    upgrade_output = StringIO()
    upgrade_config = Config(
        str(Path(__file__).parents[1] / "alembic.ini"), output_buffer=upgrade_output
    )
    upgrade_config.set_main_option(
        "sqlalchemy.url", "postgresql+psycopg://offline:offline@localhost:5432/offline"
    )
    command.upgrade(upgrade_config, "0011_question_attempt_assessment", sql=True)
    upgrade_sql = " ".join(upgrade_output.getvalue().lower().split())
    assert (
        "alter table question_attempts add constraint "
        "uq_question_attempt_identity unique" in upgrade_sql
    )
    assert "create table question_attempt_assessments" in upgrade_sql
    assert (
        "constraint fk_question_attempt_assessment_attempt_identity foreign key"
        in upgrade_sql
    )
    assert (
        "constraint uq_question_attempt_assessment_attempt unique "
        "(question_attempt_id)" in upgrade_sql
    )
    assert "review_interval_days in (1, 3, 7)" in upgrade_sql
    assert "error_type in ('none', 'metacognitive', 'application')" in upgrade_sql

    downgrade_output = StringIO()
    downgrade_config = Config(
        str(Path(__file__).parents[1] / "alembic.ini"), output_buffer=downgrade_output
    )
    downgrade_config.set_main_option(
        "sqlalchemy.url", "postgresql+psycopg://offline:offline@localhost:5432/offline"
    )
    command.downgrade(
        downgrade_config,
        "0011_question_attempt_assessment:0010_question_bank_foundation",
        sql=True,
    )
    downgrade_sql = " ".join(downgrade_output.getvalue().lower().split())
    assert "drop table question_attempt_assessments" in downgrade_sql
    assert (
        "alter table question_attempts drop constraint "
        "uq_question_attempt_identity" in downgrade_sql
    )
