"""GET/POST /recurring-payments, GET/PATCH/DELETE /recurring-payments/{id}."""

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, clock_dep, current_user, require_admin
from app.api.pagination import Page, page_params
from app.core.clock import Clock
from app.core.db import get_session
from app.core.errors import not_found
from app.models.payment import RecurringPayment
from app.models.user import User
from app.schemas.recurring import (
    RecurringPaymentCreate,
    RecurringPaymentOut,
    RecurringPaymentPage,
    RecurringPaymentPatch,
)
from app.services import assignees, attachments
from app.services import recurring as service

router = APIRouter(prefix="/recurring-payments", tags=["recurring-payments"])


async def _out(db: AsyncSession, clock: Clock, rp: RecurringPayment) -> RecurringPaymentOut:
    nexts = await service.next_due_dates(db, [rp.id], clock.today())
    return RecurringPaymentOut.of(rp, nexts.get(rp.id), await assignees.assignment(db, rp.id))


@router.get("", response_model=RecurringPaymentPage)
async def list_recurring(
    status: Literal["active", "stopped", "all"] = Query("all"),
    page: Page = Depends(page_params),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> RecurringPaymentPage:
    where = [RecurringPayment.team_id == user.team_id]
    if status != "all":
        where.append(RecurringPayment.status == status)
    total = await db.scalar(select(func.count()).select_from(RecurringPayment).where(*where)) or 0
    items = list(
        await db.scalars(
            select(RecurringPayment)
            .where(*where)
            .order_by(RecurringPayment.id.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
    )
    ids = [rp.id for rp in items]
    nexts = await service.next_due_dates(db, ids, clock.today())
    assigned = await assignees.assignments(db, ids)
    return RecurringPaymentPage(
        items=[RecurringPaymentOut.of(rp, nexts.get(rp.id), assigned[rp.id]) for rp in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=RecurringPaymentOut, status_code=201)
async def create_recurring(
    body: RecurringPaymentCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> RecurringPaymentOut:
    rp = await service.create_recurring(db, clock, admin, body, client_ip(request))
    await db.commit()
    return await _out(db, clock, rp)


@router.get("/{id}", response_model=RecurringPaymentOut)
async def get_recurring(
    id: int = Path(ge=1),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> RecurringPaymentOut:
    rp = await db.get(RecurringPayment, id)
    if rp is None or rp.team_id != user.team_id:
        raise not_found("Регулярный платёж не найден")
    return await _out(db, clock, rp)


@router.patch("/{id}", response_model=RecurringPaymentOut)
async def update_recurring(
    body: RecurringPaymentPatch,
    request: Request,
    id: int = Path(ge=1),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> RecurringPaymentOut:
    rp, orphaned_files = await service.update_recurring(
        db, clock, admin, id, body, client_ip(request)
    )
    await db.commit()
    for storage_name in orphaned_files:
        await attachments.discard_file(storage_name)
    return await _out(db, clock, rp)


@router.delete("/{id}", response_model=RecurringPaymentOut)
async def stop_recurring(
    request: Request,
    id: int = Path(ge=1),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> RecurringPaymentOut:
    rp, orphaned_files = await service.stop_recurring(db, clock, admin, id, client_ip(request))
    await db.commit()
    for storage_name in orphaned_files:
        await attachments.discard_file(storage_name)
    return await _out(db, clock, rp)
