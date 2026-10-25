"""Plan and send private Telegram reminders on each user's own schedule."""

import logging
from datetime import datetime, time, timedelta
from html import escape

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import SendResult
from app.channels.telegram import _send_one, mention, paid_keyboard
from app.channels.texts import reminder_text
from app.core.clock import Clock, get_clock, real_now, system_tz
from app.core.config import get_settings, use_settings
from app.models.notification import PersonalReminder
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.models.team import Team
from app.models.user import User
from app.services import assignees, audit
from app.services.notification_settings import team_settings
from app.services.reminders import reminder_payload
from app.services.schedule import schedule_of

logger = logging.getLogger("app.services.personal_reminders")
MAX_LEAD_DAYS = 30
MAX_ATTEMPTS = 5
STALE_SENDING = timedelta(minutes=5)


def _remind_day(period: PaymentOccurrence, recurring: RecurringPayment, user: User):
    lead = schedule_of(recurring).reminder_lead(user.telegram_dm_days_before)
    return period.due_date - timedelta(days=lead)


def _ready(clock: Clock, period: PaymentOccurrence, reminder_day, send_hour: int) -> bool:
    today, now = clock.today(), clock.now()
    if today < reminder_day:
        return False
    created_day = period.created_at.astimezone(system_tz()).date()
    return not (today == reminder_day and created_day < reminder_day and now.hour < send_hour)


async def plan(db: AsyncSession, clock: Clock, team_id: int) -> int:
    """Queue one DM per eligible user and period. The unique key prevents duplicates."""
    settings = get_settings()
    if not settings.telegram_dm_reminders or not settings.telegram_bot_token.get_secret_value():
        return 0
    users = list(
        await db.scalars(
            select(User)
            .where(
                User.team_id == team_id,
                User.deleted_at.is_(None),
                User.telegram_user_id.is_not(None),
                User.telegram_dm_enabled.is_(True),
            )
            .order_by(User.id)
        )
    )
    if not users:
        return 0
    today = clock.today()
    periods = await db.execute(
        select(PaymentOccurrence, RecurringPayment)
        .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
        .where(
            PaymentOccurrence.team_id == team_id,
            PaymentOccurrence.status == "unpaid",
            RecurringPayment.status == "active",
            PaymentOccurrence.due_date <= today + timedelta(days=MAX_LEAD_DAYS),
        )
        .order_by(PaymentOccurrence.due_date, PaymentOccurrence.id)
    )
    created = 0
    for period, recurring in periods.all():
        has_assignees, responsible = await assignees.responsible_users(db, recurring.id)
        responsible_ids = {user.id for user in responsible}
        for user in users:
            if has_assignees and user.id not in responsible_ids:
                continue
            reminder_day = _remind_day(period, recurring, user)
            if not _ready(clock, period, reminder_day, settings.reminder_send_from_hour):
                continue
            moment = clock.now()
            reminder_id = await db.scalar(
                insert(PersonalReminder)
                .values(
                    user_id=user.id,
                    occurrence_id=period.id,
                    status="pending",
                    attempts=0,
                    next_attempt_at=real_now(),
                    created_at=moment,
                    updated_at=moment,
                )
                .on_conflict_do_nothing(index_elements=["user_id", "occurrence_id"])
                .returning(PersonalReminder.id)
            )
            created += reminder_id is not None
    return created


async def _claim(db: AsyncSession, limit: int) -> list[int]:
    now = real_now()
    ids = list(
        await db.scalars(
            select(PersonalReminder.id)
            .where(PersonalReminder.status == "pending", PersonalReminder.next_attempt_at <= now)
            .order_by(PersonalReminder.next_attempt_at, PersonalReminder.id)
            .limit(limit)
            .with_for_update(skip_locked=True, of=PersonalReminder)
        )
    )
    if ids:
        await db.execute(
            update(PersonalReminder)
            .where(PersonalReminder.id.in_(ids))
            .values(
                status="sending",
                attempts=PersonalReminder.attempts + 1,
                sending_started_at=now,
            )
        )
    await db.commit()
    return ids


def _hold(reminder: PersonalReminder, clock: Clock, *, until: datetime | None = None) -> None:
    reminder.status = "pending"
    reminder.attempts -= 1  # waiting for a preference or due day is not a send attempt
    reminder.sending_started_at = None
    reminder.next_attempt_at = until or real_now() + timedelta(minutes=1)
    reminder.updated_at = clock.now()


async def _deliver(db: AsyncSession, reminder_id: int) -> None:
    reminder = await db.get(PersonalReminder, reminder_id)
    if reminder is None or reminder.status != "sending":
        return
    clock = await get_clock(db)
    user = await db.get(User, reminder.user_id)
    period = await db.get(PaymentOccurrence, reminder.occurrence_id)
    recurring = await db.get(RecurringPayment, period.recurring_payment_id) if period else None
    if (
        user is None
        or period is None
        or recurring is None
        or user.deleted_at is not None
        or period.status != "unpaid"
        or recurring.status != "active"
    ):
        reminder.status, reminder.last_error = "failed", "cancelled"
        reminder.updated_at = clock.now()
        await db.commit()
        return
    if not user.telegram_dm_enabled or user.telegram_user_id is None:
        _hold(reminder, clock, until=real_now() + timedelta(hours=1))
        await db.commit()
        return
    settings, _row = await team_settings(db, user.team_id)
    with use_settings(settings):
        active = get_settings()
        if (
            not active.telegram_dm_reminders
            or not active.telegram_bot_token.get_secret_value()
        ):
            _hold(reminder, clock, until=real_now() + timedelta(hours=1))
            await db.commit()
            return
        has_assignees, responsible = await assignees.responsible_users(db, recurring.id)
        if has_assignees and user.id not in {person.id for person in responsible}:
            reminder.status, reminder.last_error = "failed", "no longer responsible"
            reminder.updated_at = clock.now()
            await db.commit()
            return
        reminder_day = _remind_day(period, recurring, user)
        if not _ready(clock, period, reminder_day, active.reminder_send_from_hour):
            target = datetime.combine(
                reminder_day, time(active.reminder_send_from_hour), system_tz()
            )
            target -= timedelta(days=clock.offset_days)
            _hold(reminder, clock, until=max(real_now() + timedelta(minutes=1), target))
            await db.commit()
            return
        assignment = await assignees.assignment(db, recurring.id)
        line = (
            "Ответственные: "
            + (", ".join(mention(person) for person in responsible) or "—")
            if has_assignees
            else None
        )
        payload = reminder_payload(
            period, overdue=clock.today() > period.due_date, assignment=assignment
        )
        team = await db.get(Team, user.team_id)
        heading = f"Команда «{escape(team.name)}»\n" if team else ""
        text = heading + reminder_text(payload, assignees_line=line, html=True)
        try:
            result = await _send_one(user.telegram_user_id, text, paid_keyboard(period.id))
        except Exception as exc:
            logger.exception("Private reminder %s failed unexpectedly", reminder.id)
            result = SendResult.failed(f"unexpected: {type(exc).__name__}")
    reminder.last_error = result.error
    reminder.updated_at = clock.now()
    if result.outcome == "sent":
        reminder.status, reminder.sent_at = "sent", clock.now()
    elif result.outcome == "failed" and reminder.attempts < MAX_ATTEMPTS:
        reminder.status = "pending"
        wait = result.retry_after or 30 * (2 ** (reminder.attempts - 1))
        reminder.next_attempt_at = real_now() + timedelta(seconds=wait)
    else:
        reminder.status = "unknown" if result.outcome == "unknown" else "failed"
    if reminder.status != "pending":
        audit.record(
            db,
            clock,
            "notification.sent" if reminder.status == "sent" else "notification.failed",
            actor=None,
            team_id=period.team_id,
            source="system",
            object_type="personal_reminder",
            object_id=reminder.id,
            result="success" if reminder.status == "sent" else "failure",
            details={
                "channel": "telegram_dm",
                "user_id": user.id,
                "occurrence_id": period.id,
                "status": reminder.status,
                "error": result.error,
            },
        )
    await db.commit()


async def dispatch(db: AsyncSession, limit: int = 20) -> int:
    """Claim and send due DMs independently of the team channels."""
    await db.execute(
        update(PersonalReminder)
        .where(
            PersonalReminder.status == "sending",
            PersonalReminder.sending_started_at < real_now() - STALE_SENDING,
        )
        .values(status="unknown", last_error="no result: worker stopped while sending")
    )
    ids = await _claim(db, limit)
    for reminder_id in ids:
        await _deliver(db, reminder_id)
    return len(ids)
