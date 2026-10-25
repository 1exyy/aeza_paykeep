"""Business events for external channels (webhook, DOMAIN §12), queued in the caller's transaction.

Nothing is queued when no enabled channel handles the type (e.g. no WEBHOOK_URL).
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import get_channels
from app.core.clock import Clock, to_local
from app.core.money import format_money
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.services import assignees, outbox
from app.services.assignees import Assignment


def occurrence_data(occ: PaymentOccurrence) -> dict[str, Any]:
    return {
        "occurrence_id": occ.id,
        "recurring_payment_id": occ.recurring_payment_id,
        "title": occ.title,
        "amount": format_money(occ.amount),
        "currency": occ.currency,
        "due_date": occ.due_date.isoformat(),
        "status": occ.status,
        "paid_date": occ.paid_date.isoformat() if occ.paid_date else None,
        "paid_by": occ.paid_by_login,
        "paid_via": occ.paid_via,
    }


def recurring_data(rp: RecurringPayment, assignment: Assignment) -> dict[str, Any]:
    return {
        "recurring_payment_id": rp.id,
        "title": rp.title,
        "amount": format_money(rp.amount),
        "currency": rp.currency,
        "periodicity": rp.periodicity,
        "anchor_day": rp.anchor_day,
        "first_due_date": rp.first_due_date.isoformat(),
        "status": rp.status,
        "created_by": rp.created_by_login,
        "stopped_at": to_local(rp.stopped_at).isoformat() if rp.stopped_at else None,
        "assign_all": assignment.assign_all,
        "assignees": assignment.logins,
    }


async def occurrence_event(
    db: AsyncSession, clock: Clock, type: str, occ: PaymentOccurrence
) -> None:
    await outbox.enqueue(
        db,
        clock,
        get_channels(),
        type=type,
        team_id=occ.team_id,
        payload=occurrence_data(occ),
        occurrence_id=occ.id,
        recurring_payment_id=occ.recurring_payment_id,
    )


async def recurring_event(db: AsyncSession, clock: Clock, type: str, rp: RecurringPayment) -> None:
    await outbox.enqueue(
        db,
        clock,
        get_channels(),
        type=type,
        team_id=rp.team_id,
        payload=recurring_data(rp, await assignees.assignment(db, rp.id)),
        recurring_payment_id=rp.id,
    )
