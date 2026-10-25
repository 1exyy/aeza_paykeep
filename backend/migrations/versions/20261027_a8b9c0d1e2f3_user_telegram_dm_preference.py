"""Allow each user to opt out of private Telegram reminders.

Revision ID: a8b9c0d1e2f3
Revises: f9a0b1c2d3e4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("telegram_dm_enabled", sa.Boolean(), server_default="true", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("users", "telegram_dm_enabled")
