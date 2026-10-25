"""GET /payments/summary and GET /config — both roles."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import clock_dep, current_user
from app.core.clock import Clock
from app.core.config import get_settings
from app.core.db import get_session
from app.models.payment import CURRENCIES
from app.models.team import Team
from app.models.user import User
from app.schemas.summary import (
    AppConfigOut,
    ChannelsOut,
    CurrencyTotalsOut,
    SummaryOut,
    TeamRef,
)
from app.services.schedule import PERIODICITIES
from app.services.summary import resolve_range, totals_by_currency

router = APIRouter(tags=["payments"])


@router.get("/payments/summary", response_model=SummaryOut)
async def summary(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> SummaryOut:
    today = clock.today()
    start, end = resolve_range(date_from, date_to, today)
    totals = await totals_by_currency(db, user.team_id, start, end, today)
    return SummaryOut(
        from_=start, to=end, today=today, currencies=[CurrencyTotalsOut.of(t) for t in totals]
    )


@router.get("/config", response_model=AppConfigOut, tags=["config"])
async def app_config(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> AppConfigOut:
    s = get_settings()
    team = await db.get(Team, user.team_id)
    return AppConfigOut(
        team=TeamRef(id=user.team_id, name=team.name if team else ""),
        timezone_offset=s.app_tz_offset,
        timezone_label=s.tz_label,
        today=clock.today(),
        reminder_days_before=s.reminder_days_before,
        currencies=list(CURRENCIES),
        periodicities=list(PERIODICITIES),
        telegram_bot_username=s.telegram_bot_username or None,
        miniapp_url=s.miniapp_url or None,
        channels=ChannelsOut(
            telegram=s.telegram_enabled,
            email=s.email_enabled,
            webhook=s.webhook_enabled,
            extra=s.extra_enabled,
        ),
        dev_mode=s.dev_mode,
    )
