"""PATCH rules of DOMAIN §4, computed state and the period list."""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent
from tests.helpers import (
    ADMIN,
    bearer,
    create_recurring,
    create_user,
    freeze,
    login,
    set_business_today,
)

OCC = "/api/v1/payment-occurrences"


@pytest.fixture
async def setup(client: AsyncClient, db: AsyncSession) -> dict:
    """Real date 2026-11-01; one USD payment due 2026-11-10 → periods 11-10 and 12-10."""
    freeze("2026-11-01T12:00:00+03:00")
    admin = bearer(await login(client, *ADMIN))
    rp = await create_recurring(client, admin, "2026-11-10")
    await create_user(db, "anna", "anna-password")
    anna = bearer(await login(client, "anna", "anna-password"))
    client.cookies.clear()
    items = (await client.get(OCC, headers=anna, params={"sort": "due_date"})).json()["items"]
    return {"admin": admin, "anna": anna, "rp": rp, "first": items[0], "second": items[1]}


async def _patch(client: AsyncClient, h: dict, occ_id: int, body: dict):
    return await client.patch(f"{OCC}/{occ_id}", json=body, headers=h)


async def test_initial_state(setup: dict) -> None:
    first = setup["first"]
    assert first["due_date"] == "2026-11-10" and first["status"] == "unpaid"
    assert first["paid_date"] is None and first["state"] == "upcoming"
    assert first["is_overdue"] is False and first["is_paid_late"] is False
    assert first["amount"] == "120.00" and first["recurring_status"] == "active"
    assert first["paid_by"] is None and first["paid_via"] is None and first["version"] == 1


async def test_overdue_starts_next_day(client: AsyncClient, db: AsyncSession, setup: dict) -> None:
    occ_id = setup["first"]["id"]
    await set_business_today(db, date(2026, 11, 10))
    r = (await client.get(f"{OCC}/{occ_id}", headers=setup["anna"])).json()
    assert r["state"] == "upcoming" and r["is_overdue"] is False
    await set_business_today(db, date(2026, 11, 11))
    r = (await client.get(f"{OCC}/{occ_id}", headers=setup["anna"])).json()
    assert r["state"] == "overdue" and r["is_overdue"] is True


async def test_paid_on_due_date_is_on_time(
    client: AsyncClient, db: AsyncSession, setup: dict
) -> None:
    await set_business_today(db, date(2026, 11, 10))
    r = await _patch(
        client, setup["anna"], setup["first"]["id"], {"status": "paid", "paid_date": "2026-11-10"}
    )
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "paid" and out["paid_date"] == "2026-11-10"
    assert out["state"] == "paid" and out["is_paid_late"] is False and out["is_overdue"] is False
    assert out["paid_by"]["login"] == "anna" and out["paid_via"] == "web" and out["version"] == 2


async def test_late_payment_and_date_fix_removes_lateness(
    client: AsyncClient, db: AsyncSession, setup: dict
) -> None:
    occ_id = setup["first"]["id"]
    await set_business_today(db, date(2026, 11, 12))
    r = await _patch(client, setup["anna"], occ_id, {"status": "paid", "paid_date": "2026-11-12"})
    assert r.json()["state"] == "paid_late" and r.json()["is_paid_late"] is True
    r = await _patch(
        client, setup["anna"], occ_id, {"paid_date": "2026-11-09", "expected_version": 2}
    )
    out = r.json()
    assert r.status_code == 200
    assert out["state"] == "paid" and out["is_paid_late"] is False
    assert out["due_date"] == "2026-11-10" and out["paid_date"] == "2026-11-09"
    # status=paid on an already paid period just changes the date
    r = await _patch(client, setup["anna"], occ_id, {"status": "paid", "paid_date": "2026-11-11"})
    assert r.json()["paid_date"] == "2026-11-11" and r.json()["state"] == "paid_late"


async def test_unmark_clears_date_and_payer(
    client: AsyncClient, db: AsyncSession, setup: dict
) -> None:
    occ_id = setup["first"]["id"]
    await set_business_today(db, date(2026, 11, 12))
    await _patch(client, setup["anna"], occ_id, {"status": "paid", "paid_date": "2026-11-12"})
    r = await _patch(client, setup["admin"], occ_id, {"status": "unpaid", "paid_date": None})
    out = r.json()
    assert r.status_code == 200
    assert out["status"] == "unpaid" and out["paid_date"] is None and out["paid_by"] is None
    assert out["paid_via"] is None and out["state"] == "overdue"
    r = await _patch(client, setup["admin"], occ_id, {"status": "unpaid"})
    assert r.status_code == 200 and r.json()["version"] == out["version"]  # no-op


async def test_date_only_on_unpaid_is_409(setup: dict, client: AsyncClient) -> None:
    r = await _patch(client, setup["anna"], setup["first"]["id"], {"paid_date": "2026-11-01"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_paid"


@pytest.mark.parametrize(
    ("body", "code", "field"),
    [
        ({"status": "paid"}, "validation_error", "paid_date"),
        ({"status": "paid", "paid_date": None}, "validation_error", "paid_date"),
        ({"status": "unpaid", "paid_date": "2026-11-01"}, "validation_error", "paid_date"),
        ({"paid_date": None}, "validation_error", "paid_date"),
        ({}, "validation_error", "body"),
        ({"expected_version": 1}, "validation_error", "body"),
        ({"status": "paid", "paid_date": "2026-11-02"}, "validation_error", "paid_date"),
        ({"status": "paid", "paid_date": "2025-11-08"}, "validation_error", "paid_date"),
        ({"status": "done"}, "validation_error", "status"),
        ({"due_date": "2026-12-01"}, "field_not_allowed", "due_date"),
        (
            {"status": "paid", "paid_date": "2026-11-01", "amount": "1"},
            "field_not_allowed",
            "amount",
        ),
    ],
)
async def test_invalid_patches(
    client: AsyncClient, setup: dict, body: dict, code: str, field: str
) -> None:
    r = await _patch(client, setup["anna"], setup["first"]["id"], body)
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == code
    assert field in [d["field"] for d in err["details"]]


async def test_early_payment_allowed_and_limits(client: AsyncClient, setup: dict) -> None:
    occ_id = setup["second"]["id"]  # due 2026-12-10, today 2026-11-01
    r = await _patch(client, setup["anna"], occ_id, {"status": "paid", "paid_date": "2026-11-01"})
    assert r.status_code == 200 and r.json()["state"] == "paid"
    r = await _patch(client, setup["anna"], occ_id, {"paid_date": "2025-12-09"})
    assert r.status_code == 200  # exactly due − 366 days
    r = await _patch(client, setup["anna"], occ_id, {"paid_date": "2025-12-08"})
    assert r.status_code == 422


async def test_one_period_does_not_touch_another(client: AsyncClient, setup: dict) -> None:
    await _patch(
        client, setup["anna"], setup["first"]["id"], {"status": "paid", "paid_date": "2026-11-01"}
    )
    second = (await client.get(f"{OCC}/{setup['second']['id']}", headers=setup["anna"])).json()
    assert second == setup["second"]


async def test_version_conflict_and_404(client: AsyncClient, setup: dict) -> None:
    occ_id = setup["first"]["id"]
    body = {"status": "paid", "paid_date": "2026-11-01", "expected_version": 1}
    assert (await _patch(client, setup["anna"], occ_id, body)).status_code == 200
    r = await _patch(client, setup["admin"], occ_id, {"status": "unpaid", "expected_version": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "version_conflict"
    assert (await client.get(f"{OCC}/99999", headers=setup["anna"])).status_code == 404
    r = await _patch(client, setup["anna"], 99999, {"status": "unpaid"})
    assert r.status_code == 404


async def test_audit_events(client: AsyncClient, db: AsyncSession, setup: dict) -> None:
    occ_id = setup["first"]["id"]
    await _patch(client, setup["anna"], occ_id, {"status": "paid", "paid_date": "2026-11-01"})
    await _patch(client, setup["anna"], occ_id, {"paid_date": "2026-10-31"})
    await _patch(client, setup["anna"], occ_id, {"status": "unpaid"})
    stmt = select(AuditEvent).where(AuditEvent.action.like("occurrence.%")).order_by(AuditEvent.id)
    events = (await db.scalars(stmt)).all()
    assert [(e.action, e.actor_login, e.object_id) for e in events] == [
        ("occurrence.mark_paid", "anna", occ_id),
        ("occurrence.change_paid_date", "anna", occ_id),
        ("occurrence.mark_unpaid", "anna", occ_id),
    ]
    assert events[1].details["paid_date_from"] == "2026-11-01"
    assert events[1].details["paid_date_to"] == "2026-10-31"


async def test_stopped_payment_history_still_editable(
    client: AsyncClient, db: AsyncSession, setup: dict
) -> None:
    await set_business_today(db, date(2026, 11, 11))
    r = await client.delete(
        f"/api/v1/recurring-payments/{setup['rp']['id']}", headers=setup["admin"]
    )
    assert r.status_code == 200
    items = (await client.get(OCC, headers=setup["anna"])).json()["items"]
    assert [i["due_date"] for i in items] == ["2026-11-10"]
    assert items[0]["recurring_status"] == "stopped" and items[0]["state"] == "overdue"
    r = await _patch(
        client, setup["anna"], items[0]["id"], {"status": "paid", "paid_date": "2026-11-11"}
    )
    assert r.status_code == 200 and r.json()["state"] == "paid_late"


async def test_list_filters_sort_and_total(
    client: AsyncClient, db: AsyncSession, setup: dict
) -> None:
    await create_recurring(
        client, setup["admin"], "2026-11-05", title="Аренда", amount="1000", currency="RUB"
    )
    await set_business_today(db, date(2026, 11, 11))
    h = setup["anna"]

    async def ids(**params) -> tuple[int, list[str]]:
        r = await client.get(OCC, headers=h, params=params)
        assert r.status_code == 200, r.text
        body = r.json()
        return body["total"], [f"{i['currency']}:{i['due_date']}" for i in body["items"]]

    assert await ids(sort="due_date") == (
        4,
        ["RUB:2026-11-05", "USD:2026-11-10", "RUB:2026-12-05", "USD:2026-12-10"],
    )
    assert (await ids())[1][0] == "USD:2026-12-10"  # default -due_date
    assert await ids(overdue="true", sort="due_date") == (2, ["RUB:2026-11-05", "USD:2026-11-10"])
    assert (await ids(overdue="false"))[0] == 2
    assert await ids(currency="RUB", sort="due_date") == (2, ["RUB:2026-11-05", "RUB:2026-12-05"])
    assert (await ids(due_from="2026-11-06", due_to="2026-12-05"))[0] == 2
    assert (await ids(status="paid"))[0] == 0
    total, page = await ids(limit=1, offset=1, sort="due_date")
    assert total == 4 and page == ["USD:2026-11-10"]
    assert (await ids(recurring_payment_id=setup["rp"]["id"]))[0] == 2
    r = await client.get(OCC, headers=h, params={"due_from": "2026-12-01", "due_to": "2026-11-01"})
    assert r.status_code == 422
    r = await client.get(OCC, headers=h, params={"limit": 500})
    assert r.status_code == 422
