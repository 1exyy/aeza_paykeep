"""GET/PATCH /settings/notifications, POST /settings/notifications/test — admin only."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, clock_dep, require_admin
from app.core.clock import Clock
from app.core.config import use_settings
from app.core.db import get_session
from app.models.user import User
from app.schemas.settings import (
    NotificationSettingsOut,
    NotificationSettingsPatch,
    SettingsTestRequest,
    SettingsTestResult,
)
from app.services import audit
from app.services import notification_settings as service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/notifications", response_model=NotificationSettingsOut)
async def get_notification_settings(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> NotificationSettingsOut:
    return await service.get(db, admin.team_id)


@router.patch("/notifications", response_model=NotificationSettingsOut)
async def update_notification_settings(
    body: NotificationSettingsPatch,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> NotificationSettingsOut:
    out = await service.update(db, clock, admin, body, client_ip(request))
    await db.commit()
    return out


@router.post("/notifications/test", response_model=SettingsTestResult)
async def test_notification_channel(
    body: SettingsTestRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> SettingsTestResult:
    settings, _row = await service.team_settings(db, admin.team_id)
    with use_settings(settings):  # the test goes out with this team's channels
        result = await service.send_test(clock, body.channel)
    ok = result.outcome == "sent"
    audit.record(
        db,
        clock,
        "settings.test",
        actor=admin,
        object_type=None,
        result="success" if ok else "failure",
        details={"channel": body.channel, "error": None if ok else result.error},
        ip=client_ip(request),
    )
    await db.commit()
    return SettingsTestResult(channel=body.channel, ok=ok, error=None if ok else result.error)
