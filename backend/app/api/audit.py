"""GET /audit-log — action log, admin only, newest first (DOMAIN §11)."""

from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.pagination import Page, page_params
from app.core.clock import system_tz, to_local
from app.core.db import get_session
from app.core.errors import AppError
from app.models.audit_event import AuditEvent
from app.models.payment import PaymentOccurrence
from app.models.user import User
from app.schemas.user import UserRef

router = APIRouter(prefix="/audit-log", tags=["audit"])


class AuditEventOut(BaseModel):
    id: int
    at: datetime
    actor: UserRef | None
    source: str
    action: str
    object_type: str | None
    object_id: int | None
    result: str
    details: dict[str, Any]
    ip: str | None

    @classmethod
    def of(cls, e: AuditEvent) -> "AuditEventOut":
        actor = (
            UserRef(id=e.actor_id, login=e.actor_login or "") if e.actor_id is not None else None
        )
        return cls(
            id=e.id,
            at=to_local(e.at),
            actor=actor,
            source=e.source,
            action=e.action,
            object_type=e.object_type,
            object_id=e.object_id,
            result=e.result,
            details=e.details,
            ip=e.ip,
        )


class AuditEventPage(BaseModel):
    items: list[AuditEventOut]
    total: int
    limit: int
    offset: int


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time(0), system_tz())


@router.get("", response_model=AuditEventPage)
async def audit_log(
    action: str | None = Query(None, max_length=64),
    actor_id: int | None = Query(None),
    recurring_payment_id: int | None = Query(None),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    page: Page = Depends(page_params),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> AuditEventPage:
    if date_from and date_to and date_from > date_to:
        raise AppError.validation("to", "Конец периода раньше начала")
    where: list[ColumnElement[bool]] = [AuditEvent.team_id == admin.team_id]
    if action:
        if action.endswith("."):  # prefix, e.g. "auth."
            escaped = action.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append(AuditEvent.action.like(f"{escaped}%", escape="\\"))
        else:
            where.append(AuditEvent.action == action)
    if actor_id is not None:
        where.append(AuditEvent.actor_id == actor_id)
    if recurring_payment_id is not None:  # The payment and its periods
        periods = select(PaymentOccurrence.id).where(
            PaymentOccurrence.recurring_payment_id == recurring_payment_id
        )
        where.append(
            or_(
                and_(
                    AuditEvent.object_type == "recurring_payment",
                    AuditEvent.object_id == recurring_payment_id,
                ),
                and_(
                    AuditEvent.object_type == "payment_occurrence",
                    AuditEvent.object_id.in_(periods),
                ),
            )
        )
    if date_from:
        where.append(AuditEvent.at >= _day_start(date_from))
    if date_to:
        where.append(AuditEvent.at < _day_start(date_to + timedelta(days=1)))

    total = await db.scalar(select(func.count()).select_from(AuditEvent).where(*where)) or 0
    rows = await db.scalars(
        select(AuditEvent)
        .where(*where)
        .order_by(AuditEvent.at.desc(), AuditEvent.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return AuditEventPage(
        items=[AuditEventOut.of(e) for e in rows], total=total, limit=page.limit, offset=page.offset
    )
