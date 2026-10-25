"""Which periods get the "due soon" reminder (DOMAIN §6).

A period is reminded once in its life when it is unpaid, its payment is active and
today ≥ due − REMINDER_DAYS_BEFORE:
- normally from REMINDER_SEND_FROM_HOUR (09:00) on the day due − 3;
- right away if the period was created when ≤ 3 days were left (late creation);
- after downtime the missed reminder still goes, marked «Срок оплаты прошёл» if due has passed.
"""

from datetime import timedelta

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import ChannelRegistry
from app.core.clock import Clock, system_tz
from app.core.config import get_settings
from app.core.money import format_money
from app.models.notification import Notification
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.services import assignees, outbox
from app.services.assignees import Assignment
from app.services.schedule import schedule_of

TYPE = "payment.due_soon"


def reminder_payload(
    occ: PaymentOccurrence, overdue: bool, assignment: Assignment | None = None
) -> dict:
    assignment = assignment or Assignment()
    return {
        "occurrence_id": occ.id,
        "recurring_payment_id": occ.recurring_payment_id,
        "title": occ.title,
        "amount": format_money(occ.amount),
        "currency": occ.currency,
        "due_date": occ.due_date.isoformat(),
        "overdue": overdue,
        "assign_all": assignment.assign_all,
        "assignees": assignment.logins,
    }


async def plan_reminders(
    db: AsyncSession,
    clock: Clock,
    channels: ChannelRegistry,
    recurring_payment_id: int | None = None,
    team_id: int | None = None,
) -> list[Notification]:
    """Create reminders that are due now (caller commits). Idempotent.

    The worker calls it per team with that team's channels.
    """
    settings = get_settings()
    days = timedelta(days=settings.reminder_days_before)
    today, now = clock.today(), clock.now()

    occ = PaymentOccurrence
    already = exists().where(and_(Notification.occurrence_id == occ.id, Notification.type == TYPE))
    stmt = (
        select(occ, RecurringPayment)
        .join(RecurringPayment, RecurringPayment.id == occ.recurring_payment_id)
        .where(
            occ.status == "unpaid",
            RecurringPayment.status == "active",
            occ.reminder_sent_at.is_(None),
            occ.due_date <= today + days,
            ~already,
        )
        .order_by(occ.due_date, occ.id)
    )
    if recurring_payment_id is not None:
        stmt = stmt.where(occ.recurring_payment_id == recurring_payment_id)
    if team_id is not None:
        stmt = stmt.where(occ.team_id == team_id)

    created = []
    for period, recurring in (await db.execute(stmt)).all():
        # frequent payments are reminded no earlier than the previous due date
        lead = schedule_of(recurring).reminder_lead(settings.reminder_days_before)
        remind_day = period.due_date - timedelta(days=lead)
        if today < remind_day:
            continue
        created_day = period.created_at.astimezone(system_tz()).date()
        late_creation = created_day >= remind_day
        if (
            not late_creation
            and today == remind_day
            and now.hour < settings.reminder_send_from_hour
        ):
            continue
        notification = await outbox.enqueue(
            db,
            clock,
            channels,
            type=TYPE,
            team_id=period.team_id,
            payload=reminder_payload(
                period,
                overdue=today > period.due_date,
                assignment=await assignees.assignment(db, period.recurring_payment_id),
            ),
            occurrence_id=period.id,
            recurring_payment_id=period.recurring_payment_id,
        )
        if notification is not None:
            created.append(notification)
    return created
