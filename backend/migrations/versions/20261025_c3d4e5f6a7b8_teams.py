"""teams: every team has its own users, payments and channels

Existing data goes to the first team named DEFAULT_TEAM_NAME (default "aeza").

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-10-25 18:00:00
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEAM_TABLES = ("users", "recurring_payments", "payment_occurrences", "notifications")


def _default_name() -> str:
    return " ".join(os.environ.get("DEFAULT_TEAM_NAME", "aeza").split()) or "aeza"


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
        sa.UniqueConstraint("slug", name=op.f("uq_teams_slug")),
    )
    name = _default_name()
    op.get_bind().execute(
        sa.text("INSERT INTO teams (id, name, slug, created_at) VALUES (1, :n, :s, now())"),
        {"n": name, "s": name.lower()},
    )
    op.execute("SELECT setval(pg_get_serial_sequence('teams', 'id'), 1)")

    for table in TEAM_TABLES:
        op.add_column(table, sa.Column("team_id", sa.Integer(), nullable=True))
        op.execute(f"UPDATE {table} SET team_id = 1")
        op.alter_column(table, "team_id", nullable=False)
        op.create_foreign_key(op.f(f"fk_{table}_team_id_teams"), table, "teams", ["team_id"], ["id"])
    op.create_index(op.f("ix_users_team_id"), "users", ["team_id"])
    op.create_index(op.f("ix_recurring_payments_team_id"), "recurring_payments", ["team_id"])
    op.create_index(op.f("ix_notifications_team_id"), "notifications", ["team_id"])
    op.create_index(
        "ix_payment_occurrences_team_due", "payment_occurrences", ["team_id", "due_date"]
    )

    op.add_column("audit_events", sa.Column("team_id", sa.Integer(), nullable=True))
    op.execute("UPDATE audit_events SET team_id = 1")
    op.create_foreign_key(
        op.f("fk_audit_events_team_id_teams"), "audit_events", "teams", ["team_id"], ["id"]
    )
    op.create_index(op.f("ix_audit_events_team_id"), "audit_events", ["team_id"])

    # uniqueness within a team
    op.drop_index("uq_users_login_active", table_name="users")
    op.drop_index("uq_users_telegram_active", table_name="users")
    op.drop_index("uq_users_single_protected", table_name="users")
    op.create_index(
        "uq_users_login_active",
        "users",
        ["team_id", sa.text("lower(login)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_users_telegram_active",
        "users",
        ["team_id", "telegram_user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND telegram_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_users_single_protected",
        "users",
        ["team_id"],
        unique=True,
        postgresql_where=sa.text("is_protected"),
    )

    # login attempts: rate limit per (team, login)
    op.add_column(
        "login_attempts",
        sa.Column("team", sa.String(length=64), server_default="", nullable=False),
    )
    op.drop_index("ix_login_attempts_login_at", table_name="login_attempts")
    op.create_index(
        "ix_login_attempts_login_at", "login_attempts", ["team", "login", "attempted_at"]
    )

    # notification settings: one row per team
    op.add_column("app_settings", sa.Column("team_id", sa.Integer(), nullable=True))
    op.execute("UPDATE app_settings SET team_id = 1")
    op.drop_constraint(op.f("ck_app_settings_single_row"), "app_settings", type_="check")
    op.drop_constraint(op.f("pk_app_settings"), "app_settings", type_="primary")
    op.drop_column("app_settings", "id")
    op.alter_column("app_settings", "team_id", nullable=False)
    op.create_primary_key(op.f("pk_app_settings"), "app_settings", ["team_id"])
    op.create_foreign_key(
        op.f("fk_app_settings_team_id_teams"),
        "app_settings",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Only the first team survives a downgrade: the others' rows cannot fit one-team tables.
    op.execute("DELETE FROM app_settings WHERE team_id <> 1")
    op.drop_constraint(op.f("fk_app_settings_team_id_teams"), "app_settings", type_="foreignkey")
    op.drop_constraint(op.f("pk_app_settings"), "app_settings", type_="primary")
    op.add_column("app_settings", sa.Column("id", sa.SmallInteger(), nullable=True))
    op.execute("UPDATE app_settings SET id = 1")
    op.alter_column("app_settings", "id", nullable=False)
    op.drop_column("app_settings", "team_id")
    op.create_primary_key(op.f("pk_app_settings"), "app_settings", ["id"])
    op.create_check_constraint(op.f("ck_app_settings_single_row"), "app_settings", "id = 1")

    op.drop_index("ix_login_attempts_login_at", table_name="login_attempts")
    op.drop_column("login_attempts", "team")
    op.create_index("ix_login_attempts_login_at", "login_attempts", ["login", "attempted_at"])

    for table in ("audit_events", "notifications", "payment_occurrences", "recurring_payments"):
        op.execute(f"DELETE FROM {table} WHERE team_id IS DISTINCT FROM 1")
    op.execute(
        "DELETE FROM recurring_payment_assignees WHERE user_id IN "
        "(SELECT id FROM users WHERE team_id <> 1)"
    )
    op.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE team_id <> 1)")
    op.execute("DELETE FROM users WHERE team_id <> 1")

    op.drop_index("uq_users_login_active", table_name="users")
    op.drop_index("uq_users_telegram_active", table_name="users")
    op.drop_index("uq_users_single_protected", table_name="users")
    op.create_index(
        "uq_users_login_active",
        "users",
        [sa.text("lower(login)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_users_telegram_active",
        "users",
        ["telegram_user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND telegram_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_users_single_protected",
        "users",
        ["is_protected"],
        unique=True,
        postgresql_where=sa.text("is_protected"),
    )

    op.drop_index(op.f("ix_audit_events_team_id"), table_name="audit_events")
    op.drop_constraint(op.f("fk_audit_events_team_id_teams"), "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "team_id")
    op.drop_index("ix_payment_occurrences_team_due", table_name="payment_occurrences")
    op.drop_index(op.f("ix_notifications_team_id"), table_name="notifications")
    op.drop_index(op.f("ix_recurring_payments_team_id"), table_name="recurring_payments")
    op.drop_index(op.f("ix_users_team_id"), table_name="users")
    for table in TEAM_TABLES:
        op.drop_constraint(op.f(f"fk_{table}_team_id_teams"), table, type_="foreignkey")
        op.drop_column(table, "team_id")
    op.drop_table("teams")
