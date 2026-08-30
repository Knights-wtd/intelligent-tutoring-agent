"""add AI question generation support

Revision ID: 0018_question_generation
Revises: 0017_recharge_orders
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_question_generation"
down_revision: str | Sequence[str] | None = "0017_recharge_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND_CHECK = (
    "kind IN ('parse_document', 'ocr_page', 'build_index', 'generate_markdown', "
    "'index_markdown_links', 'generate_questions')"
)
_TARGET_CHECK = (
    "(kind = 'parse_document' AND document_id IS NOT NULL "
    "AND document_version_id IS NOT NULL AND page_id IS NULL "
    "AND index_version_id IS NULL) OR "
    "(kind = 'ocr_page' AND document_id IS NOT NULL "
    "AND document_version_id IS NOT NULL AND page_id IS NOT NULL "
    "AND index_version_id IS NULL) OR "
    "(kind = 'build_index' AND document_id IS NULL "
    "AND document_version_id IS NULL AND page_id IS NULL "
    "AND index_version_id IS NOT NULL) OR "
    "(kind IN ('generate_markdown', 'index_markdown_links') AND document_id IS NOT NULL "
    "AND document_version_id IS NOT NULL AND page_id IS NULL "
    "AND index_version_id IS NULL) OR "
    "(kind = 'generate_questions' AND document_id IS NULL "
    "AND document_version_id IS NULL AND page_id IS NULL "
    "AND index_version_id IS NULL)"
)  # noqa: E501


def upgrade() -> None:
    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.drop_constraint("ingestion_job_kind", type_="check")
        batch.drop_constraint("ck_ingestion_target_matches_kind", type_="check")
        batch.create_check_constraint("ingestion_job_kind", _KIND_CHECK)
        batch.create_check_constraint("ck_ingestion_target_matches_kind", _TARGET_CHECK)

    choices_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    with op.batch_alter_table("question_versions") as batch:
        batch.add_column(sa.Column("choices", choices_type, nullable=True))
        batch.add_column(sa.Column("explanation", sa.Text(), nullable=True))
        batch.add_column(sa.Column("difficulty", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("generation_job_id", sa.Uuid(), nullable=True))
        batch.create_check_constraint(
            "ck_question_version_difficulty",
            "difficulty IS NULL OR difficulty BETWEEN 1 AND 5",
        )
    op.create_index(
        "ix_question_versions_generation_job_id", "question_versions", ["generation_job_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_question_versions_generation_job_id", table_name="question_versions")
    with op.batch_alter_table("question_versions") as batch:
        batch.drop_constraint("ck_question_version_difficulty", type_="check")
        batch.drop_column("generation_job_id")
        batch.drop_column("difficulty")
        batch.drop_column("explanation")
        batch.drop_column("choices")

    old_kind = "kind IN ('parse_document', 'ocr_page', 'build_index', 'generate_markdown', 'index_markdown_links')"  # noqa: E501
    old_target = (
        "(kind = 'parse_document' AND document_id IS NOT NULL "
        "AND document_version_id IS NOT NULL AND page_id IS NULL "
        "AND index_version_id IS NULL) OR "
        "(kind = 'ocr_page' AND document_id IS NOT NULL "
        "AND document_version_id IS NOT NULL AND page_id IS NOT NULL "
        "AND index_version_id IS NULL) OR "
        "(kind = 'build_index' AND document_id IS NULL "
        "AND document_version_id IS NULL AND page_id IS NULL "
        "AND index_version_id IS NOT NULL) OR "
        "(kind IN ('generate_markdown', 'index_markdown_links') AND document_id IS NOT NULL "
        "AND document_version_id IS NOT NULL AND page_id IS NULL "
        "AND index_version_id IS NULL)"
    )  # noqa: E501
    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.drop_constraint("ingestion_job_kind", type_="check")
        batch.drop_constraint("ck_ingestion_target_matches_kind", type_="check")
        batch.create_check_constraint("ingestion_job_kind", old_kind)
        batch.create_check_constraint("ck_ingestion_target_matches_kind", old_target)
