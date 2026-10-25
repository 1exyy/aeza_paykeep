"""«Оплачено» button in the Telegram reminder (DOMAIN §9).

Atomic `UPDATE … WHERE status = 'unpaid' RETURNING`: of two simultaneous presses exactly one
marks the period paid; the other gets «Уже оплачено …» and the date does not change.
"""

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.texts import ru_date
from app.core.clock import Clock, get_clock
from app.core.config import use_settings
from app.models.payment import PaymentOccurrence
from app.services import assignees, audit, events, outbox, telegram_link
from app.services.notification_settings import team_settings
from app.services.recurring import sync_completion

NO_ACCESS = "Нет доступа. Откройте приложение и привяжите Telegram"


@dataclass
class PaidOutcome:
    alert: str  # answerCallbackQuery text
    paid_line: str | None = None  # appended to the message; the button is removed


def parse_callback(data: str | None) -> int | None:
    if not data or not data.startswith("paid:"):
        return None
    raw = data.removeprefix("paid:")
    return int(raw) if raw.isdigit() else None


async def press_paid(
    db: AsyncSession, telegram_user_id: int, occurrence_id: int, username: str | None = None
) -> PaidOutcome:
    """Handle one button press. Commits."""
    clock = await get_clock(db)
    # One bot serves every team; the period tells which team presses the button
    team_id = await db.scalar(
        select(PaymentOccurrence.team_id).where(PaymentOccurrence.id == occurrence_id)
    )
    if team_id is None:
        return PaidOutcome("Платёж не найден")
    settings, _row = await team_settings(db, team_id)
    with use_settings(settings):  # events of this press go to the team's channels
        return await _press(db, clock, team_id, telegram_user_id, occurrence_id, username)


async def _press(
    db: AsyncSession,
    clock: Clock,
    team_id: int,
    telegram_user_id: int,
    occurrence_id: int,
    username: str | None,
) -> PaidOutcome:
    found = await telegram_link.bind_on_contact(
        db, clock, telegram_user_id, username, team_id=team_id
    )
    user = found[0] if found else None
    details = {"telegram_user_id": telegram_user_id, "occurrence_id": occurrence_id}
    if user is None:
        audit.record(
            db,
            clock,
            "telegram.paid_button",
            actor=None,
            team_id=team_id,
            source="telegram",
            object_type="payment_occurrence",
            object_id=occurrence_id,
            result="failure",
            details={**details, "reason": "not_linked"},
        )
        await db.commit()
        return PaidOutcome(NO_ACCESS)

    recurring_id = await db.scalar(
        select(PaymentOccurrence.recurring_payment_id).where(PaymentOccurrence.id == occurrence_id)
    )
    if recurring_id is not None and user.role != "admin":
        has_assignees, responsible = await assignees.responsible_users(db, recurring_id)
        if has_assignees and user.id not in {u.id for u in responsible}:
            audit.record(
                db,
                clock,
                "telegram.paid_button",
                actor=user,
                source="telegram",
                object_type="payment_occurrence",
                object_id=occurrence_id,
                result="failure",
                details={**details, "reason": "not_assignee"},
            )
            await db.commit()
            names = ", ".join(u.login for u in responsible) or "—"
            return PaidOutcome(f"Оплату отмечает ответственный: {names}"[:190])

    today = clock.today()
    paid = await db.scalar(
        update(PaymentOccurrence)
        .where(PaymentOccurrence.id == occurrence_id, PaymentOccurrence.status == "unpaid")
        .values(
            status="paid",
            paid_date=today,
            paid_by_id=user.id,
            paid_by_login=user.login,
            paid_via="telegram",
            version=PaymentOccurrence.version + 1,
            updated_at=clock.now(),
        )
        .returning(PaymentOccurrence.id)
    )
    if paid is None:
        row = (
            await db.execute(
                select(PaymentOccurrence.id, PaymentOccurrence.paid_date).where(
                    PaymentOccurrence.id == occurrence_id
                )
            )
        ).first()
        await db.rollback()
        if row is None:
            return PaidOutcome("Платёж не найден")
        when = f" {ru_date(row.paid_date)}" if row.paid_date else ""
        return PaidOutcome(f"Уже оплачено{when}")

    await outbox.cancel_pending(db, occurrence_id=occurrence_id)
    occurrence = await db.get(PaymentOccurrence, occurrence_id, populate_existing=True)
    assert occurrence is not None
    await events.occurrence_event(db, clock, "occurrence.paid", occurrence)
    await sync_completion(db, clock, occurrence.recurring_payment_id)
    audit.record(
        db,
        clock,
        "telegram.paid_button",
        actor=user,
        source="telegram",
        object_type="payment_occurrence",
        object_id=occurrence_id,
        details={**details, "paid_date": today.isoformat()},
    )
    await db.commit()
    line = f"✅ Оплачено {ru_date(today)} — {user.login}"
    return PaidOutcome(alert=line, paid_line=line)
