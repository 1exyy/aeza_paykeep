"""Demo data (DOMAIN §15). Dates are relative to "today", so the demo works on any day.

Run: `uv run python -m app.seed`. Idempotent: existing users and payments (by title) are kept.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock, get_clock, system_tz
from app.core.config import get_settings
from app.core.db import dispose_engine, get_sessionmaker
from app.core.logging import setup_logging
from app.core.security import hash_password
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.models.user import User
from app.services import assignees
from app.services.bootstrap import ensure_admin
from app.services.generator import ensure_occurrences
from app.services.schedule import add_months, due_date

logger = logging.getLogger("app.seed")

DEMO_USERS = {"anna": "anna-demo-123", "boris": "boris-demo-123"}


@dataclass
class Seeded:
    users: list[str]
    payments: list[str]


async def _user(
    db: AsyncSession, clock: Clock, team_id: int, login: str, password: str
) -> tuple[User, bool]:
    user = await db.scalar(
        select(User).where(
            User.team_id == team_id, func.lower(User.login) == login, User.deleted_at.is_(None)
        )
    )
    if user is not None:
        return user, False
    now = clock.now()
    user = User(
        team_id=team_id,
        login=login,
        password_hash=hash_password(password),
        role="user",
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.flush()
    return user, True


async def _recurring(
    db: AsyncSession,
    clock: Clock,
    admin: User,
    title: str,
    amount: str,
    currency: str,
    first_due: date,
    anchor_day: int,
) -> RecurringPayment | None:
    if await db.scalar(
        select(RecurringPayment.id).where(
            RecurringPayment.team_id == admin.team_id, RecurringPayment.title == title
        )
    ):
        return None
    now = clock.now()
    rp = RecurringPayment(
        team_id=admin.team_id,
        title=title,
        amount=Decimal(amount),
        currency=currency,
        periodicity="monthly",
        anchor_day=anchor_day,
        first_due_date=first_due,
        status="active",
        created_by_id=admin.id,
        created_by_login=admin.login,
        created_at=now,
        updated_at=now,
    )
    db.add(rp)
    await db.flush()
    return rp


async def _periods(db: AsyncSession, rp: RecurringPayment) -> list[PaymentOccurrence]:
    rows = await db.scalars(
        select(PaymentOccurrence)
        .where(PaymentOccurrence.recurring_payment_id == rp.id)
        .order_by(PaymentOccurrence.period_index)
    )
    return list(rows)


def _pay(occ: PaymentOccurrence, paid: date, user: User, now: datetime) -> None:
    occ.status, occ.paid_date = "paid", paid
    occ.paid_by_id, occ.paid_by_login, occ.paid_via = user.id, user.login, "web"
    occ.version, occ.updated_at = 2, now


def _mark_reminded(periods: list[PaymentOccurrence], today: date) -> None:
    """Historical periods: reminders count as already sent, so the first start sends nothing old."""
    hour = get_settings().reminder_send_from_hour
    for occ in periods:
        if occ.due_date < today:
            moment = datetime.combine(occ.due_date - timedelta(days=3), time(hour), system_tz())
            occ.reminder_sent_at = moment
    # The reminder planner skips periods with reminder_sent_at set, so no old reminders go out.


async def seed(db: AsyncSession) -> Seeded:
    admin = await ensure_admin(db)
    if admin is None:
        raise RuntimeError("Set ADMIN_LOGIN and ADMIN_PASSWORD in .env before seeding")
    clock = await get_clock(db)
    today, now = clock.today(), clock.now()
    result = Seeded(users=[], payments=[])

    users = {}
    for login, password in DEMO_USERS.items():
        users[login], created = await _user(db, clock, admin.team_id, login, password)
        if created:
            result.users.append(login)
    anna, boris = users["anna"], users["boris"]

    # 1. Rent, RUB, the 5th: on time, 4 days late, last one unpaid and overdue.
    last_past = today.replace(day=5) if today.day > 5 else add_months(today.replace(day=5), -1)
    rent = await _recurring(
        db, clock, admin, "Аренда офиса", "85000.00", "RUB", add_months(last_past, -2), 5
    )
    if rent:
        await assignees.replace(db, rent, [anna], assign_all=False)
        await ensure_occurrences(db, rent, today, now)
        periods = await _periods(db, rent)
        _pay(periods[0], periods[0].due_date, anna, now)
        _pay(periods[1], periods[1].due_date + timedelta(days=4), boris, now)
        _mark_reminded(periods, today)
        result.payments.append(rent.title)

    # 2. Server, USD, the 31st: "last day of the month"; one paid, one unpaid.
    server_first = add_months(today, -2, anchor_day=31)
    server = await _recurring(db, clock, admin, "Сервер (VPS)", "120.00", "USD", server_first, 31)
    if server:
        await assignees.replace(db, server, [anna, boris], assign_all=False)
        await ensure_occurrences(db, server, today, now)
        periods = await _periods(db, server)
        _pay(periods[0], periods[0].due_date, anna, now)
        _mark_reminded(periods, today)
        result.payments.append(server.title)

    # 3. Subscription, EUR: paid; the next period is due in ≤ 3 days → reminder right after start.
    sub_first = add_months(today, -1) + timedelta(days=2)
    subscription = await _recurring(
        db, clock, admin, "Подписка на сервис", "15.99", "EUR", sub_first, sub_first.day
    )
    if subscription:
        await assignees.replace(db, subscription, [], assign_all=True)
        await ensure_occurrences(db, subscription, today, now)
        periods = await _periods(db, subscription)
        _pay(periods[0], periods[0].due_date - timedelta(days=1), anna, now)
        _mark_reminded(periods, today)
        result.payments.append(subscription.title)

    # 4. Old hosting, USD: stopped, history of 3 paid periods kept.
    old_first = add_months(today, -4)
    hosting = await _recurring(
        db, clock, admin, "Старый хостинг", "40.00", "USD", old_first, old_first.day
    )
    if hosting:
        for n in range(3):
            due = due_date(old_first, old_first.day, n)
            occ = PaymentOccurrence(
                recurring_payment_id=hosting.id,
                team_id=hosting.team_id,
                period_index=n,
                title=hosting.title,
                amount=hosting.amount,
                currency=hosting.currency,
                due_date=due,
                status="unpaid",
                created_at=now,
                updated_at=now,
            )
            _pay(occ, due, boris, now)
            db.add(occ)
        await db.flush()
        hosting.status, hosting.stopped_at, hosting.version = "stopped", now, 2
        _mark_reminded(await _periods(db, hosting), today)
        result.payments.append(hosting.title)

    await db.commit()
    return result


async def main() -> None:
    setup_logging(get_settings().log_level)
    async with get_sessionmaker()() as db:
        result = await seed(db)
    await dispose_engine()
    logger.info(
        "Seed done. New users: %s. New payments: %s",
        ", ".join(result.users) or "—",
        ", ".join(result.payments) or "—",
    )


if __name__ == "__main__":
    asyncio.run(main())
