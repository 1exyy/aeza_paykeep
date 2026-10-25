from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CURRENCIES = ("RUB", "USD", "EUR")


class RecurringPayment(Base):
    """A recurring expense. Its periods live in payment_occurrences (DOMAIN §3)."""

    __tablename__ = "recurring_payments"
    __table_args__ = (
        CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="currency"),
        CheckConstraint(
            "periodicity IN ('once', 'daily', 'weekly', 'monthly', 'every_n_days')",
            name="periodicity",
        ),
        CheckConstraint(
            "(periodicity = 'every_n_days') = (interval_days IS NOT NULL)", name="interval_days"
        ),
        CheckConstraint("status IN ('active', 'stopped')", name="status"),
        CheckConstraint("anchor_day BETWEEN 1 AND 31", name="anchor_day"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    periodicity: Mapped[str] = mapped_column(String(16), nullable=False)
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    first_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # period_index of the first period of the current schedule (grows when the schedule is edited)
    index_base: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_login: Mapped[str] = mapped_column(String(64), nullable=False)
    assign_all: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecurringPaymentAssignee(Base):
    """Explicitly chosen responsible users of a payment."""

    __tablename__ = "recurring_payment_assignees"
    __table_args__ = (PrimaryKeyConstraint("recurring_payment_id", "user_id"),)

    recurring_payment_id: Mapped[int] = mapped_column(
        ForeignKey("recurring_payments.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


class PaymentOccurrence(Base):
    """Payment for one period: its own due date and its own paid mark (DOMAIN §4)."""

    __tablename__ = "payment_occurrences"
    __table_args__ = (
        UniqueConstraint("recurring_payment_id", "period_index", name="uq_occurrence_period"),
        CheckConstraint("status IN ('paid', 'unpaid')", name="status"),
        CheckConstraint("(status = 'paid') = (paid_date IS NOT NULL)", name="paid_date_iff_paid"),
        CheckConstraint("paid_via IS NULL OR paid_via IN ('web', 'telegram')", name="paid_via"),
        CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="currency"),
        Index("ix_payment_occurrences_due_date", "due_date"),
        Index("ix_payment_occurrences_team_due", "team_id", "due_date"),
        Index("ix_payment_occurrences_status_due", "status", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recurring_payment_id: Mapped[int] = mapped_column(
        ForeignKey("recurring_payments.id"), nullable=False
    )
    # copy of the payment's team: every query filters by it with one condition
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    period_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unpaid")
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    paid_by_login: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paid_via: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
