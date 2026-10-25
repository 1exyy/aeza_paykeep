"""supervisor role, temporary passwords, team applications

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-10-25 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), server_default="false", nullable=False),
    )
    op.alter_column("users", "team_id", nullable=True)
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_role"), "users", "role IN ('admin', 'user', 'supervisor')"
    )
    op.create_check_constraint(
        op.f("ck_users_supervisor_no_team"), "users", "(role = 'supervisor') = (team_id IS NULL)"
    )
    op.create_index(
        "uq_users_single_supervisor",
        "users",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'supervisor'"),
    )

    op.create_table(
        "team_applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("team_name", sa.String(length=64), nullable=False),
        sa.Column("team_slug", sa.String(length=64), nullable=False),
        sa.Column("admin_login", sa.String(length=64), nullable=False),
        sa.Column("applicant_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("applicant_username", sa.String(length=64), nullable=True),
        sa.Column("applicant_name", sa.String(length=128), nullable=True),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=False),
        sa.Column("smtp", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_login", sa.String(length=64), nullable=True),
        sa.Column("reject_reason", sa.String(length=500), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_team_applications_status"),
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_team_applications_team_id_teams")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_applications")),
    )
    op.create_index(
        "ix_team_applications_status_created", "team_applications", ["status", "created_at"]
    )
    op.create_index(
        "uq_team_applications_pending_applicant",
        "team_applications",
        ["applicant_telegram_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_team_applications_pending_applicant", table_name="team_applications")
    op.drop_index("ix_team_applications_status_created", table_name="team_applications")
    op.drop_table("team_applications")
    op.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE team_id IS NULL)")
    op.execute("DELETE FROM users WHERE team_id IS NULL")
    op.drop_index("uq_users_single_supervisor", table_name="users")
    op.drop_constraint(op.f("ck_users_supervisor_no_team"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(op.f("ck_users_role"), "users", "role IN ('admin', 'user')")
    op.alter_column("users", "team_id", nullable=False)
    op.drop_column("users", "must_change_password")
