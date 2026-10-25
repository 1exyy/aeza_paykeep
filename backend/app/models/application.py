from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

APPLICATION_STATUSES = ("pending", "approved", "rejected")


class TeamApplication(Base):
    """A request to create a team, sent through the application bot.

    The supervisor approves it (a team, its administrator and channels are created) or rejects
    it with a reason. `smtp` keeps the optional mail settings in Settings field names.
    """

    __tablename__ = "team_applications"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status"),
        Index("ix_team_applications_status_created", "status", "created_at"),
        # one open application per Telegram account
        Index(
            "uq_team_applications_pending_applicant",
            "applicant_telegram_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    team_name: Mapped[str] = mapped_column(String(64), nullable=False)
    team_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    admin_login: Mapped[str] = mapped_column(String(64), nullable=False)
    applicant_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applicant_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applicant_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    telegram_chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    smtp: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_login: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
