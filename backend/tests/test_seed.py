"""Seed (DOMAIN §15) on different days of the month; idempotent."""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import PaymentOccurrence
from app.seed import DEMO_USERS, seed
from tests.helpers import ADMIN, bearer, freeze, login


async def _by_title(client: AsyncClient, h: dict) -> dict[str, list[dict]]:
    items = (
        await client.get(
            "/api/v1/payment-occurrences", headers=h, params={"sort": "due_date", "limit": 200}
        )
    ).json()["items"]
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item["title"], []).append(item)
    return grouped


@pytest.mark.parametrize(
    "moment",
    [
        "2026-10-24T12:00:00+03:00",
        "2026-11-01T12:00:00+03:00",
        "2026-11-05T12:00:00+03:00",
        "2026-12-31T12:00:00+03:00",
        "2028-02-29T12:00:00+03:00",
        "2027-03-30T12:00:00+03:00",
    ],
)
async def test_seed_matches_domain(client: AsyncClient, db: AsyncSession, moment: str) -> None:
    freeze(moment)
    today = date.fromisoformat(moment[:10])
    result = await seed(db)
    assert sorted(result.users) == sorted(DEMO_USERS)
    assert len(result.payments) == 4

    for login_name, password in DEMO_USERS.items():
        await login(client, login_name, password)
    h = bearer(await login(client, *ADMIN))
    by = await _by_title(client, h)

    rent = by["Аренда офиса"]
    past = [o for o in rent if date.fromisoformat(o["due_date"]) < today]
    assert [o["state"] for o in past] == ["paid", "paid_late", "overdue"]
    assert all(o["due_date"].endswith("-05") and o["amount"] == "85000.00" for o in rent)
    assert all(o["reminder_sent_at"] for o in past)

    server = by["Сервер (VPS)"]
    assert [o["state"] for o in server[:2]] == ["paid", "overdue"]
    assert all(o["currency"] == "USD" for o in server)
    last_days = [date.fromisoformat(o["due_date"]) for o in server]
    assert all((d + timedelta(days=1)).day == 1 for d in last_days)  # last day of the month

    sub = by["Подписка на сервис"]
    assert sub[0]["state"] == "paid" and sub[0]["amount"] == "15.99"
    upcoming = [o for o in sub if o["status"] == "unpaid"]
    assert 0 <= (date.fromisoformat(upcoming[0]["due_date"]) - today).days <= 3
    assert upcoming[0]["reminder_sent_at"] is None

    assert [a["login"] for a in rent[0]["assignees"]] == ["anna"]
    assert [a["login"] for a in server[0]["assignees"]] == ["anna", "boris"]
    assert sub[0]["assign_all"] is True

    hosting = by["Старый хостинг"]
    assert len(hosting) == 3 and all(o["state"] == "paid" for o in hosting)
    assert all(o["recurring_status"] == "stopped" for o in hosting)

    overdue = (
        await client.get("/api/v1/payment-occurrences", headers=h, params={"overdue": "true"})
    ).json()
    assert overdue["total"] == 2


async def test_seed_is_idempotent(db: AsyncSession) -> None:
    freeze("2026-10-24T12:00:00+03:00")
    await seed(db)
    count = await db.scalar(select(func.count()).select_from(PaymentOccurrence))
    again = await seed(db)
    assert again.users == [] and again.payments == []
    assert await db.scalar(select(func.count()).select_from(PaymentOccurrence)) == count
