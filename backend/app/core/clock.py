"""The ONLY source of time in the application.

Business day = calendar date in the system time zone (APP_TZ_OFFSET, default UTC+03:00).
In DEV_MODE "today" can be shifted by N days (stored in system_state, shared by API and worker).

Two kinds of time:
- business time (`Clock.now()`, `Clock.today()`) — shifted by the dev offset; used for due dates,
  overdue flags, reminders and record timestamps;
- real time (`real_now()`) — never shifted; used for security: session expiry, login rate limit,
  initData freshness. Otherwise moving the dev clock by a month would log everybody out.
"""

import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings


def _system_now() -> datetime:
    return datetime.now(UTC)


_now_fn: Callable[[], datetime] = _system_now


def set_real_now(fn: Callable[[], datetime]) -> None:
    """Tests: freeze or move the real clock. `fn` must return an aware datetime."""
    global _now_fn
    _now_fn = fn
    invalidate_cache()


def reset_real_now() -> None:
    set_real_now(_system_now)


def real_now() -> datetime:
    """Real current moment in UTC (not affected by the dev offset)."""
    return _now_fn().astimezone(UTC)


def system_tz() -> timezone:
    return get_settings().tz


def to_local(moment: datetime) -> datetime:
    """Moment in the system time zone without microseconds (for API responses)."""
    return moment.astimezone(system_tz()).replace(microsecond=0)


class Clock:
    def __init__(self, offset_days: int = 0) -> None:
        self.offset_days = offset_days

    def now(self) -> datetime:
        """Business moment (aware, system time zone), shifted by the dev offset."""
        return (real_now() + timedelta(days=self.offset_days)).astimezone(system_tz())

    def today(self) -> date:
        return self.now().date()

    def real_today(self) -> date:
        return real_now().astimezone(system_tz()).date()


_CACHE_TTL = 1.0
_cache: tuple[float, int] | None = None


def invalidate_cache() -> None:
    global _cache
    _cache = None


async def get_clock(session: AsyncSession) -> Clock:
    """Clock with the dev offset from the DB (cached for ≤ 1 s). Offset is 0 unless DEV_MODE."""
    global _cache
    if not get_settings().dev_mode:
        return Clock(0)
    if _cache is not None and time.monotonic() - _cache[0] < _CACHE_TTL:
        return Clock(_cache[1])
    from app.models.system_state import SystemState

    offset = await session.scalar(select(SystemState.clock_offset_days).where(SystemState.id == 1))
    _cache = (time.monotonic(), offset or 0)
    return Clock(offset or 0)


async def set_offset_days(session: AsyncSession, offset_days: int) -> Clock:
    """Persist the dev offset (caller commits)."""
    from app.models.system_state import SystemState

    stmt = insert(SystemState).values(id=1, clock_offset_days=offset_days, updated_at=real_now())
    stmt = stmt.on_conflict_do_update(
        index_elements=[SystemState.id],
        set_={"clock_offset_days": offset_days, "updated_at": real_now()},
    )
    await session.execute(stmt)
    invalidate_cache()
    return Clock(offset_days)
