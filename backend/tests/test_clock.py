from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.clock import Clock, get_clock, set_offset_days, to_local
from tests.helpers import freeze


def test_business_day_boundary_utc_plus_3() -> None:
    freeze("2026-11-06T20:59:59+00:00")
    assert Clock().today() == date(2026, 11, 6)
    freeze("2026-11-06T21:00:00+00:00")
    assert Clock().today() == date(2026, 11, 7)
    assert Clock().now().isoformat() == "2026-11-07T00:00:00+03:00"


def test_offset_shifts_business_time_but_not_real_time() -> None:
    freeze("2026-10-24T10:00:00+03:00")
    shifted = Clock(offset_days=31)
    assert shifted.today() == date(2026, 11, 24)
    assert shifted.real_today() == date(2026, 10, 24)
    assert clock.real_now().isoformat() == "2026-10-24T07:00:00+00:00"


def test_to_local_formats_with_offset() -> None:
    freeze("2026-10-24T06:00:00.123456+00:00")
    assert to_local(clock.real_now()).isoformat() == "2026-10-24T09:00:00+03:00"


async def test_dev_offset_persisted_in_db(db: AsyncSession) -> None:
    freeze("2026-10-24T10:00:00+03:00")
    assert (await get_clock(db)).today() == date(2026, 10, 24)
    await set_offset_days(db, 5)
    await db.commit()
    clock.invalidate_cache()
    assert (await get_clock(db)).today() == date(2026, 10, 29)
    await set_offset_days(db, -1)
    await db.commit()
    assert (await get_clock(db)).today() == date(2026, 10, 23)
