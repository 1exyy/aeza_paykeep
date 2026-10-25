"""Per-user lead time and delivery state for private Telegram reminders.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: str | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("telegram_dm_days_before", sa.Integer(), server_default="3", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_users_telegram_dm_days_before"),
        "users",
        "telegram_dm_days_before BETWEEN 0 AND 30",
    )
    op.create_table(
        "personal_reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "occurrence_id",
            sa.Integer(),
            sa.ForeignKey("payment_occurrences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sending_started_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'unknown')",
            name=op.f("ck_personal_reminders_status"),
        ),
        sa.UniqueConstraint(
            "user_id", "occurrence_id", name=op.f("uq_personal_reminders_user_occurrence")
        ),
    )
    op.create_index(
        op.f("ix_personal_reminders_pending"),
        "personal_reminders",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    # Periods already reminded by the old combined channel must not get a second DM.
    op.execute(
        """
        INSERT INTO personal_reminders
            (user_id, occurrence_id, status, attempts, next_attempt_at, sent_at, created_at, updated_at)
        SELECT u.id, o.id, 'sent', 0, o.reminder_sent_at, o.reminder_sent_at,
               o.reminder_sent_at, o.reminder_sent_at
        FROM users AS u
        JOIN payment_occurrences AS o ON o.team_id = u.team_id
        WHERE o.reminder_sent_at IS NOT NULL AND u.deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_personal_reminders_pending"), table_name="personal_reminders")
    op.drop_table("personal_reminders")
    op.drop_constraint(op.f("ck_users_telegram_dm_days_before"), "users", type_="check")
    op.drop_column("users", "telegram_dm_days_before")
