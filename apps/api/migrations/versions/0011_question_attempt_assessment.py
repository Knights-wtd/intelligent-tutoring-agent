"""persist immutable question attempt assessment evidence

Revision ID: 0011_question_attempt_assessment
Revises: 0010_question_bank_foundation
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_question_attempt_assessment"
down_revision: str | Sequence[str] | None = "0010_question_bank_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("question_attempts") as batch:
        batch.create_unique_constraint(
            "uq_question_attempt_identity",
            ["id", "space_id", "knowledge_base_id", "question_version_id", "user_id"],
        )
    op.create_table(
        "question_attempt_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("question_version_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("question_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("score_basis_points", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=13), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("mastery_basis_points", sa.Integer(), nullable=False),
        sa.Column("mastery_evidence_count", sa.Integer(), nullable=False),
        sa.Column("prior_correct_streak", sa.Integer(), nullable=False),
        sa.Column("next_correct_streak", sa.Integer(), nullable=False),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_interval_days", sa.Integer(), nullable=False),
        sa.Column("grading_contract_version", sa.String(length=128), nullable=False),
        sa.Column("mastery_contract_version", sa.String(length=128), nullable=False),
        sa.Column("review_policy_version", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "score_basis_points >= 0 AND score_basis_points <= 10000",
            name="ck_question_attempt_assessment_score_range",
        ),
        sa.CheckConstraint(
            "mastery_basis_points >= 0 AND mastery_basis_points <= 10000",
            name="ck_question_attempt_assessment_mastery_range",
        ),
        sa.CheckConstraint(
            "mastery_evidence_count >= 1 AND mastery_evidence_count <= 6",
            name="ck_question_attempt_assessment_evidence_count",
        ),
        sa.CheckConstraint(
            "prior_correct_streak >= 0 AND next_correct_streak >= 0",
            name="ck_question_attempt_assessment_streaks",
        ),
        sa.CheckConstraint(
            "review_interval_days > 0",
            name="ck_question_attempt_assessment_review_interval",
        ),
        sa.CheckConstraint(
            "review_interval_days IN (1, 3, 7) AND "
            "((NOT needs_review AND review_interval_days = 7) OR "
            "(needs_review AND review_interval_days IN (1, 3)))",
            name="ck_question_attempt_assessment_review_policy",
        ),
        sa.CheckConstraint(
            "(correct AND score_basis_points = 10000 AND error_type = 'none' "
            "AND NOT needs_review) OR "
            "(NOT correct AND score_basis_points < 10000 "
            "AND error_type IN ('metacognitive', 'application') AND needs_review "
            "AND (error_type != 'metacognitive' OR score_basis_points = 0))",
            name="ck_question_attempt_assessment_assessment_contract",
        ),
        sa.CheckConstraint(
            "length(grading_contract_version) > 0 AND "
            "length(mastery_contract_version) > 0 AND "
            "length(review_policy_version) > 0",
            name="ck_question_attempt_assessment_contract_versions",
        ),
        sa.CheckConstraint(
            "error_type IN ('none', 'metacognitive', 'application')",
            name="assessment_error_type",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_attempt_id", name="uq_question_attempt_assessment_attempt"
        ),
    )
    for column in (
        "space_id",
        "knowledge_base_id",
        "question_version_id",
        "user_id",
        "question_attempt_id",
    ):
        op.create_index(
            f"ix_question_attempt_assessments_{column}",
            "question_attempt_assessments",
            [column],
        )


def downgrade() -> None:
    for column in (
        "question_attempt_id",
        "user_id",
        "question_version_id",
        "knowledge_base_id",
        "space_id",
    ):
        op.drop_index(
            f"ix_question_attempt_assessments_{column}",
            table_name="question_attempt_assessments",
        )
    op.drop_table("question_attempt_assessments")
    with op.batch_alter_table("question_attempts") as batch:
        batch.drop_constraint("uq_question_attempt_identity", type_="unique")
