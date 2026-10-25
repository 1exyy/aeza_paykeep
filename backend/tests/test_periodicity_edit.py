"""Periodicity, payment editing, one-time completion, user Telegram."""

from datetime import date

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.telegram import mention
from app.core.clock import get_clock
from app.models.audit_event import AuditEvent
from app.models.payment import PaymentOccurrence
from app.models.user import User
from app.services import telegram_link
from app.services.schedule import Schedule
from app.services.telegram_paid import press_paid
from tests.helpers import ADMIN, bearer, create_user, freeze, login
from tests.test_contract import check

R = "/api/v1/recurring-payments"
OCC = "/api/v1/payment-occurrences"
U = "/api/v1/users"
TODAY = "2026-10-24T12:00:00+03:00"


def _body(due: str = "2026-10-30", **kw: object) -> dict:
    return {
        "title": "Хостинг",
        "amount": "100",
        "currency": "RUB",
        "next_due_date": due,
        "periodicity": "monthly",
    } | kw


async def _dues(db: AsyncSession, rp_id: int) -> list[tuple[int, date, str]]:
    rows = await db.execute(
        select(PaymentOccurrence.period_index, PaymentOccurrence.due_date, PaymentOccurrence.status)
        .where(PaymentOccurrence.recurring_payment_id == rp_id)
        .order_by(PaymentOccurrence.period_index)
    )
    db.expire_all()
    return [tuple(r) for r in rows.all()]  # type: ignore[misc]


# ---------- schedule ----------


def test_schedule_steps_and_lead() -> None:
    d = date(2026, 10, 30)
    assert Schedule(d, 30, "daily").due(3) == date(2026, 11, 2)
    assert Schedule(d, 30, "weekly").due(2) == date(2026, 11, 13)
    assert Schedule(d, 30, "every_n_days", 10).due(1) == date(2026, 11, 9)
    assert Schedule(d, 30, "monthly").due(4) == date(2027, 2, 28)
    once = Schedule(d, 30, "once")
    assert once.has(0) and not once.has(1)
    assert list(once.horizon(date(2027, 1, 1))) == [0]
    assert Schedule(d, 30, "daily").reminder_lead(3) == 0
    assert Schedule(d, 30, "every_n_days", 2).reminder_lead(3) == 1
    assert Schedule(d, 30, "weekly").reminder_lead(3) == 3
    assert Schedule(d, 30, "monthly").reminder_lead(3) == 3


# ---------- create ----------


async def test_create_each_periodicity(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    r = await client.post(R, json=_body("2026-10-24", periodicity="daily"), headers=h)
    rp = check("/recurring-payments", "post", r)
    assert rp["periodicity"] == "daily" and rp["interval_days"] is None
    assert [d for _, d, _ in await _dues(db, rp["id"])] == [
        date(2026, 10, 24),
        date(2026, 10, 25),
        date(2026, 10, 26),
    ]
    r = await client.post(R, json=_body(periodicity="every_n_days", interval_days=10), headers=h)
    rp = r.json()
    assert rp["interval_days"] == 10
    assert [d for _, d, _ in await _dues(db, rp["id"])] == [
        date(2026, 10, 30),
        date(2026, 11, 9),
    ]
    r = await client.post(R, json=_body(periodicity="once"), headers=h)
    rp = r.json()
    assert rp["completed"] is False
    assert len(await _dues(db, rp["id"])) == 1
    got = check("/recurring-payments/{id}", "get", await client.get(f"{R}/{rp['id']}", headers=h))
    assert got["id"] == rp["id"] and got["periodicity"] == "once"
    assert (await client.get(f"{R}/9999", headers=h)).status_code == 404


# ---------- edit ----------


async def test_edit_content_only_touches_future_unpaid(
    client: AsyncClient, db: AsyncSession
) -> None:
    freeze("2026-09-20T12:00:00+03:00")
    h = bearer(await login(client, *ADMIN))
    rp = (await client.post(R, json=_body("2026-09-25"), headers=h)).json()
    freeze(TODAY)  # September period is in the past now
    client.cookies.clear()
    h = bearer(await login(client, *ADMIN))
    r = await client.patch(
        f"{R}/{rp['id']}",
        json={"title": "Хостинг Pro", "amount": "150.50", "expected_version": rp["version"]},
        headers=h,
    )
    body = check("/recurring-payments/{id}", "patch", r)
    assert body["title"] == "Хостинг Pro" and body["amount"] == "150.50"
    assert body["version"] == rp["version"] + 1
    rows = (
        await db.execute(
            select(PaymentOccurrence.due_date, PaymentOccurrence.title, PaymentOccurrence.amount)
            .where(PaymentOccurrence.recurring_payment_id == rp["id"])
            .order_by(PaymentOccurrence.period_index)
        )
    ).all()
    assert rows[0].title == "Хостинг"  # past period keeps history
    assert all(row.title == "Хостинг Pro" for row in rows if row.due_date >= date(2026, 10, 24))
    event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "recurring.update"))
    assert event is not None and event.details["title"] == "Хостинг Pro"


async def test_edit_schedule_rebuilds_unpaid(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    rp = (await client.post(R, json=_body("2026-10-24"), headers=h)).json()
    first = (await _dues(db, rp["id"]))[0]
    occ_id = await db.scalar(
        select(PaymentOccurrence.id).where(
            PaymentOccurrence.recurring_payment_id == rp["id"],
            PaymentOccurrence.period_index == first[0],
        )
    )
    r = await client.patch(
        f"{OCC}/{occ_id}", json={"status": "paid", "paid_date": "2026-10-24"}, headers=h
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"{R}/{rp['id']}",
        json={"periodicity": "weekly", "next_due_date": "2026-11-02"},
        headers=h,
    )
    body = r.json()
    assert r.status_code == 200 and body["periodicity"] == "weekly"
    dues = await _dues(db, rp["id"])
    assert dues[0] == (0, date(2026, 10, 24), "paid")  # paid history stays
    assert [(i, d) for i, d, _ in dues[1:]] == [(1, date(2026, 11, 2)), (2, date(2026, 11, 9))]

    bad = await client.patch(f"{R}/{rp['id']}", json={"periodicity": "every_n_days"}, headers=h)
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "interval_days"
    past = await client.patch(f"{R}/{rp['id']}", json={"next_due_date": "2026-10-01"}, headers=h)
    assert past.status_code == 422


async def test_stopped_payment_is_not_editable(client: AsyncClient) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    rp = (await client.post(R, json=_body(), headers=h)).json()
    await client.delete(f"{R}/{rp['id']}", headers=h)
    r = await client.patch(f"{R}/{rp['id']}", json={"title": "x"}, headers=h)
    assert r.status_code == 422


async def test_user_cannot_edit(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    rp = (await client.post(R, json=_body(), headers=h)).json()
    await create_user(db, "anna", "anna-password")
    await db.commit()
    client.cookies.clear()
    hu = bearer(await login(client, "anna", "anna-password"))
    assert (
        await client.patch(f"{R}/{rp['id']}", json={"title": "x"}, headers=hu)
    ).status_code == 403
    assert (await client.get(f"{R}/{rp['id']}", headers=hu)).status_code == 200


# ---------- one-time completion ----------


async def test_once_completes_and_reopens(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    rp = (await client.post(R, json=_body(periodicity="once"), headers=h)).json()
    occ_id = await db.scalar(
        select(PaymentOccurrence.id).where(PaymentOccurrence.recurring_payment_id == rp["id"])
    )
    r = await client.patch(
        f"{OCC}/{occ_id}", json={"status": "paid", "paid_date": "2026-10-24"}, headers=h
    )
    assert r.status_code == 200
    got = (await client.get(f"{R}/{rp['id']}", headers=h)).json()
    assert got["status"] == "stopped" and got["completed"] is True
    await client.patch(f"{OCC}/{occ_id}", json={"status": "unpaid"}, headers=h)
    got = (await client.get(f"{R}/{rp['id']}", headers=h)).json()
    assert got["status"] == "active" and got["completed"] is False


async def test_once_completes_from_telegram_button(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    rp = (await client.post(R, json=_body(periodicity="once"), headers=h)).json()
    user = await create_user(db, "anna", "anna-password")
    user.telegram_user_id = 111
    await db.commit()
    occ_id = await db.scalar(
        select(PaymentOccurrence.id).where(PaymentOccurrence.recurring_payment_id == rp["id"])
    )
    assert occ_id is not None
    outcome = await press_paid(db, 111, occ_id)
    assert outcome.paid_line
    got = (await client.get(f"{R}/{rp['id']}", headers=h)).json()
    assert got["completed"] is True


# ---------- user Telegram ----------


async def test_admin_sets_user_telegram(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    r = await client.post(
        U, json={"login": "anna", "password": "anna-password", "telegram": "@Anna_TG"}, headers=h
    )
    anna = check("/users", "post", r)
    assert anna["telegram_username"] == "anna_tg" and anna["telegram_user_id"] is None
    assert anna["telegram_linked"] is False

    r = await client.post(
        U, json={"login": "boris", "password": "boris-password", "telegram": "222"}, headers=h
    )
    boris = r.json()
    assert boris["telegram_user_id"] == 222 and boris["telegram_linked"] is True

    dup = await client.patch(f"{U}/{anna['id']}", json={"telegram": "222"}, headers=h)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "telegram_already_linked"
    dup = await client.post(
        U, json={"login": "carl", "password": "carl-password", "telegram": "@anna_tg"}, headers=h
    )
    assert dup.status_code == 409
    bad = await client.patch(f"{U}/{anna['id']}", json={"telegram": "@ab"}, headers=h)
    assert bad.status_code == 422

    r = await client.patch(f"{U}/{boris['id']}", json={"telegram": None}, headers=h)
    assert r.json()["telegram_user_id"] is None and r.json()["telegram_username"] is None
    same = await client.patch(f"{U}/{boris['id']}", json={"telegram": ""}, headers=h)
    assert same.json()["updated_at"] == r.json()["updated_at"]


async def test_username_binds_on_first_contact(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    anna = (
        await client.post(
            U,
            json={"login": "anna", "password": "anna-password", "telegram": "@anna_tg"},
            headers=h,
        )
    ).json()
    user = await db.get(User, anna["id"])
    assert user is not None
    assert mention(user) == "@anna_tg"

    clock = await get_clock(db)
    assert await telegram_link.bind_on_contact(db, clock, 555, "someone_else") == []
    [bound] = await telegram_link.bind_on_contact(db, clock, 777, "Anna_TG")
    await db.commit()
    assert bound.id == anna["id"] and bound.telegram_user_id == 777
    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "telegram.link", AuditEvent.source == "telegram"
        )
    )
    assert event is not None
    [again] = await telegram_link.bind_on_contact(db, clock, 777, "anna_tg")
    assert again.id == anna["id"]


# ---------- filters and history ----------


async def test_filter_by_assignee(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    anna = await create_user(db, "anna", "anna-password")
    boris = await create_user(db, "boris", "boris-password")
    await db.commit()
    h = bearer(await login(client, *ADMIN))
    mine = (await client.post(R, json=_body(assignee_ids=[anna.id]), headers=h)).json()
    everyone = (await client.post(R, json=_body(title="Все", assign_all=True), headers=h)).json()
    await client.post(R, json=_body(title="Борис", assignee_ids=[boris.id]), headers=h)

    r = await client.get(OCC, params={"assignee_id": anna.id, "limit": 100}, headers=h)
    found = {
        item["recurring_payment_id"] for item in check("/payment-occurrences", "get", r)["items"]
    }
    assert found == {mine["id"], everyone["id"]}
    r = await client.get(
        OCC, params={"assignee_id": anna.id, "status": "unpaid", "overdue": "false"}, headers=h
    )
    assert r.status_code == 200 and r.json()["total"] > 0


async def test_audit_history_of_payment(client: AsyncClient, db: AsyncSession) -> None:
    freeze(TODAY)
    h = bearer(await login(client, *ADMIN))
    rp = (await client.post(R, json=_body("2026-10-24"), headers=h)).json()
    other = (await client.post(R, json=_body(title="Другой"), headers=h)).json()
    occ_id = await db.scalar(
        select(PaymentOccurrence.id).where(
            PaymentOccurrence.recurring_payment_id == rp["id"],
            PaymentOccurrence.due_date == date(2026, 10, 24),
        )
    )
    await client.patch(
        f"{OCC}/{occ_id}", json={"status": "paid", "paid_date": "2026-10-24"}, headers=h
    )
    await client.patch(f"{R}/{rp['id']}", json={"amount": "200"}, headers=h)
    r = await client.get("/api/v1/audit-log", params={"recurring_payment_id": rp["id"]}, headers=h)
    actions = [e["action"] for e in check("/audit-log", "get", r)["items"]]
    assert actions == ["recurring.update", "occurrence.mark_paid", "recurring.create"]
    r = await client.get(
        "/api/v1/audit-log", params={"recurring_payment_id": other["id"]}, headers=h
    )
    assert [e["action"] for e in r.json()["items"]] == ["recurring.create"]
