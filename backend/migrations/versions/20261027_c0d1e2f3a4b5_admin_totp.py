"""Administrator TOTP enrollment and one-time code tracking.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("totp_pending_secret", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("totp_pending_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("totp_last_counter", sa.BigInteger()))
    op.add_column(
        "users", sa.Column("totp_failures", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("users", sa.Column("totp_failed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for name in (
        "totp_failed_at",
        "totp_failures",
        "totp_last_counter",
        "totp_pending_at",
        "totp_pending_secret",
        "totp_secret",
    ):
        op.drop_column("users", name)
