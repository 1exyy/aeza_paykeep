"""Recurring payments: create, edit, stop, one-time completion (DOMAIN §3).

Callers commit.
"""

from datetime import date, timedelta
from typing import cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import get_channels
from app.core.clock import Clock
from app.core.errors import AppError, not_found, version_conflict
from app.core.money import format_money
from app.models.attachment import Attachment
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.models.user import User
from app.schemas.recurring import RecurringPaymentCreate, RecurringPaymentPatch, check_interval
from app.services import assignees, audit, events, outbox, personal_reminders
from app.services.generator import ensure_occurrences
from app.services.reminders import plan_reminders


async def next_due_dates(db: AsyncSession, ids: list[int], today: date) -> dict[int, date]:
    """Nearest due date ≥ today per payment (computed, never stored)."""
    if not ids:
        return {}
    rows = await db.execute(
        select(PaymentOccurrence.recurring_payment_id, func.min(PaymentOccurrence.due_date))
        .where(PaymentOccurrence.recurring_payment_id.in_(ids), PaymentOccurrence.due_date >= today)
        .group_by(PaymentOccurrence.recurring_payment_id)
    )
    return {rp_id: due for rp_id, due in rows.all()}


async def create_recurring(
    db: AsyncSession, clock: Clock, actor: User, data: RecurringPaymentCreate, ip: str | None
) -> RecurringPayment:
    today, now = clock.today(), clock.now()
    if data.next_due_date < today:
        raise AppError.validation(
            "next_due_date", "Дата ближайшей оплаты не может быть раньше сегодняшнего дня"
        )
    assignees.check_choice(data.assignee_ids, data.assign_all)
    chosen = await assignees.validate_ids(db, actor.team_id, data.assignee_ids)
    recurring = RecurringPayment(
        team_id=actor.team_id,
        title=data.title,
        amount=data.amount,
        currency=data.currency,
        periodicity=data.periodicity,
        interval_days=data.interval_days,
        anchor_day=data.next_due_date.day,
        first_due_date=data.next_due_date,
        status="active",
        created_by_id=actor.id,
        created_by_login=actor.login,
        created_at=now,
        updated_at=now,
    )
    db.add(recurring)
    await db.flush()
    await assignees.replace(db, recurring, chosen, data.assign_all)
    await ensure_occurrences(db, recurring, today, now)
    # Late creation queues team and eligible personal reminders in this transaction.
    await plan_reminders(db, clock, get_channels(), recurring_payment_id=recurring.id)
    await personal_reminders.plan(db, clock, actor.team_id)
    audit.record(
        db,
        clock,
        "recurring.create",
        actor=actor,
        object_type="recurring_payment",
        object_id=recurring.id,
        details={
            "title": recurring.title,
            "amount": format_money(recurring.amount),
            "currency": recurring.currency,
            "next_due_date": recurring.first_due_date.isoformat(),
            "periodicity": recurring.periodicity,
            "interval_days": recurring.interval_days,
            "assign_all": recurring.assign_all,
            "assignees": [u.login for u in chosen],
        },
        ip=ip,
    )
    await events.recurring_event(db, clock, "recurring.created", recurring)
    return recurring


async def stop_recurring(
    db: AsyncSession, clock: Clock, actor: User, recurring_id: int, ip: str | None
) -> tuple[RecurringPayment, list[str]]:
    """Stop: keep history, delete unpaid periods due after today. Repeated call is a no-op.

    Returns the payment and the storage names of attachment files to unlink after the commit.
    """
    recurring = await db.scalar(
        select(RecurringPayment)
        .where(RecurringPayment.id == recurring_id, RecurringPayment.team_id == actor.team_id)
        .with_for_update()
    )
    if recurring is None:
        raise not_found("Регулярный платёж не найден")
    if recurring.status == "stopped":
        return recurring, []

    today, now = clock.today(), clock.now()
    recurring.status = "stopped"
    recurring.stopped_at = now
    recurring.updated_at = now
    recurring.version += 1
    cancelled = await outbox.cancel_pending(db, recurring_payment_id=recurring.id)
    removed, orphaned_files = await _drop_unpaid(db, recurring.id, today + timedelta(days=1))
    audit.record(
        db,
        clock,
        "recurring.stop",
        actor=actor,
        object_type="recurring_payment",
        object_id=recurring.id,
        details={
            "title": recurring.title,
            "deleted_future_unpaid": removed,
            "cancelled_deliveries": cancelled,
        },
        ip=ip,
    )
    await events.recurring_event(db, clock, "recurring.stopped", recurring)
    return recurring, orphaned_files


async def _drop_unpaid(
    db: AsyncSession, recurring_id: int, due_from: date
) -> tuple[int, list[str]]:
    """Delete unpaid periods due on or after `due_from`; paid ones are history and stay.

    Their pending reminders are cancelled; attachments go with them (FK cascade) and the
    storage names are returned so the caller unlinks the files after the commit.
    """
    doomed = select(PaymentOccurrence.id).where(
        PaymentOccurrence.recurring_payment_id == recurring_id,
        PaymentOccurrence.status == "unpaid",
        PaymentOccurrence.due_date >= due_from,
    )
    for occurrence_id in list(await db.scalars(doomed)):
        await outbox.cancel_pending(db, occurrence_id=occurrence_id)
    files = list(
        await db.scalars(
            select(Attachment.storage_name).where(
                Attachment.occurrence_id.in_(doomed), Attachment.storage_name.is_not(None)
            )
        )
    )
    removed = await db.execute(
        delete(PaymentOccurrence)
        .where(PaymentOccurrence.id.in_(doomed))
        .returning(PaymentOccurrence.id)
    )
    return len(removed.all()), [name for name in files if name]


async def update_recurring(
    db: AsyncSession,
    clock: Clock,
    actor: User,
    recurring_id: int,
    data: RecurringPaymentPatch,
    ip: str | None,
) -> tuple[RecurringPayment, list[str]]:
    """Edit an active payment. Returns it and attachment files to unlink after commit.

    - title / amount / currency also change the unpaid periods due today or later;
    - next_due_date / periodicity / interval_days rebuild those periods from the new start;
    - assignee_ids / assign_all change the responsible users.
    Paid and past periods are history and never change.
    """
    given = data.model_fields_set - {"expected_version"}
    if not given:
        raise AppError.validation("body", "Передайте хотя бы одно поле для изменения")
    recurring = await db.scalar(
        select(RecurringPayment)
        .where(RecurringPayment.id == recurring_id, RecurringPayment.team_id == actor.team_id)
        .with_for_update()
    )
    if recurring is None:
        raise not_found("Регулярный платёж не найден")
    if data.expected_version is not None and data.expected_version != recurring.version:
        raise version_conflict()
    if recurring.status != "active":
        raise AppError.validation("body", "Прекращённый или завершённый платёж нельзя изменить")

    today, now = clock.today(), clock.now()
    changes: dict[str, object] = {}
    orphaned: list[str] = []

    content: dict[str, object] = {}
    for field in ("title", "amount", "currency"):
        value = getattr(data, field)
        if field in given and value is not None and value != getattr(recurring, field):
            content[field] = value
    if content:
        for field, value in content.items():
            setattr(recurring, field, value)
            changes[field] = format_money(value) if field == "amount" else value  # type: ignore[arg-type]
        await db.execute(
            update(PaymentOccurrence)
            .where(
                PaymentOccurrence.recurring_payment_id == recurring.id,
                PaymentOccurrence.status == "unpaid",
                PaymentOccurrence.due_date >= today,
            )
            .values(**content, updated_at=now, version=PaymentOccurrence.version + 1)
        )

    if given & {"next_due_date", "periodicity", "interval_days"}:
        periodicity = data.periodicity or recurring.periodicity
        if "interval_days" in given:
            interval = data.interval_days
        else:
            interval = recurring.interval_days if periodicity == "every_n_days" else None
        check_interval(periodicity, interval)
        current_next = await db.scalar(
            select(func.min(PaymentOccurrence.due_date)).where(
                PaymentOccurrence.recurring_payment_id == recurring.id,
                PaymentOccurrence.status == "unpaid",
                PaymentOccurrence.due_date >= today,
            )
        )
        start = data.next_due_date or current_next or today
        if start < today:
            raise AppError.validation(
                "next_due_date", "Дата ближайшей оплаты не может быть раньше сегодняшнего дня"
            )
        before_schedule = (recurring.periodicity, recurring.interval_days, current_next)
        if (periodicity, interval, start) != before_schedule:
            _, orphaned = await _drop_unpaid(db, recurring.id, today)
            last = await db.scalar(
                select(func.max(PaymentOccurrence.period_index)).where(
                    PaymentOccurrence.recurring_payment_id == recurring.id
                )
            )
            changes["schedule"] = {
                "from": {
                    "periodicity": recurring.periodicity,
                    "interval_days": recurring.interval_days,
                    "next_due_date": current_next.isoformat() if current_next else None,
                },
                "to": {
                    "periodicity": periodicity,
                    "interval_days": interval,
                    "next_due_date": start.isoformat(),
                },
            }
            recurring.periodicity, recurring.interval_days = periodicity, interval
            recurring.first_due_date, recurring.anchor_day = start, start.day
            recurring.index_base = (last + 1) if last is not None else 0

    if given & {"assignee_ids", "assign_all"}:
        before = await assignees.assignment(db, recurring.id)
        if data.assign_all is not None:
            assign_all = data.assign_all
        else:
            assign_all = recurring.assign_all if data.assignee_ids is None else False
        if data.assignee_ids is not None:
            ids = data.assignee_ids
        else:
            ids = [] if assign_all else [u.id for u in before.users]
        assignees.check_choice(ids, assign_all)
        chosen = await assignees.validate_ids(db, actor.team_id, ids)
        same = assign_all == before.assign_all and {u.id for u in chosen} == {
            u.id for u in before.users
        }
        if not same:
            await assignees.replace(db, recurring, chosen, assign_all)
            changes["assignees"] = {
                "from": {"assign_all": before.assign_all, "assignees": before.logins},
                "to": {"assign_all": assign_all, "assignees": [u.login for u in chosen]},
            }

    if not changes:
        return recurring, []
    recurring.version += 1
    recurring.updated_at = now
    await db.flush()
    if "schedule" in changes:
        await ensure_occurrences(db, recurring, today, now)
        await plan_reminders(db, clock, get_channels(), recurring_payment_id=recurring.id)
        await personal_reminders.plan(db, clock, actor.team_id)
    only_assignees = set(changes) == {"assignees"}
    details: dict[str, object] = {"title": recurring.title}
    if only_assignees:
        details.update(cast(dict[str, object], changes["assignees"]))
    else:
        details.update(changes)
    audit.record(
        db,
        clock,
        "recurring.update_assignees" if only_assignees else "recurring.update",
        actor=actor,
        object_type="recurring_payment",
        object_id=recurring.id,
        details=details,
        ip=ip,
    )
    return recurring, orphaned


async def sync_completion(db: AsyncSession, clock: Clock, recurring_id: int) -> str | None:
    """One-time payment: paid → completed (stopped); payment undone → active again.

    Returns the payment's status after the sync (None if it does not exist).
    """
    recurring = await db.get(RecurringPayment, recurring_id, with_for_update=True)
    if recurring is None:
        return None
    if recurring.periodicity != "once":
        return recurring.status
    if recurring.status == "stopped" and not recurring.completed:
        return recurring.status  # stopped by an admin: the payment status does not revive it
    status = await db.scalar(
        select(PaymentOccurrence.status).where(
            PaymentOccurrence.recurring_payment_id == recurring.id,
            PaymentOccurrence.period_index == recurring.index_base,
        )
    )
    now = clock.now()
    if status == "paid" and recurring.status == "active":
        recurring.status, recurring.completed, recurring.stopped_at = "stopped", True, now
    elif status == "unpaid" and recurring.completed:
        recurring.status, recurring.completed, recurring.stopped_at = "active", False, None
    else:
        return recurring.status
    recurring.version += 1
    recurring.updated_at = now
    return recurring.status
