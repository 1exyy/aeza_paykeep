"""Demo helpers, only with DEV_MODE=true (else 404): dev clock and an immediate worker cycle."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, require_admin
from app.core import clock as clock_module
from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import not_found
from app.models.user import User
from app.schemas.notification import DevClockIn, DevClockOut
from app.worker.jobs import dispatch_deliveries, run_cycle


async def dev_only() -> None:
    if not get_settings().dev_mode:
        raise not_found("Ресурс не найден")


router = APIRouter(prefix="/dev", tags=["dev"], dependencies=[Depends(dev_only)])


async def _out(db: AsyncSession) -> DevClockOut:
    clock = await get_clock(db)
    return DevClockOut(
        today=clock.today(), real_today=clock.real_today(), offset_days=clock.offset_days
    )


@router.get("/clock", response_model=DevClockOut)
async def get_dev_clock(
    _: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> DevClockOut:
    return await _out(db)


@router.put("/clock", response_model=DevClockOut)
async def set_dev_clock(
    body: DevClockIn,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> DevClockOut:
    await clock_module.set_offset_days(db, body.offset_days)
    await db.commit()
    return await _out(db)


@router.post("/run-jobs", status_code=202)
async def run_jobs(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)
) -> Response:
    """Generator → reminders → delivery, right now (a full worker cycle)."""
    await run_cycle(db)
    await dispatch_deliveries(db)
    return Response(status_code=202)
