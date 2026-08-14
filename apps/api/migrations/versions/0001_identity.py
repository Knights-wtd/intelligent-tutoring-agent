"""create identity and classroom schema

Revision ID: 0001_identity
Revises:
Create Date: 2026-08-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_identity"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table(
        "spaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=9), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_spaces_owner_id", "spaces", ["owner_id"])
    op.create_index("ix_spaces_kind", "spaces", ["kind"])
    op.create_index(
        "uq_personal_space_owner",
        "spaces",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'personal'"),
        sqlite_where=sa.text("kind = 'personal'"),
    )
    op.create_table(
        "classrooms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id"),
    )
    op.create_index("ix_classrooms_owner_id", "classrooms", ["owner_id"])
    op.create_table(
        "classroom_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=7), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["classroom_id"], ["classrooms.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("classroom_id", "user_id", name="uq_classroom_membership"),
    )
    op.create_index("ix_classroom_memberships_classroom_id", "classroom_memberships", ["classroom_id"])
    op.create_index("ix_classroom_memberships_user_id", "classroom_memberships", ["user_id"])
    op.create_table(
        "classroom_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=7), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["classroom_id"], ["classrooms.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_digest"),
    )
    op.create_index("ix_classroom_invites_classroom_id", "classroom_invites", ["classroom_id"])
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_classroom_invites_classroom_id", table_name="classroom_invites")
    op.drop_table("classroom_invites")
    op.drop_index("ix_classroom_memberships_user_id", table_name="classroom_memberships")
    op.drop_index("ix_classroom_memberships_classroom_id", table_name="classroom_memberships")
    op.drop_table("classroom_memberships")
    op.drop_index("ix_classrooms_owner_id", table_name="classrooms")
    op.drop_table("classrooms")
    op.drop_index("uq_personal_space_owner", table_name="spaces")
    op.drop_index("ix_spaces_kind", table_name="spaces")
    op.drop_index("ix_spaces_owner_id", table_name="spaces")
    op.drop_table("spaces")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
