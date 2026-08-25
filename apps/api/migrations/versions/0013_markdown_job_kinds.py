"""add Markdown generation job kinds

Revision ID: 0013_markdown_job_kinds
Revises: 0012_markdown_drafts_links
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_markdown_job_kinds"
down_revision: str | Sequence[str] | None = "0012_markdown_drafts_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND_CHECK = "kind IN ('parse_document', 'ocr_page', 'build_index', 'generate_markdown', 'index_markdown_links')"  # noqa: E501
_TARGET_CHECK = "(kind = 'parse_document' AND document_id IS NOT NULL AND document_version_id IS NOT NULL AND page_id IS NULL AND index_version_id IS NULL) OR (kind = 'ocr_page' AND document_id IS NOT NULL AND document_version_id IS NOT NULL AND page_id IS NOT NULL AND index_version_id IS NULL) OR (kind = 'build_index' AND document_id IS NULL AND document_version_id IS NULL AND page_id IS NULL AND index_version_id IS NOT NULL) OR (kind IN ('generate_markdown', 'index_markdown_links') AND document_id IS NOT NULL AND document_version_id IS NOT NULL AND page_id IS NULL AND index_version_id IS NULL)"  # noqa: E501


def upgrade() -> None:
    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.drop_constraint("ingestion_job_kind", type_="check")
        batch.drop_constraint("ck_ingestion_target_matches_kind", type_="check")
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=14),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
        batch.create_check_constraint("ingestion_job_kind", _KIND_CHECK)
        batch.create_check_constraint("ck_ingestion_target_matches_kind", _TARGET_CHECK)


def downgrade() -> None:
    old_kind = "kind IN ('parse_document', 'ocr_page', 'build_index')"
    old_target = "(kind = 'parse_document' AND document_id IS NOT NULL AND document_version_id IS NOT NULL AND page_id IS NULL AND index_version_id IS NULL) OR (kind = 'ocr_page' AND document_id IS NOT NULL AND document_version_id IS NOT NULL AND page_id IS NOT NULL AND index_version_id IS NULL) OR (kind = 'build_index' AND document_id IS NULL AND document_version_id IS NULL AND page_id IS NULL AND index_version_id IS NOT NULL)"  # noqa: E501
    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.drop_constraint("ingestion_job_kind", type_="check")
        batch.drop_constraint("ck_ingestion_target_matches_kind", type_="check")
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=20),
            type_=sa.String(length=14),
            existing_nullable=False,
        )
        batch.create_check_constraint("ingestion_job_kind", old_kind)
        batch.create_check_constraint("ck_ingestion_target_matches_kind", old_target)
