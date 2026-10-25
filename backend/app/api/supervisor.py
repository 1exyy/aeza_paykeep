"""Supervisor: team applications — list, approve, reject. Nothing else."""

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, clock_dep, require_supervisor
from app.api.pagination import Page, page_params
from app.core.clock import Clock
from app.core.db import get_session
from app.models.application import TeamApplication
from app.models.user import User
from app.schemas.application import ApplicationOut, ApplicationPage, DecisionOut, RejectRequest
from app.services import applications as service

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


@router.get("/applications", response_model=ApplicationPage)
async def list_applications(
    status: Literal["pending", "approved", "rejected", "all"] = Query("pending"),
    page: Page = Depends(page_params),
    _: User = Depends(require_supervisor),
    db: AsyncSession = Depends(get_session),
) -> ApplicationPage:
    where = [] if status == "all" else [TeamApplication.status == status]
    total = await db.scalar(select(func.count()).select_from(TeamApplication).where(*where)) or 0
    order = (
        TeamApplication.created_at.asc()
        if status == "pending"
        else TeamApplication.created_at.desc()
    )
    rows = await db.scalars(
        select(TeamApplication)
        .where(*where)
        .order_by(order, TeamApplication.id)
        .limit(page.limit)
        .offset(page.offset)
    )
    return ApplicationPage(
        items=[ApplicationOut.of(a) for a in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/applications/{id}/approve", response_model=DecisionOut)
async def approve_application(
    request: Request,
    id: int = Path(ge=1),
    supervisor: User = Depends(require_supervisor),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> DecisionOut:
    application, password = await service.approve(db, clock, supervisor, id, client_ip(request))
    try:
        await db.commit()
    except IntegrityError as exc:  # the same name approved concurrently
        await db.rollback()
        raise service.team_name_taken() from exc
    notified = await service.notify(application, service.approved_text(application, password))
    return DecisionOut(
        application=ApplicationOut.of(application),
        notified=notified,
        temp_password=None if notified else password,
    )


@router.post("/applications/{id}/reject", response_model=DecisionOut)
async def reject_application(
    body: RejectRequest,
    request: Request,
    id: int = Path(ge=1),
    supervisor: User = Depends(require_supervisor),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> DecisionOut:
    application = await service.reject(db, clock, supervisor, id, body.reason, client_ip(request))
    await db.commit()
    notified = await service.notify(application, service.rejected_text(application))
    return DecisionOut(
        application=ApplicationOut.of(application), notified=notified, temp_password=None
    )
