from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.clock import to_local
from app.core.money import format_money
from app.models.payment import PaymentOccurrence
from app.schemas.user import UserRef
from app.services.assignees import Assignment

State = Literal["upcoming", "overdue", "paid", "paid_late"]


def is_overdue(occ: PaymentOccurrence, today: date) -> bool:
    """Unpaid and today is after the due date (payment on the due date is on time)."""
    return occ.status == "unpaid" and today > occ.due_date


def is_paid_late(occ: PaymentOccurrence) -> bool:
    return occ.status == "paid" and occ.paid_date is not None and occ.paid_date > occ.due_date


def state_of(occ: PaymentOccurrence, today: date) -> State:
    if occ.status == "paid":
        return "paid_late" if is_paid_late(occ) else "paid"
    return "overdue" if is_overdue(occ, today) else "upcoming"


class OccurrenceOut(BaseModel):
    id: int
    recurring_payment_id: int
    title: str
    amount: str
    currency: str
    due_date: date
    status: Literal["paid", "unpaid"]
    paid_date: date | None
    is_overdue: bool
    is_paid_late: bool
    state: State
    recurring_status: Literal["active", "stopped"]
    assign_all: bool
    assignees: list[UserRef]
    paid_by: UserRef | None
    paid_via: Literal["web", "telegram"] | None
    reminder_sent_at: datetime | None
    attachments_count: int
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(
        cls,
        occ: PaymentOccurrence,
        recurring_status: str,
        today: date,
        attachments_count: int = 0,
        assignment: Assignment | None = None,
    ) -> "OccurrenceOut":
        assignment = assignment or Assignment()
        paid_by = (
            UserRef(id=occ.paid_by_id or 0, login=occ.paid_by_login)
            if occ.paid_by_login is not None
            else None
        )
        return cls(
            id=occ.id,
            recurring_payment_id=occ.recurring_payment_id,
            title=occ.title,
            amount=format_money(occ.amount),
            currency=occ.currency,
            due_date=occ.due_date,
            status=occ.status,  # type: ignore[arg-type]
            paid_date=occ.paid_date,
            is_overdue=is_overdue(occ, today),
            is_paid_late=is_paid_late(occ),
            state=state_of(occ, today),
            recurring_status=recurring_status,  # type: ignore[arg-type]
            assign_all=assignment.assign_all,
            assignees=[UserRef(id=u.id, login=u.login) for u in assignment.users],
            paid_by=paid_by,
            paid_via=occ.paid_via,  # type: ignore[arg-type]
            reminder_sent_at=to_local(occ.reminder_sent_at) if occ.reminder_sent_at else None,
            attachments_count=attachments_count,
            version=occ.version,
            created_at=to_local(occ.created_at),
            updated_at=to_local(occ.updated_at),
        )


class OccurrencePage(BaseModel):
    items: list[OccurrenceOut]
    total: int
    limit: int
    offset: int


class OccurrencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["paid", "unpaid"] | None = None
    paid_date: date | None = None
    expected_version: int | None = None
