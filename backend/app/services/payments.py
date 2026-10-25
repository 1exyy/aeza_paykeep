"""PATCH rules of a period (DOMAIN §4). A change of one period never touches another."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.errors import AppError, not_found, version_conflict
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.models.user import User
from app.schemas.occurrence import OccurrencePatch
from app.services import audit, events, outbox
from app.services.recurring import sync_completion

EARLIEST_PAYMENT = timedelta(days=366)


def _check_shape(data: OccurrencePatch) -> None:
    given = data.model_fields_set - {"expected_version"}
    if not given:
        raise AppError.validation("body", "Передайте status и/или paid_date")
    if "status" in given and data.status is None:
        raise AppError.validation("status", "Допустимо: paid, unpaid")
    if data.status == "paid" and data.paid_date is None:
        raise AppError.validation("paid_date", "Укажите фактическую дату оплаты")
    if data.status == "unpaid" and data.paid_date is not None:
        raise AppError.validation("paid_date", "При отмене оплаты дата не передаётся")
    if data.status is None and data.paid_date is None:
        raise AppError.validation("paid_date", "Чтобы отменить оплату, передайте status: unpaid")


async def get_for_update(
    db: AsyncSession, team_id: int, occurrence_id: int
) -> tuple[PaymentOccurrence, str]:
    row = (
        await db.execute(
            select(PaymentOccurrence, RecurringPayment.status)
            .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
            .where(PaymentOccurrence.id == occurrence_id, PaymentOccurrence.team_id == team_id)
            .with_for_update(of=PaymentOccurrence)
        )
    ).first()
    if row is None:
        raise not_found("Платёж не найден")
    return row[0], row[1]


async def patch_occurrence(
    db: AsyncSession,
    clock: Clock,
    actor: User,
    occurrence_id: int,
    data: OccurrencePatch,
    ip: str | None,
    source: str = "web",
) -> tuple[PaymentOccurrence, str]:
    _check_shape(data)
    occ, recurring_status = await get_for_update(db, actor.team_id, occurrence_id)
    if data.expected_version is not None and data.expected_version != occ.version:
        raise version_conflict()

    today = clock.today()
    if data.paid_date is not None:
        if data.paid_date > today:
            raise AppError.validation("paid_date", "Дата оплаты не может быть в будущем")
        if data.paid_date < occ.due_date - EARLIEST_PAYMENT:
            raise AppError.validation(
                "paid_date", "Дата оплаты не может быть раньше срока более чем на 366 дней"
            )

    old_date = occ.paid_date
    action: str | None = None
    if data.status == "unpaid":
        if occ.status == "paid":
            occ.status, occ.paid_date = "unpaid", None
            occ.paid_by_id, occ.paid_by_login, occ.paid_via = None, None, None
            action = "occurrence.mark_unpaid"
    elif data.status == "paid" and occ.status == "unpaid":
        occ.status, occ.paid_date = "paid", data.paid_date
        occ.paid_by_id, occ.paid_by_login, occ.paid_via = actor.id, actor.login, source
        action = "occurrence.mark_paid"
        await outbox.cancel_pending(db, occurrence_id=occ.id)
    else:  # date correction: status paid with a new date, or only paid_date
        if occ.status != "paid":
            raise AppError(409, "not_paid", "Платёж не отмечен как оплаченный")
        if data.paid_date != occ.paid_date:
            occ.paid_date = data.paid_date
            action = "occurrence.change_paid_date"

    if action is not None:
        occ.version += 1
        occ.updated_at = clock.now()
        audit.record(
            db,
            clock,
            action,
            actor=actor,
            source=source,
            object_type="payment_occurrence",
            object_id=occ.id,
            details={
                "title": occ.title,
                "due_date": occ.due_date.isoformat(),
                "paid_date_from": old_date.isoformat() if old_date else None,
                "paid_date_to": occ.paid_date.isoformat() if occ.paid_date else None,
            },
            ip=ip,
        )
        webhook_type = {
            "occurrence.mark_paid": "occurrence.paid",
            "occurrence.mark_unpaid": "occurrence.unpaid",
        }.get(action)
        if webhook_type:
            await events.occurrence_event(db, clock, webhook_type, occ)
            # A one-time payment completes when paid and reopens when the payment is undone.
            recurring_status = (
                await sync_completion(db, clock, occ.recurring_payment_id) or recurring_status
            )
    return occ, recurring_status
