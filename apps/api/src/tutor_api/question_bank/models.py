from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.core.database import Base


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [member.value for member in values],
    )


def _sha256_check(column_name: str) -> str:
    stripped = column_name
    for character in "0123456789abcdef":
        stripped = f"replace({stripped}, '{character}', '')"
    return f"length({column_name}) = 64 AND {stripped} = ''"


class QuestionType(StrEnum):
    CHOICE = "choice"
    SHORT = "short"
    OPEN = "open"


class AssessmentErrorType(StrEnum):
    NONE = "none"
    METACOGNITIVE = "metacognitive"
    APPLICATION = "application"


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("id", "knowledge_base_id", "space_id", name="uq_question_id_kb_space"),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_question_knowledge_base_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QuestionVersion(Base):
    __tablename__ = "question_versions"
    __table_args__ = (
        UniqueConstraint(
            "id", "knowledge_base_id", "space_id", name="uq_question_version_id_kb_space"
        ),
        UniqueConstraint("question_id", "version_number", name="uq_question_version_number"),
        CheckConstraint("version_number > 0", name="ck_question_version_number_positive"),
        CheckConstraint("source_chunk_ordinal >= 0", name="ck_question_version_chunk_ordinal"),
        CheckConstraint(
            _sha256_check("source_content_sha256"), name="ck_question_version_source_sha256"
        ),
        ForeignKeyConstraint(
            ["question_id", "knowledge_base_id", "space_id"],
            ["questions.id", "questions.knowledge_base_id", "questions.space_id"],
            name="fk_question_version_question_kb_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "knowledge_base_id", "space_id"],
            [
                "document_versions.id",
                "document_versions.knowledge_base_id",
                "document_versions.space_id",
            ],
            name="fk_question_version_document_version_kb_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    question_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    question_type: Mapped[QuestionType] = mapped_column(
        _enum(QuestionType, "question_type"), nullable=False, index=True
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    expected_keywords: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    source_chunk_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    source_chunk_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_pointer: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_index_signature: Mapped[str] = mapped_column(String(512), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QuestionAttempt(Base):
    __tablename__ = "question_attempts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "question_version_id",
            "request_key_hash",
            name="uq_question_attempt_request_key",
        ),
        UniqueConstraint(
            "id",
            "space_id",
            "knowledge_base_id",
            "question_version_id",
            "user_id",
            name="uq_question_attempt_identity",
        ),
        CheckConstraint(_sha256_check("request_key_hash"), name="ck_question_attempt_request_hash"),
        ForeignKeyConstraint(
            ["question_version_id", "knowledge_base_id", "space_id"],
            [
                "question_versions.id",
                "question_versions.knowledge_base_id",
                "question_versions.space_id",
            ],
            name="fk_question_attempt_version_kb_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    question_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

class QuestionAttemptAssessment(Base):
    __tablename__ = "question_attempt_assessments"
    __table_args__ = (
        UniqueConstraint(
            "question_attempt_id", name="uq_question_attempt_assessment_attempt"
        ),
        CheckConstraint(
            "score_basis_points >= 0 AND score_basis_points <= 10000",
            name="ck_question_attempt_assessment_score_range",
        ),
        CheckConstraint(
            "mastery_basis_points >= 0 AND mastery_basis_points <= 10000",
            name="ck_question_attempt_assessment_mastery_range",
        ),
        CheckConstraint(
            "mastery_evidence_count >= 1 AND mastery_evidence_count <= 6",
            name="ck_question_attempt_assessment_evidence_count",
        ),
        CheckConstraint(
            "prior_correct_streak >= 0 AND next_correct_streak >= 0",
            name="ck_question_attempt_assessment_streaks",
        ),
        CheckConstraint(
            "review_interval_days > 0",
            name="ck_question_attempt_assessment_review_interval",
        ),
        CheckConstraint(
            "review_interval_days IN (1, 3, 7) AND "
            "((NOT needs_review AND review_interval_days = 7) OR "
            "(needs_review AND review_interval_days IN (1, 3)))",
            name="ck_question_attempt_assessment_review_policy",
        ),
        CheckConstraint(
            "(correct AND score_basis_points = 10000 AND error_type = 'none' "
            "AND NOT needs_review) OR "
            "(NOT correct AND score_basis_points < 10000 "
            "AND error_type IN ('metacognitive', 'application') AND needs_review "
            "AND (error_type != 'metacognitive' OR score_basis_points = 0))",
            name="ck_question_attempt_assessment_assessment_contract",
        ),
        CheckConstraint(
            "length(grading_contract_version) > 0 AND "
            "length(mastery_contract_version) > 0 AND "
            "length(review_policy_version) > 0",
            name="ck_question_attempt_assessment_contract_versions",
        ),
        ForeignKeyConstraint(
            [
                "question_attempt_id",
                "space_id",
                "knowledge_base_id",
                "question_version_id",
                "user_id",
            ],
            [
                "question_attempts.id",
                "question_attempts.space_id",
                "question_attempts.knowledge_base_id",
                "question_attempts.question_version_id",
                "question_attempts.user_id",
            ],
            name="fk_question_attempt_assessment_attempt_identity",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    question_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    question_attempt_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    error_type: Mapped[AssessmentErrorType] = mapped_column(
        _enum(AssessmentErrorType, "assessment_error_type"), nullable=False
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mastery_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    mastery_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # These record the streak immediately before and immediately after this attempt.
    prior_correct_streak: Mapped[int] = mapped_column(Integer, nullable=False)
    next_correct_streak: Mapped[int] = mapped_column(Integer, nullable=False)
    review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    grading_contract_version: Mapped[str] = mapped_column(String(128), nullable=False)
    mastery_contract_version: Mapped[str] = mapped_column(String(128), nullable=False)
    review_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
