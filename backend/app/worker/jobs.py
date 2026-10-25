"""Worker jobs. Every state lives in PostgreSQL, so restarts neither lose nor duplicate anything."""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import ChannelRegistry, get_channels
from app.core.clock import get_clock
from app.core.config import use_settings
from app.models.team import Team
from app.services import outbox, personal_reminders
from app.services.generator import ensure_all
from app.services.notification_settings import team_settings
from app.services.reminders import plan_reminders

logger = logging.getLogger("app.worker.jobs")


@dataclass
class CycleResult:
    periods_created: int
    reminders_created: int


async def run_cycle(db: AsyncSession, channels: ChannelRegistry | None = None) -> CycleResult:
    """Generate missing periods, then queue reminders that are due. One transaction.

    Reminders are planned team by team with each team's channels.
    """
    clock = await get_clock(db)
    periods = await ensure_all(db, clock)
    reminders = []
    for team_id in list(await db.scalars(select(Team.id).order_by(Team.id))):
        settings, _row = await team_settings(db, team_id)
        with use_settings(settings):
            team_channels = get_channels() if channels is None else channels
            reminders += await plan_reminders(db, clock, team_channels, team_id=team_id)
            await personal_reminders.plan(db, clock, team_id)
    await db.commit()
    if periods or reminders:
        logger.info("cycle: %d new periods, %d new reminders", periods, len(reminders))
    return CycleResult(periods_created=periods, reminders_created=len(reminders))


async def dispatch_deliveries(db: AsyncSession, channels: ChannelRegistry | None = None) -> int:
    """Send due deliveries; each one goes out with its team's settings."""
    group_count = await outbox.dispatch(db, channels)
    personal_count = await personal_reminders.dispatch(db)
    return group_count + personal_count
