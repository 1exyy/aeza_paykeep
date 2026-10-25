"""GET /notifications/deliveries — delivery statuses, admin only, read-only."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.pagination import Page, page_params
from app.core.db import get_session
from app.models.notification import Delivery, Notification
from app.models.user import User
from app.schemas.notification import DeliveryOut, DeliveryPage

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/deliveries", response_model=DeliveryPage)
async def list_deliveries(
    occurrence_id: int | None = Query(None),
    channel: Literal["telegram", "email", "webhook", "extra"] | None = Query(None),
    status: Literal["pending", "sending", "sent", "failed", "unknown"] | None = Query(None),
    page: Page = Depends(page_params),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> DeliveryPage:
    where = [Notification.team_id == admin.team_id]
    if occurrence_id is not None:
        where.append(Notification.occurrence_id == occurrence_id)
    if channel:
        where.append(Delivery.channel == channel)
    if status:
        where.append(Delivery.status == status)
    base = select(Delivery, Notification).join(
        Notification, Notification.id == Delivery.notification_id
    )
    total = (
        await db.scalar(
            select(func.count())
            .select_from(Delivery)
            .join(Notification, Notification.id == Delivery.notification_id)
            .where(*where)
        )
        or 0
    )
    rows = await db.execute(
        base.where(*where).order_by(Delivery.id.desc()).limit(page.limit).offset(page.offset)
    )
    return DeliveryPage(
        items=[DeliveryOut.of(d, n) for d, n in rows.all()],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
