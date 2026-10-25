"""GET /payments/summary (control example AT21) and GET /config."""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.services.teams import ensure_default
from tests.helpers import ADMIN, bearer, freeze, login

S = "/api/v1/payments/summary"


async def _occurrence(
    db: AsyncSession, currency: str, amount: str, due: date, paid: date | None = None
) -> None:
    now = Clock().now()
    team = await ensure_default(db)
    rp = RecurringPayment(
        team_id=team.id,
        title=f"{currency} {amount}",
        amount=Decimal(amount),
        currency=currency,
        periodicity="monthly",
        anchor_day=due.day,
        first_due_date=due,
        status="active",
        created_by_login="admin",
        created_at=now,
        updated_at=now,
    )
    db.add(rp)
    await db.flush()
    db.add(
        PaymentOccurrence(
            recurring_payment_id=rp.id,
            team_id=team.id,
            period_index=0,
            title=rp.title,
            amount=rp.amount,
            currency=currency,
            due_date=due,
            status="paid" if paid else "unpaid",
            paid_date=paid,
            created_at=now,
            updated_at=now,
        )
    )
    await db.commit()


async def _at21(db: AsyncSession) -> None:
    """today 2026-11-15; November: RUB 1000 paid, 500 overdue, 200 upcoming; USD 10 paid; EUR 20."""
    await _occurrence(db, "RUB", "1000", date(2026, 11, 5), paid=date(2026, 11, 7))  # paid late
    await _occurrence(db, "RUB", "500", date(2026, 11, 10))
    await _occurrence(db, "RUB", "200", date(2026, 11, 25))
    await _occurrence(db, "USD", "10", date(2026, 11, 1), paid=date(2026, 11, 1))
    await _occurrence(db, "EUR", "20", date(2026, 11, 30))
    # outside November — must not be counted
    await _occurrence(db, "RUB", "99999", date(2026, 10, 31))
    await _occurrence(db, "USD", "77", date(2026, 12, 1))


async def test_at21_control_example(client: AsyncClient, db: AsyncSession) -> None:
    freeze("2026-11-15T12:00:00+03:00")
    await _at21(db)
    h = bearer(await login(client, *ADMIN))
    r = await client.get(S, headers=h)
    assert r.status_code == 200
    assert r.json() == {
        "from": "2026-11-01",
        "to": "2026-11-30",
        "today": "2026-11-15",
        "currencies": [
            {"currency": "RUB", "total": "1700.00", "paid": "1000.00", "unpaid": "700.00",
             "overdue": "500.00", "count": 3},
            {"currency": "USD", "total": "10.00", "paid": "10.00", "unpaid": "0.00",
             "overdue": "0.00", "count": 1},
            {"currency": "EUR", "total": "20.00", "paid": "0.00", "unpaid": "20.00",
             "overdue": "0.00", "count": 1},
        ],
    }  # fmt: skip


async def test_invariants_over_whole_selection(client: AsyncClient, db: AsyncSession) -> None:
    freeze("2026-11-15T12:00:00+03:00")
    await _at21(db)
    h = bearer(await login(client, *ADMIN))
    body = (
        await client.get(S, headers=h, params={"from": "2026-10-01", "to": "2026-12-31"})
    ).json()
    for t in body["currencies"]:
        total, paid, unpaid, overdue = (
            Decimal(t[k]) for k in ("total", "paid", "unpaid", "overdue")
        )
        assert total == paid + unpaid and overdue <= unpaid
    rub = body["currencies"][0]
    assert rub["total"] == "101699.00" and rub["overdue"] == "100499.00" and rub["count"] == 4


async def test_empty_selection_gives_three_zero_currencies(client: AsyncClient) -> None:
    freeze("2026-11-15T12:00:00+03:00")
    h = bearer(await login(client, *ADMIN))
    body = (
        await client.get(S, headers=h, params={"from": "2030-01-01", "to": "2030-01-31"})
    ).json()
    assert [c["currency"] for c in body["currencies"]] == ["RUB", "USD", "EUR"]
    assert all(
        c["total"] == c["paid"] == c["unpaid"] == c["overdue"] == "0.00" and c["count"] == 0
        for c in body["currencies"]
    )


async def test_range_validation(client: AsyncClient) -> None:
    h = bearer(await login(client, *ADMIN))
    r = await client.get(S, headers=h, params={"from": "2026-12-01", "to": "2026-11-01"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "to"
    r = await client.get(S, headers=h, params={"from": "2026-01-01", "to": "2028-01-03"})
    assert r.status_code == 422
    r = await client.get(S, headers=h, params={"from": "2026-01-01", "to": "2028-01-02"})
    assert r.status_code == 200  # exactly 731 days
    r = await client.get(S, headers=h, params={"from": "bad"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "from"


async def test_config(client: AsyncClient) -> None:
    freeze("2026-11-06T21:30:00+00:00")
    h = bearer(await login(client, *ADMIN))
    r = await client.get("/api/v1/config", headers=h)
    assert r.status_code == 200
    assert r.json() == {
        "team": {"id": 1, "name": "aeza"},
        "timezone_offset": "+03:00",
        "timezone_label": "GMT+3",
        "today": "2026-11-07",
        "reminder_days_before": 3,
        "currencies": ["RUB", "USD", "EUR"],
        "periodicities": ["once", "daily", "weekly", "monthly", "every_n_days"],
        "telegram_bot_username": None,
        "miniapp_url": None,
        "channels": {"telegram": False, "email": False, "webhook": False, "extra": False},
        "dev_mode": True,
    }
    client.cookies.clear()
    assert (await client.get("/api/v1/config")).status_code == 401
    assert (await client.get(S)).status_code == 401
