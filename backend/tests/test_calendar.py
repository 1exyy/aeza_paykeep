"""GET /calendar and GET /budget (DOMAIN §8)."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.worker.jobs import run_cycle
from tests.helpers import (
    ADMIN,
    bearer,
    create_recurring,
    create_user,
    freeze,
    login,
    set_business_today,
)
from tests.test_contract import check

CAL = "/api/v1/calendar"
BUD = "/api/v1/budget"


@pytest.fixture
async def world(client: AsyncClient, db: AsyncSession) -> dict:
    """Today 2026-01-10. RUB 1000 and USD 10 on the 31st, EUR 20 on the 15th."""
    freeze("2026-01-10T12:00:00+03:00")
    admin = bearer(await login(client, *ADMIN))
    await create_user(db, "anna", "anna-password")
    anna = bearer(await login(client, "anna", "anna-password"))
    client.cookies.clear()
    rub = await create_recurring(
        client, admin, "2026-01-31", title="Аренда", amount="1000", currency="RUB"
    )
    usd = await create_recurring(
        client, admin, "2026-01-31", title="Сервер", amount="10", currency="USD"
    )
    eur = await create_recurring(
        client, admin, "2026-01-15", title="Подписка", amount="20", currency="EUR"
    )
    return {"admin": admin, "anna": anna, "rub": rub, "usd": usd, "eur": eur}


async def _calendar(client: AsyncClient, h: dict, month: str | None = None) -> dict:
    params = {"month": month} if month else {}
    return check("/calendar", "get", await client.get(CAL, headers=h, params=params))


def _totals(rows: list[dict]) -> dict[str, tuple]:
    return {
        t["currency"]: (t["total"], t["paid"], t["unpaid"], t["overdue"], t["count"]) for t in rows
    }


async def test_several_currencies_on_one_day(client: AsyncClient, world: dict) -> None:
    body = await _calendar(client, world["anna"])  # default: current month
    assert body["month"] == "2026-01" and body["today"] == "2026-01-10"
    assert [d["date"] for d in body["days"]] == ["2026-01-15", "2026-01-31"]
    day31 = body["days"][1]
    assert [(i["currency"], i["title"]) for i in day31["items"]] == [
        ("RUB", "Аренда"),
        ("USD", "Сервер"),
    ]
    assert all(
        i["occurrence_id"] and i["state"] == "upcoming" and not i["is_projected"]
        for i in day31["items"]
    )
    assert _totals(day31["totals"]) == {
        "RUB": ("1000.00", "0.00", "1000.00", "0.00", 1),
        "USD": ("10.00", "0.00", "10.00", "0.00", 1),
        "EUR": ("0.00", "0.00", "0.00", "0.00", 0),
    }
    assert _totals(body["month_totals"])["EUR"] == ("20.00", "0.00", "20.00", "0.00", 1)


async def test_february_and_projected_months(client: AsyncClient, world: dict) -> None:
    feb = await _calendar(client, world["anna"], "2026-02")
    assert [d["date"] for d in feb["days"]] == ["2026-02-15", "2026-02-28"]  # the 31st → 28.02
    assert all(not i["is_projected"] for d in feb["days"] for i in d["items"])  # created already

    apr = await _calendar(client, world["anna"], "2026-04")  # beyond the 2-future horizon
    assert [d["date"] for d in apr["days"]] == ["2026-04-15", "2026-04-30"]
    items = [i for d in apr["days"] for i in d["items"]]
    assert all(
        i["is_projected"] and i["occurrence_id"] is None and i["state"] is None for i in items
    )
    assert _totals(apr["month_totals"])["RUB"] == ("1000.00", "0.00", "1000.00", "0.00", 1)

    feb28 = await _calendar(client, world["anna"], "2028-02")
    assert "2028-02-29" in [d["date"] for d in feb28["days"]]  # leap year


async def test_paid_and_overdue_in_day_totals(
    client: AsyncClient, db: AsyncSession, world: dict
) -> None:
    jan = (await _calendar(client, world["anna"], "2026-01"))["days"]
    rub_id = jan[1]["items"][0]["occurrence_id"]
    await client.patch(
        f"/api/v1/payment-occurrences/{rub_id}",
        json={"status": "paid", "paid_date": "2026-01-10"},
        headers=world["anna"],
    )
    await set_business_today(db, date(2026, 2, 1))
    jan = await _calendar(client, world["anna"], "2026-01")
    assert [i["state"] for i in jan["days"][1]["items"]] == ["paid", "overdue"]
    assert _totals(jan["month_totals"]) == {
        "RUB": ("1000.00", "1000.00", "0.00", "0.00", 1),
        "USD": ("10.00", "0.00", "10.00", "10.00", 1),
        "EUR": ("20.00", "0.00", "20.00", "20.00", 1),
    }


async def test_budget_year_and_month(client: AsyncClient, world: dict) -> None:
    jan = (await _calendar(client, world["anna"], "2026-01"))["days"]
    await client.patch(
        f"/api/v1/payment-occurrences/{jan[1]['items'][0]['occurrence_id']}",
        json={"status": "paid", "paid_date": "2026-01-10"},
        headers=world["anna"],
    )
    # started mid-year: July..December only
    await create_recurring(
        client, world["admin"], "2026-07-05", title="Склад", amount="500", currency="RUB"
    )
    body = check(
        "/budget",
        "get",
        await client.get(BUD, headers=world["anna"], params={"period": "year", "year": 2026}),
    )
    assert body["from"] == "2026-01-01" and body["to"] == "2026-12-31" and body["period"] == "year"
    rub, usd, eur = body["currencies"]
    # RUB: 12 × 1000 (1 paid, 1 unpaid existing, 10 projected) + 6 × 500 (2 existing, 4 projected)
    assert rub == {
        "currency": "RUB",
        "planned": "15000.00",
        "existing_paid": "1000.00",
        "existing_unpaid": "2000.00",
        "projected": "12000.00",
    }
    assert usd["planned"] == "120.00" and eur["planned"] == "240.00"
    for t in body["currencies"]:
        parts = sum(Decimal(t[k]) for k in ("existing_paid", "existing_unpaid", "projected"))
        assert Decimal(t["planned"]) == parts

    month = check(
        "/budget",
        "get",
        await client.get(
            BUD, headers=world["anna"], params={"period": "month", "year": 2026, "month": 2}
        ),
    )
    assert month["from"] == "2026-02-01" and month["to"] == "2026-02-28"
    assert [t["planned"] for t in month["currencies"]] == ["1000.00", "10.00", "20.00"]
    # fmt: skip


async def test_stopped_mid_year_counts_only_existing(
    client: AsyncClient, db: AsyncSession, world: dict
) -> None:
    hosting = await create_recurring(
        client, world["admin"], "2026-01-20", title="Хостинг", amount="100", currency="USD"
    )
    await set_business_today(db, date(2026, 5, 25))
    async with get_sessionmaker()() as s:
        await run_cycle(s, channels={})
    await client.delete(f"/api/v1/recurring-payments/{hosting['id']}", headers=world["admin"])

    body = (
        await client.get(BUD, headers=world["anna"], params={"period": "year", "year": 2026})
    ).json()
    usd = body["currencies"][1]
    # hosting: 5 existing periods (Jan–May) = 500, nothing projected after the stop;
    # server: 6 existing (Jan–Jun) = 60 + 6 projected (Jul–Dec) = 60
    assert usd["existing_unpaid"] == "560.00" and usd["projected"] == "60.00"
    assert usd["planned"] == "620.00"
    june = await _calendar(client, world["anna"], "2026-06")
    assert "Хостинг" not in [i["title"] for d in june["days"] for i in d["items"]]
    jan = await _calendar(client, world["anna"], "2026-01")
    assert "Хостинг" in [i["title"] for d in jan["days"] for i in d["items"]]


async def test_empty_month_has_three_zero_currencies(client: AsyncClient, db: AsyncSession) -> None:
    freeze("2026-01-10T12:00:00+03:00")
    h = bearer(await login(client, *ADMIN))
    body = await _calendar(client, h, "2026-03")
    assert body["days"] == []
    assert [t["currency"] for t in body["month_totals"]] == ["RUB", "USD", "EUR"]
    budget = (await client.get(BUD, headers=h, params={"period": "year", "year": 2026})).json()
    assert all(t["planned"] == "0.00" for t in budget["currencies"])


@pytest.mark.parametrize(
    ("url", "params", "field"),
    [
        (CAL, {"month": "2026-13"}, "month"),
        (CAL, {"month": "2026-1"}, "month"),
        (CAL, {"month": "1999-12"}, "month"),
        (BUD, {"period": "month", "year": 2026}, "month"),
        (BUD, {"period": "month", "year": 2026, "month": 13}, "month"),
        (BUD, {"period": "year", "year": 1999}, "year"),
        (BUD, {"period": "week", "year": 2026}, "period"),
        (BUD, {"period": "year"}, "year"),
    ],
)
async def test_validation(client: AsyncClient, url: str, params: dict, field: str) -> None:
    h = bearer(await login(client, *ADMIN))
    r = await client.get(url, headers=h, params=params)
    path = "/calendar" if url == CAL else "/budget"
    body = check(path, "get", r)
    assert r.status_code == 422 and field in [d["field"] for d in body["error"]["details"]]
