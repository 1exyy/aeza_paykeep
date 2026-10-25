"""GET /audit-log and the completeness of the action log (DOMAIN §11)."""

from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.channels import SendResult, set_channels_factory
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.services.telegram_paid import press_paid
from app.worker.jobs import dispatch_deliveries
from tests.helpers import ADMIN, bearer, create_recurring, freeze, login
from tests.test_contract import check
from tests.test_reminders import FakeTelegram
from tests.test_telegram import TOKEN, make_init_data

A = "/api/v1/audit-log"
OCC = "/api/v1/payment-occurrences"

# DOMAIN §11, except attachment.add|delete
EXPECTED_ACTIONS = {
    "auth.login", "auth.login_failed", "auth.logout",
    "user.create", "user.update", "user.delete",
    "recurring.create", "recurring.stop",
    "occurrence.mark_paid", "occurrence.mark_unpaid", "occurrence.change_paid_date",
    "telegram.link", "telegram.unlink", "telegram.paid_button",
    "notification.sent", "notification.failed",
}  # fmt: skip

SECRETS = ["anna-password-1", "anna-new-password", "wrong-password-9", TOKEN, ADMIN[1]]


@pytest.fixture
def tg(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeTelegram]:
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", type(settings.telegram_bot_token)(TOKEN))
    fake = FakeTelegram()
    set_channels_factory(lambda: {"telegram": fake})
    yield fake
    set_channels_factory(None)


async def _dispatch() -> None:
    async with get_sessionmaker()() as s:
        await dispatch_deliveries(s)


@pytest.fixture
async def scenario(client: AsyncClient, tg: FakeTelegram) -> dict:
    """Login → pay → unpay → create user … every kind of event once."""
    freeze("2026-11-08T07:00:00+00:00")  # 10:00 GMT+3
    admin_token = await login(client, *ADMIN)
    admin = bearer(admin_token)
    client.cookies.clear()
    r = await client.post(
        "/api/v1/users", json={"login": "anna", "password": "anna-password-1"}, headers=admin
    )
    anna_id = r.json()["id"]
    await client.post(
        "/api/v1/auth/login", json={"team": "aeza", "login": "anna", "password": "wrong-password-9"}
    )
    anna_token = await login(client, "anna", "anna-password-1")
    anna = bearer(anna_token)
    client.cookies.clear()

    await client.post("/api/v1/telegram/link", json={"init_data": make_init_data()}, headers=anna)
    rp = await create_recurring(client, admin, "2026-11-10")  # reminder queued now
    tg.results = [SendResult.ok("1"), SendResult.unknown("timeout")]
    await _dispatch()  # notification.sent
    occ = (await client.get(OCC, headers=anna, params={"sort": "due_date"})).json()["items"][0]
    await client.patch(
        f"{OCC}/{occ['id']}", json={"status": "paid", "paid_date": "2026-11-08"}, headers=anna
    )
    await client.patch(f"{OCC}/{occ['id']}", json={"paid_date": "2026-11-07"}, headers=anna)
    await client.patch(f"{OCC}/{occ['id']}", json={"status": "unpaid"}, headers=anna)
    async with get_sessionmaker()() as s:
        await press_paid(s, 111, occ["id"])  # telegram.paid_button
    await client.delete("/api/v1/telegram/link", headers=anna)

    rp2 = await create_recurring(client, admin, "2026-11-09", title="Второй")
    await _dispatch()  # unknown → notification.failed
    await client.delete(f"/api/v1/recurring-payments/{rp2['id']}", headers=admin)

    await client.patch(
        f"/api/v1/users/{anna_id}", json={"password": "anna-new-password"}, headers=admin
    )
    await client.post("/api/v1/auth/logout", headers=admin)
    admin = bearer(await login(client, *ADMIN))
    client.cookies.clear()
    await client.delete(f"/api/v1/users/{anna_id}", headers=admin)
    return {
        "admin": admin,
        "anna_id": anna_id,
        "rp": rp,
        "secrets": [*SECRETS, admin_token, anna_token],
    }


async def _all(client: AsyncClient, h: dict, **params) -> list[dict]:
    body = check(
        "/audit-log", "get", await client.get(A, headers=h, params={"limit": 200, **params})
    )
    assert body["total"] == len(body["items"])
    return body["items"]


async def test_every_domain_event_is_logged(client: AsyncClient, scenario: dict) -> None:
    items = await _all(client, scenario["admin"])
    assert {i["action"] for i in items} == EXPECTED_ACTIONS
    assert [i["id"] for i in items] == sorted(
        (i["id"] for i in items), reverse=True
    )  # newest first
    assert all(i["at"].endswith("+03:00") for i in items)


async def test_actor_and_source(client: AsyncClient, scenario: dict) -> None:
    items = await _all(client, scenario["admin"])
    by_action = {i["action"]: i for i in reversed(items)}  # first occurrence of each
    assert by_action["occurrence.mark_paid"]["actor"]["login"] == "anna"
    assert by_action["occurrence.mark_paid"]["source"] == "web"
    assert by_action["telegram.paid_button"]["source"] == "telegram"
    assert by_action["telegram.paid_button"]["actor"]["id"] == scenario["anna_id"]
    assert by_action["notification.sent"]["source"] == "system"
    assert by_action["notification.sent"]["actor"] is None
    assert by_action["auth.login_failed"]["actor"] is None
    assert by_action["auth.login_failed"]["details"] == {"team": "aeza", "login": "anna"}
    assert by_action["user.create"]["actor"]["login"] == "admin"
    assert by_action["recurring.create"]["object_type"] == "recurring_payment"
    # the deleted user is still shown with the login of the time of the action
    assert by_action["occurrence.mark_unpaid"]["actor"] == {
        "id": scenario["anna_id"],
        "login": "anna",
    }


async def test_no_secrets_in_details(client: AsyncClient, scenario: dict) -> None:
    text = str(await _all(client, scenario["admin"]))
    for secret in scenario["secrets"]:
        assert secret not in text
    assert "init_data" not in text
    assert "auth_date" not in text
    items = await _all(client, scenario["admin"])
    for item in items:
        details = dict(item["details"])
        changed = details.pop("changed", [])  # names of changed fields, e.g. ["password"]
        assert set(changed) <= {"login", "password"}
        assert "password" not in str(details).lower(), item


async def test_filters(client: AsyncClient, scenario: dict) -> None:
    h = scenario["admin"]
    assert {i["action"] for i in await _all(client, h, action="auth.")} == {
        "auth.login", "auth.login_failed", "auth.logout"
    }  # fmt: skip
    exact = await _all(client, h, action="occurrence.mark_paid")
    assert [i["action"] for i in exact] == ["occurrence.mark_paid"]
    assert await _all(client, h, action="occurrence.") != []
    assert await _all(client, h, action="occ") == []  # not a prefix without the dot
    assert await _all(client, h, action="%.") == []  # LIKE wildcards are escaped
    mine = await _all(client, h, actor_id=scenario["anna_id"])
    assert mine and all(i["actor"]["id"] == scenario["anna_id"] for i in mine)

    assert len(await _all(client, h, **{"from": "2026-11-08", "to": "2026-11-08"})) > 0
    assert await _all(client, h, **{"from": "2026-11-09"}) == []
    assert await _all(client, h, to="2026-11-07") == []
    page = (await client.get(A, headers=h, params={"limit": 2, "offset": 1})).json()
    assert len(page["items"]) == 2 and page["total"] > 2
    r = await client.get(A, headers=h, params={"from": "2026-11-09", "to": "2026-11-01"})
    assert r.status_code == 422


async def test_day_boundary_uses_system_time_zone(client: AsyncClient) -> None:
    freeze("2026-11-08T20:59:00+00:00")  # 23:59 GMT+3 on the 8th
    h = bearer(await login(client, *ADMIN))
    freeze("2026-11-08T21:01:00+00:00")  # 00:01 GMT+3 on the 9th
    await client.post(
        "/api/v1/auth/login", json={"team": "aeza", "login": "admin", "password": "bad-one"}
    )
    on_8th = await _all(client, h, **{"from": "2026-11-08", "to": "2026-11-08"})
    on_9th = await _all(client, h, **{"from": "2026-11-09", "to": "2026-11-09"})
    assert [i["action"] for i in on_8th] == ["auth.login"]
    assert [i["action"] for i in on_9th] == ["auth.login_failed"]
