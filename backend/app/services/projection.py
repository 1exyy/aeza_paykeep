"""Projected (not yet created) periods of active payments, for the calendar and the budget.

Only due dates after the last existing period of an ACTIVE payment are projected: stopped
payments contribute their existing periods only (DOMAIN §8).
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import PaymentOccurrence, RecurringPayment
from app.services.schedule import schedule_of


@dataclass
class Projected:
    recurring: RecurringPayment
    period_index: int
    due_date: date


async def project(
    db: AsyncSession, team_id: int, date_from: date, date_to: date
) -> list[Projected]:
    rows = await db.execute(
        select(RecurringPayment, func.max(PaymentOccurrence.period_index))
        .outerjoin(PaymentOccurrence, PaymentOccurrence.recurring_payment_id == RecurringPayment.id)
        .where(RecurringPayment.team_id == team_id, RecurringPayment.status == "active")
        .group_by(RecurringPayment.id)
        .order_by(RecurringPayment.id)
    )
    result = []
    for recurring, last_index in rows.all():
        schedule = schedule_of(recurring)
        base = recurring.index_base
        n = 0 if last_index is None or last_index < base else last_index + 1 - base
        while schedule.has(n) and (due := schedule.due(n)) <= date_to:
            if due >= date_from:
                result.append(Projected(recurring, base + n, due))
            n += 1
    return result
