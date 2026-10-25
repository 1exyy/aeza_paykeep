"""GET /calendar?month=YYYY-MM, GET /calendar/export and GET /budget — both roles."""

import re
from datetime import date
from itertools import groupby
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import clock_dep, current_user
from app.core.clock import Clock
from app.core.db import get_session
from app.core.errors import AppError
from app.core.money import format_money
from app.models.team import Team
from app.models.user import User
from app.schemas.summary import CurrencyTotalsOut
from app.services import calendar as service
from app.services import calendar_export
from app.services.summary import month_bounds

router = APIRouter(tags=["calendar-budget"])

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
MIN_YEAR, MAX_YEAR = 2000, 2100


class CalendarItemOut(BaseModel):
    occurrence_id: int | None
    recurring_payment_id: int
    title: str
    amount: str
    currency: str
    due_date: date
    state: Literal["upcoming", "overdue", "paid", "paid_late"] | None
    is_projected: bool


class CalendarDayOut(BaseModel):
    date: date
    items: list[CalendarItemOut]
    totals: list[CurrencyTotalsOut]


class CalendarMonthOut(BaseModel):
    month: str
    today: date
    days: list[CalendarDayOut]
    month_totals: list[CurrencyTotalsOut]


class BudgetTotalsOut(BaseModel):
    currency: str
    planned: str
    existing_paid: str
    existing_unpaid: str
    projected: str


class BudgetOut(BaseModel):
    period: Literal["month", "year"]
    from_: date = Field(serialization_alias="from")
    to: date
    currencies: list[BudgetTotalsOut]


def _item(e: service.CalendarEntry) -> CalendarItemOut:
    return CalendarItemOut(
        occurrence_id=e.occurrence_id,
        recurring_payment_id=e.recurring_payment_id,
        title=e.title,
        amount=format_money(e.amount),
        currency=e.currency,
        due_date=e.due_date,
        state=e.state,  # type: ignore[arg-type]
        is_projected=e.is_projected,
    )


def _year(value: int, field: str = "year") -> int:
    if not MIN_YEAR <= value <= MAX_YEAR:
        raise AppError.validation(field, f"Год от {MIN_YEAR} до {MAX_YEAR}")
    return value


@router.get("/calendar", response_model=CalendarMonthOut)
async def calendar(
    month: str | None = Query(None),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> CalendarMonthOut:
    today = clock.today()
    if month is None:
        year, month_number = today.year, today.month
    else:
        m = _MONTH_RE.match(month)
        if not m:
            raise AppError.validation("month", "Месяц в формате ГГГГ-ММ, например 2026-11")
        year, month_number = _year(int(m.group(1)), "month"), int(m.group(2))
    start, end = service.month_range(year, month_number)
    entries = await service.calendar_entries(db, user.team_id, start, end, today)
    days = []
    for day, group in groupby(entries, key=lambda e: e.due_date):
        day_entries = list(group)
        days.append(
            CalendarDayOut(
                date=day,
                items=[_item(e) for e in day_entries],
                totals=[CurrencyTotalsOut.of(t) for t in service.totals_of(day_entries)],
            )
        )
    return CalendarMonthOut(
        month=f"{year:04d}-{month_number:02d}",
        today=today,
        days=days,
        month_totals=[CurrencyTotalsOut.of(t) for t in service.totals_of(entries)],
    )


EXPORT_MAX_DAYS = 366
_MEDIA = {"csv": "text/csv; charset=utf-8", "ics": "text/calendar; charset=utf-8"}


@router.get("/calendar/export", response_class=Response)
async def export_calendar(
    format: Literal["csv", "ics"] = Query(...),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> Response:
    """The team's calendar as a file; the current month by default."""
    today = clock.today()
    start, end = month_bounds(today)
    start, end = date_from or start, date_to or end
    if start > end:
        raise AppError.validation("to", "Конец периода раньше начала")
    if (end - start).days >= EXPORT_MAX_DAYS:
        raise AppError.validation("to", f"Период выгрузки — не больше {EXPORT_MAX_DAYS} дней")
    entries = await service.calendar_entries(db, user.team_id, start, end, today)
    team = await db.get(Team, user.team_id)
    team_name = team.name if team else ""
    if format == "csv":
        content = calendar_export.to_csv(entries)
    else:
        content = calendar_export.to_ics(entries, user.team_id, team_name, clock.now())
    name = f"calendar-{team_name}-{start:%Y-%m-%d}-{end:%Y-%m-%d}.{format}"
    ascii_name = f"calendar-{start:%Y-%m-%d}-{end:%Y-%m-%d}.{format}"
    return Response(
        content=content,
        media_type=_MEDIA[format],
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
            ),
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/budget", response_model=BudgetOut)
async def budget(
    period: Literal["month", "year"] = Query(...),
    year: int = Query(...),
    month: int | None = Query(None, ge=1, le=12),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> BudgetOut:
    _year(year)
    if period == "month":
        if month is None:
            raise AppError.validation("month", "Укажите месяц (1–12) для period=month")
        start, end = service.month_range(year, month)
    else:
        start, end = date(year, 1, 1), date(year, 12, 31)
    totals = await service.budget(db, user.team_id, start, end)
    return BudgetOut(
        period=period,
        from_=start,
        to=end,
        currencies=[
            BudgetTotalsOut(
                currency=t.currency,
                planned=format_money(t.planned),
                existing_paid=format_money(t.existing_paid),
                existing_unpaid=format_money(t.existing_unpaid),
                projected=format_money(t.projected),
            )
            for t in totals
        ],
    )
