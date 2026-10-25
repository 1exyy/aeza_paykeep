"""Totals by currency over the WHOLE selection, computed in SQL (DOMAIN §8). No conversion."""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.money import ZERO
from app.models.payment import CURRENCIES, PaymentOccurrence

MAX_RANGE_DAYS = 731


@dataclass
class CurrencyTotals:
    currency: str
    total: Decimal = ZERO
    paid: Decimal = ZERO
    unpaid: Decimal = ZERO
    overdue: Decimal = ZERO
    count: int = 0


def month_bounds(day: date) -> tuple[date, date]:
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


def resolve_range(date_from: date | None, date_to: date | None, today: date) -> tuple[date, date]:
    start, end = month_bounds(today)
    date_from = date_from or start
    date_to = date_to or end
    if date_from > date_to:
        raise AppError.validation("to", "Конец периода раньше начала")
    if (date_to - date_from).days > MAX_RANGE_DAYS:
        raise AppError.validation("to", f"Период не может быть длиннее {MAX_RANGE_DAYS} дней")
    return date_from, date_to


async def totals_by_currency(
    db: AsyncSession, team_id: int, date_from: date, date_to: date, today: date
) -> list[CurrencyTotals]:
    occ = PaymentOccurrence
    paid = occ.status == "paid"
    unpaid = occ.status == "unpaid"
    overdue = and_(unpaid, occ.due_date < today)

    def amount_if(cond):  # type: ignore[no-untyped-def]
        return func.coalesce(func.sum(case((cond, occ.amount), else_=0)), 0)

    rows = await db.execute(
        select(
            occ.currency,
            func.coalesce(func.sum(occ.amount), 0),
            amount_if(paid),
            amount_if(unpaid),
            amount_if(overdue),
            func.count(),
        )
        .where(occ.team_id == team_id, occ.due_date >= date_from, occ.due_date <= date_to)
        .group_by(occ.currency)
    )
    found = {
        cur: CurrencyTotals(cur, Decimal(t), Decimal(p), Decimal(u), Decimal(o), n)
        for cur, t, p, u, o, n in rows.all()
    }
    return [found.get(cur, CurrencyTotals(cur)) for cur in CURRENCIES]
