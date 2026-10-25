import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

NOTIFICATION_TYPES = (
    "payment.due_soon",
    "occurrence.paid",
    "occurrence.unpaid",
    "recurring.created",
    "recurring.stopped",
)
CHANNELS = ("telegram", "email", "webhook", "extra")
DELIVERY_STATUSES = ("pending", "sending", "sent", "failed", "unknown")


class Notification(Base):
    """Logical notification: an event about a period/payment (DOMAIN §6).

    One `payment.due_soon` per period for its whole life (partial unique index).
    """

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "type IN ('payment.due_soon', 'occurrence.paid', 'occurrence.unpaid', "
            "'recurring.created', 'recurring.stopped')",
            name="type",
        ),
        Index(
            "uq_notifications_due_soon",
            "occurrence_id",
            "type",
            unique=True,
            postgresql_where=text("type = 'payment.due_soon'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    occurrence_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_occurrences.id", ondelete="SET NULL"), nullable=True
    )
    recurring_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_payments.id"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Delivery(Base):
    """Delivery attempt of a notification to one channel.

    pending → sending → sent | failed | unknown. `unknown` (timeout, no answer) is never retried:
    a duplicate is worse than a miss.
    """

    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("notification_id", "channel", name="uq_deliveries_notification_channel"),
        CheckConstraint("channel IN ('telegram', 'email', 'webhook', 'extra')", name="channel"),
        CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'unknown')", name="status"
        ),
        Index(
            "ix_deliveries_pending", "next_attempt_at", postgresql_where=text("status = 'pending'")
        ),
        Index("ix_deliveries_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notification_id: Mapped[int] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sending_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
