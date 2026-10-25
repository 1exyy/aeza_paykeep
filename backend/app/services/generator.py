"""Idempotent creation of periods (DOMAIN §5).

An active payment always has every period with due date ≤ today plus two future ones
(a one-time payment has a single period).
Uniqueness (recurring_payment_id, period_index) + ON CONFLICT DO NOTHING: reruns and parallel
runs never duplicate; after downtime the next run creates every missing period.
"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.services.schedule import schedule_of

FUTURE_PERIODS = 2


async def ensure_occurrences(
    db: AsyncSession, recurring: RecurringPayment, today: date, now: datetime
) -> list[int]:
    """Create missing periods of one payment; returns ids of the new rows."""
    if recurring.status != "active":
        return []
    schedule = schedule_of(recurring)
    rows = [
        {
            "recurring_payment_id": recurring.id,
            "team_id": recurring.team_id,
            # periods of an edited schedule continue after the old ones
            "period_index": recurring.index_base + n,
            "title": recurring.title,
            "amount": recurring.amount,
            "currency": recurring.currency,
            "due_date": schedule.due(n),
            "status": "unpaid",
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        for n in schedule.horizon(today, FUTURE_PERIODS)
    ]
    if not rows:
        return []
    stmt = (
        insert(PaymentOccurrence)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_occurrence_period")
        .returning(PaymentOccurrence.id)
    )
    return list((await db.scalars(stmt)).all())


async def ensure_all(db: AsyncSession, clock: Clock) -> int:
    """Run the generator for every active payment (worker cycle). Caller commits."""
    today, now = clock.today(), clock.now()
    created = 0
    for recurring in await db.scalars(
        select(RecurringPayment).where(RecurringPayment.status == "active")
    ):
        created += len(await ensure_occurrences(db, recurring, today, now))
    return created
