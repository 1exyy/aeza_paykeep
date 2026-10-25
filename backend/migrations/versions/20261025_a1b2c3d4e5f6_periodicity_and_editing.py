"""periodicity, schedule edits, one-time completion

Revision ID: a1b2c3d4e5f6
Revises: 811d7dbab297
Create Date: 2026-10-25 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "811d7dbab297"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recurring_payments", sa.Column("interval_days", sa.Integer(), nullable=True))
    op.add_column(
        "recurring_payments",
        sa.Column("index_base", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "recurring_payments",
        sa.Column("completed", sa.Boolean(), server_default="false", nullable=False),
    )
    op.drop_constraint(op.f("ck_recurring_payments_periodicity"), "recurring_payments", type_="check")
    op.create_check_constraint(
        op.f("ck_recurring_payments_periodicity"),
        "recurring_payments",
        "periodicity IN ('once', 'daily', 'weekly', 'monthly', 'every_n_days')",
    )
    op.create_check_constraint(
        op.f("ck_recurring_payments_interval_days"),
        "recurring_payments",
        "(periodicity = 'every_n_days') = (interval_days IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_recurring_payments_interval_days"), "recurring_payments", type_="check")
    op.drop_constraint(op.f("ck_recurring_payments_periodicity"), "recurring_payments", type_="check")
    op.create_check_constraint(
        op.f("ck_recurring_payments_periodicity"), "recurring_payments", "periodicity IN ('monthly')"
    )
    op.drop_column("recurring_payments", "completed")
    op.drop_column("recurring_payments", "index_base")
    op.drop_column("recurring_payments", "interval_days")
