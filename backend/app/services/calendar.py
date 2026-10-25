"""Payment calendar and budget (DOMAIN §8). Decimal over the whole range."""

import calendar as cal
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import ZERO
from app.models.payment import CURRENCIES, PaymentOccurrence
from app.schemas.occurrence import state_of
from app.services.projection import project
from app.services.summary import CurrencyTotals


@dataclass
class CalendarEntry:
    occurrence_id: int | None
    recurring_payment_id: int
    title: str
    amount: Decimal
    currency: str
    due_date: date
    state: str | None  # None for a projected period
    is_projected: bool


def totals_of(entries: list[CalendarEntry]) -> list[CurrencyTotals]:
    """Per currency; projected periods count as total and unpaid."""
    by = {cur: CurrencyTotals(cur) for cur in CURRENCIES}
    for e in entries:
        t = by[e.currency]
        t.total += e.amount
        t.count += 1
        if e.state in ("paid", "paid_late"):
            t.paid += e.amount
        else:
            t.unpaid += e.amount
            if e.state == "overdue":
                t.overdue += e.amount
    return list(by.values())


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, cal.monthrange(year, month)[1])


async def calendar_entries(
    db: AsyncSession, team_id: int, date_from: date, date_to: date, today: date
) -> list[CalendarEntry]:
    rows = await db.scalars(
        select(PaymentOccurrence).where(
            PaymentOccurrence.team_id == team_id,
            PaymentOccurrence.due_date >= date_from,
            PaymentOccurrence.due_date <= date_to,
        )
    )
    entries = [
        CalendarEntry(
            occurrence_id=o.id,
            recurring_payment_id=o.recurring_payment_id,
            title=o.title,
            amount=o.amount,
            currency=o.currency,
            due_date=o.due_date,
            state=state_of(o, today),
            is_projected=False,
        )
        for o in rows
    ]
    entries += [
        CalendarEntry(
            occurrence_id=None,
            recurring_payment_id=p.recurring.id,
            title=p.recurring.title,
            amount=p.recurring.amount,
            currency=p.recurring.currency,
            due_date=p.due_date,
            state=None,
            is_projected=True,
        )
        for p in await project(db, team_id, date_from, date_to)
    ]
    order = {cur: i for i, cur in enumerate(CURRENCIES)}
    entries.sort(key=lambda e: (e.due_date, order[e.currency], e.title, e.occurrence_id or 0))
    return entries


@dataclass
class BudgetTotals:
    currency: str
    existing_paid: Decimal = ZERO
    existing_unpaid: Decimal = ZERO
    projected: Decimal = ZERO

    @property
    def planned(self) -> Decimal:
        return self.existing_paid + self.existing_unpaid + self.projected


async def budget(
    db: AsyncSession, team_id: int, date_from: date, date_to: date
) -> list[BudgetTotals]:
    occ = PaymentOccurrence
    by = {cur: BudgetTotals(cur) for cur in CURRENCIES}
    rows = await db.execute(
        select(
            occ.currency,
            func.coalesce(func.sum(case((occ.status == "paid", occ.amount), else_=0)), 0),
            func.coalesce(func.sum(case((occ.status == "unpaid", occ.amount), else_=0)), 0),
        )
        .where(occ.team_id == team_id, occ.due_date >= date_from, occ.due_date <= date_to)
        .group_by(occ.currency)
    )
    for currency, paid, unpaid in rows.all():
        by[currency].existing_paid = Decimal(paid)
        by[currency].existing_unpaid = Decimal(unpaid)
    for p in await project(db, team_id, date_from, date_to):
        by[p.recurring.currency].projected += p.recurring.amount
    return list(by.values())
