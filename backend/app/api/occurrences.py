"""GET /payment-occurrences, GET/PATCH /payment-occurrences/{id} — both roles."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import client_ip, clock_dep, current_user
from app.api.pagination import Page, page_params
from app.core.clock import Clock
from app.core.db import get_session
from app.core.errors import AppError, not_found
from app.models.payment import PaymentOccurrence, RecurringPayment, RecurringPaymentAssignee
from app.models.user import User
from app.schemas.occurrence import OccurrenceOut, OccurrencePage, OccurrencePatch
from app.services import assignees, attachments, payments

router = APIRouter(prefix="/payment-occurrences", tags=["payment-occurrences"])


@router.get("", response_model=OccurrencePage)
async def list_occurrences(
    due_from: date | None = Query(None),
    due_to: date | None = Query(None),
    status: Literal["paid", "unpaid"] | None = Query(None),
    overdue: bool | None = Query(None),
    currency: Literal["RUB", "USD", "EUR"] | None = Query(None),
    recurring_payment_id: int | None = Query(None),
    assignee_id: int | None = Query(None),
    sort: Literal["due_date", "-due_date"] = Query("-due_date"),
    page: Page = Depends(page_params),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> OccurrencePage:
    if due_from and due_to and due_from > due_to:
        raise AppError.validation("due_to", "Конец диапазона раньше начала")
    today = clock.today()
    occ = PaymentOccurrence
    where = [occ.team_id == user.team_id]
    if due_from:
        where.append(occ.due_date >= due_from)
    if due_to:
        where.append(occ.due_date <= due_to)
    if status:
        where.append(occ.status == status)
    if overdue is not None:
        cond = and_(occ.status == "unpaid", occ.due_date < today)
        where.append(cond if overdue else not_(cond))
    if currency:
        where.append(occ.currency == currency)
    if recurring_payment_id is not None:
        where.append(occ.recurring_payment_id == recurring_payment_id)
    if assignee_id is not None:  # Chosen explicitly or «all users»
        explicit = exists().where(
            RecurringPaymentAssignee.recurring_payment_id == occ.recurring_payment_id,
            RecurringPaymentAssignee.user_id == assignee_id,
        )
        everyone = aliased(RecurringPayment)  # the list query joins RecurringPayment itself
        assign_all = exists().where(
            everyone.id == occ.recurring_payment_id, everyone.assign_all.is_(True)
        )
        where.append(or_(explicit, assign_all))

    total = await db.scalar(select(func.count()).select_from(occ).where(*where)) or 0
    order = (
        (occ.due_date.asc(), occ.id.asc())
        if sort == "due_date"
        else (occ.due_date.desc(), occ.id.desc())
    )
    rows = await db.execute(
        select(occ, RecurringPayment.status)
        .join(RecurringPayment, RecurringPayment.id == occ.recurring_payment_id)
        .where(*where)
        .order_by(*order)
        .limit(page.limit)
        .offset(page.offset)
    )
    found = rows.all()
    counts = await attachments.counts(db, [o.id for o, _ in found])
    assigned = await assignees.assignments(db, list({o.recurring_payment_id for o, _ in found}))
    return OccurrencePage(
        items=[
            OccurrenceOut.of(
                o, rs, today, counts.get(o.id, 0), assigned.get(o.recurring_payment_id)
            )
            for o, rs in found
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{id}", response_model=OccurrenceOut)
async def get_occurrence(
    id: int = Path(ge=1),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> OccurrenceOut:
    row = (
        await db.execute(
            select(PaymentOccurrence, RecurringPayment.status)
            .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
            .where(PaymentOccurrence.id == id, PaymentOccurrence.team_id == user.team_id)
        )
    ).first()
    if row is None:
        raise not_found("Платёж не найден")
    counts = await attachments.counts(db, [row[0].id])
    assigned = await assignees.assignment(db, row[0].recurring_payment_id)
    return OccurrenceOut.of(row[0], row[1], clock.today(), counts.get(row[0].id, 0), assigned)


@router.patch("/{id}", response_model=OccurrenceOut)
async def patch_occurrence(
    body: OccurrencePatch,
    request: Request,
    id: int = Path(ge=1),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> OccurrenceOut:
    occ, recurring_status = await payments.patch_occurrence(
        db, clock, user, id, body, client_ip(request)
    )
    await db.commit()
    counts = await attachments.counts(db, [occ.id])
    assigned = await assignees.assignment(db, occ.recurring_payment_id)
    return OccurrenceOut.of(occ, recurring_status, clock.today(), counts.get(occ.id, 0), assigned)
