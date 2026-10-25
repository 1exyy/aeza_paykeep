"""Recurring payments and the period generator (DOMAIN §3, §5)."""

from datetime import date

from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.clock import get_clock
from app.models.audit_event import AuditEvent
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.services.generator import ensure_all
from tests.helpers import ADMIN, bearer, freeze, login

R = "/api/v1/recurring-payments"
TODAY = "2026-10-24T12:00:00+03:00"


def body(due: str, **kw: object) -> dict:
    return {
        "title": "Сервер (VPS)",
        "amount": "120",
        "currency": "USD",
        "next_due_date": due,
        "periodicity": "monthly",
    } | kw


async def _create(client: AsyncClient, h: dict, due: str, **kw: object) -> dict:
    r = await client.post(R, json=body(due, **kw), headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _dues(db: AsyncSession, rp_id: int) -> list[date]:
    rows = await db.scalars(
        select(PaymentOccurrence.due_date)
        .where(PaymentOccurrence.recurring_payment_id == rp_id)
        .order_by(PaymentOccurrence.period_index)
    )
    return list(rows)


async def test_create_makes_two_future_periods(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    rp = await _create(client, h, "2026-10-31")
    assert rp["amount"] == "120.00" and rp["anchor_day"] == 31 and rp["status"] == "active"
    assert rp["first_due_date"] == "2026-10-31" and rp["next_due_date"] == "2026-10-31"
    assert rp["created_by"]["login"] == "admin" and rp["stopped_at"] is None
    assert rp["created_at"].endswith("+03:00")
    assert await _dues(db, rp["id"]) == [date(2026, 10, 31), date(2026, 11, 30)]


async def test_due_today_counts_as_current_plus_two_future(
    client: AsyncClient, db: AsyncSession
) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    rp = await _create(client, h, "2026-10-24")
    assert await _dues(db, rp["id"]) == [date(2026, 10, 24), date(2026, 11, 24), date(2026, 12, 24)]


async def test_rerun_does_not_duplicate_and_catches_up(
    client: AsyncClient, db: AsyncSession
) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    rp = await _create(client, h, "2026-10-31")
    c = await get_clock(db)
    assert await ensure_all(db, c) == 0
    assert await ensure_all(db, c) == 0
    await db.commit()
    assert len(await _dues(db, rp["id"])) == 2

    # "downtime": the clock moves 70 days ahead → all missed periods appear, then 2 future
    await clock.set_offset_days(db, 70)
    await db.commit()
    c = await get_clock(db)
    assert c.today() == date(2027, 1, 2)
    assert await ensure_all(db, c) == 3
    await db.commit()
    assert await _dues(db, rp["id"]) == [
        date(2026, 10, 31),
        date(2026, 11, 30),
        date(2026, 12, 31),
        date(2027, 1, 31),
        date(2027, 2, 28),
    ]
    r = (await client.get(R, headers=h)).json()
    assert r["items"][0]["next_due_date"] == "2027-01-31"


async def test_validation(client: AsyncClient) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    cases = [
        (body("2026-10-23"), "next_due_date"),
        (body("2026-11-01", amount="0"), "amount"),
        (body("2026-11-01", amount="1.999"), "amount"),
        (body("2026-11-01", title="   "), "title"),
        (body("2026-11-01", currency="GBP"), "currency"),
        (body("2026-11-01", periodicity="yearly"), "periodicity"),
        (body("2026-11-01", periodicity="every_n_days"), "interval_days"),
        (body("2026-11-01", periodicity="every_n_days", interval_days=0), "interval_days"),
        (body("2026-11-01", periodicity="every_n_days", interval_days=366), "interval_days"),
        (body("2026-11-01", periodicity="weekly", interval_days=7), "interval_days"),
        (body("2026-11-40"), "next_due_date"),
    ]
    for payload, field in cases:
        r = await client.post(R, json=payload, headers=h)
        assert r.status_code == 422, payload
        assert [d["field"] for d in r.json()["error"]["details"]] == [field], r.text
    r = await client.post(R, json=body("2026-11-01") | {"amount": 120.5}, headers=h)
    assert r.status_code == 422
    r = await client.post(R, json=body("2026-11-01") | {"status": "stopped"}, headers=h)
    assert r.json()["error"]["code"] == "field_not_allowed"


async def test_stop_keeps_history_and_paid_future(client: AsyncClient, db: AsyncSession) -> None:
    freeze("2026-10-05T12:00:00+03:00")
    h = bearer(await login(client, *ADMIN))
    rp = await _create(client, h, "2026-10-05", amount="85000", currency="RUB")
    await clock.set_offset_days(db, 46)  # business day 2026-11-20; sessions are unaffected
    await db.commit()
    await ensure_all(db, await get_clock(db))
    await db.commit()
    # periods: 10-05, 11-05 (≤ today), 12-05, 01-05 (future); pay 10-05 and the future 12-05
    await db.execute(
        update(PaymentOccurrence)
        .where(PaymentOccurrence.due_date.in_([date(2026, 10, 5), date(2026, 12, 5)]))
        .values(status="paid", paid_date=date(2026, 10, 5))
    )
    await db.commit()

    r = await client.delete(f"{R}/{rp['id']}", headers=h)
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "stopped" and out["next_due_date"] is None
    assert out["stopped_at"] is not None and out["version"] == 2
    assert await _dues(db, rp["id"]) == [date(2026, 10, 5), date(2026, 11, 5), date(2026, 12, 5)]

    again = await client.delete(f"{R}/{rp['id']}", headers=h)
    assert again.status_code == 200 and again.json() == out

    await ensure_all(db, await get_clock(db))
    await db.commit()
    assert len(await _dues(db, rp["id"])) == 3  # no new periods after stop
    stops = await db.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "recurring.stop")
    )
    assert stops == 1


async def test_stop_unknown_404(client: AsyncClient) -> None:
    h = bearer(await login(client, *ADMIN))
    r = await client.delete(f"{R}/12345", headers=h)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_list_filters_and_pagination(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    a = await _create(client, h, "2026-11-01", title="A")
    await _create(client, h, "2026-11-02", title="B")
    await client.delete(f"{R}/{a['id']}", headers=h)
    page = (await client.get(R, headers=h, params={"limit": 1})).json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["items"][0]["title"] == "B"
    stopped = (await client.get(R, headers=h, params={"status": "stopped"})).json()
    assert [i["title"] for i in stopped["items"]] == ["A"]
    assert (await client.get(R, headers=h, params={"status": "x"})).status_code == 422
    assert await db.scalar(select(func.count()).select_from(RecurringPayment)) == 2
    audit = await db.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "recurring.create")
    )
    assert audit == 2
