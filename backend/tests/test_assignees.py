"""Responsible users of a payment."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import get_channels
from app.channels import telegram as telegram_channel
from app.channels.texts import reminder_text
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.audit_event import AuditEvent
from app.models.user import User
from app.services.telegram_paid import press_paid
from app.worker.jobs import dispatch_deliveries
from tests.helpers import ADMIN, bearer, create_user, freeze, login
from tests.test_contract import check
from tests.test_telegram_dm import GROUP, FakeBot

R = "/api/v1/recurring-payments"
OCC = "/api/v1/payment-occurrences"


@pytest.fixture
async def team(client: AsyncClient, db: AsyncSession) -> dict:
    """anna (tg 111 @anna_tg), boris (tg 222, no username), carl (not linked)."""
    freeze("2026-11-08T10:00:00+03:00")
    ids = {}
    for name in ("anna", "boris", "carl"):
        ids[name] = (await create_user(db, name, f"{name}-password")).id
    await db.execute(
        update(User)
        .where(User.login == "anna")
        .values(telegram_user_id=111, telegram_username="anna_tg")
    )
    await db.execute(update(User).where(User.login == "boris").values(telegram_user_id=222))
    await db.execute(update(User).where(User.login == "admin").values(telegram_user_id=999))
    await db.commit()
    admin = bearer(await login(client, *ADMIN))
    client.cookies.clear()
    return {"admin": admin, **ids}


async def _create(client: AsyncClient, h: dict, due: str = "2026-12-10", **kw):
    payload = {
        "title": "Сервер",
        "amount": "10",
        "currency": "USD",
        "next_due_date": due,
        "periodicity": "monthly",
    } | kw
    return await client.post(R, json=payload, headers=h)


# ---------- API ----------


async def test_create_with_assignees_and_read_back(client: AsyncClient, team: dict) -> None:
    r = await _create(
        client, team["admin"], assignee_ids=[team["boris"], team["anna"], team["anna"]]
    )
    body = check("/recurring-payments", "post", r)
    assert body["assign_all"] is False
    assert body["assignees"] == [
        {"id": team["anna"], "login": "anna"},
        {"id": team["boris"], "login": "boris"},
    ]
    listed = check("/recurring-payments", "get", await client.get(R, headers=team["admin"]))
    assert listed["items"][0]["assignees"] == body["assignees"]
    occ = check("/payment-occurrences", "get", await client.get(OCC, headers=team["admin"]))[
        "items"
    ][0]
    assert occ["assignees"] == body["assignees"] and occ["assign_all"] is False


async def test_create_assign_all_and_default_none(client: AsyncClient, team: dict) -> None:
    body = (await _create(client, team["admin"], assign_all=True)).json()
    assert body["assign_all"] is True and body["assignees"] == []
    plain = (await _create(client, team["admin"], title="Без ответственных")).json()
    assert plain["assign_all"] is False and plain["assignees"] == []


@pytest.mark.parametrize(
    ("extra", "field"),
    [
        ({"assignee_ids": [99999]}, "assignee_ids"),
        ({"assignee_ids": ["x"]}, "assignee_ids.0"),
        ({"assign_all": True, "assignee_ids": [1]}, "assign_all"),
    ],
)
async def test_create_validation(client: AsyncClient, team: dict, extra: dict, field: str) -> None:
    r = await _create(client, team["admin"], **extra)
    body = check("/recurring-payments", "post", r)
    assert r.status_code == 422 and field in [d["field"] for d in body["error"]["details"]]


async def test_admin_and_deleted_users_cannot_be_assignees(
    client: AsyncClient, db: AsyncSession, team: dict
) -> None:
    admin_id = await db.scalar(select(User.id).where(User.login == "admin"))
    assert (await _create(client, team["admin"], assignee_ids=[admin_id])).status_code == 422
    await client.delete(f"/api/v1/users/{team['carl']}", headers=team["admin"])
    assert (await _create(client, team["admin"], assignee_ids=[team["carl"]])).status_code == 422


async def test_patch_assignees(client: AsyncClient, db: AsyncSession, team: dict) -> None:
    rp = (await _create(client, team["admin"], assignee_ids=[team["anna"]])).json()
    url = f"{R}/{rp['id']}"
    body = check(
        "/recurring-payments/{id}",
        "patch",
        await client.patch(
            url,
            json={"assignee_ids": [team["boris"]], "expected_version": rp["version"]},
            headers=team["admin"],
        ),
    )
    assert [a["login"] for a in body["assignees"]] == ["boris"] and body["version"] == rp[
        "version"
    ] + 1
    body = (await client.patch(url, json={"assign_all": True}, headers=team["admin"])).json()
    assert body["assign_all"] is True and body["assignees"] == []
    body = (await client.patch(url, json={"assign_all": False}, headers=team["admin"])).json()
    assert body["assign_all"] is False and body["assignees"] == []
    same = (await client.patch(url, json={"assignee_ids": []}, headers=team["admin"])).json()
    assert same["version"] == body["version"]  # nothing changed

    r = await client.patch(
        url, json={"assignee_ids": [team["anna"]], "expected_version": 1}, headers=team["admin"]
    )
    assert check("/recurring-payments/{id}", "patch", r)["error"]["code"] == "version_conflict"
    r = await client.patch(url, json={"status": "stopped"}, headers=team["admin"])
    assert check("/recurring-payments/{id}", "patch", r)["error"]["code"] == "field_not_allowed"
    r = await client.patch(url, json={}, headers=team["admin"])
    assert check("/recurring-payments/{id}", "patch", r)["error"]["code"] == "validation_error"
    check(
        "/recurring-payments/{id}",
        "patch",
        await client.patch(f"{R}/9999", json={"assign_all": True}, headers=team["admin"]),
    )

    events = (
        await db.scalars(
            select(AuditEvent).where(AuditEvent.action == "recurring.update_assignees")
        )
    ).all()
    assert len(events) == 3
    assert events[0].details["from"]["assignees"] == ["anna"] and events[0].details["to"][
        "assignees"
    ] == ["boris"]
    # fmt: skip


async def test_deleted_user_drops_out(client: AsyncClient, team: dict) -> None:
    rp = (await _create(client, team["admin"], assignee_ids=[team["anna"], team["carl"]])).json()
    await client.delete(f"/api/v1/users/{team['carl']}", headers=team["admin"])
    body = (await client.get(R, headers=team["admin"])).json()["items"][0]
    assert body["id"] == rp["id"] and [a["login"] for a in body["assignees"]] == ["anna"]


# ---------- Telegram: mentions, private messages ----------


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", type(settings.telegram_bot_token)("1:T"))
    monkeypatch.setattr(settings, "telegram_chat_id", GROUP)
    fake = FakeBot()
    monkeypatch.setattr(telegram_channel, "get_bot", lambda: fake)
    assert "telegram" in get_channels()
    return fake


async def _remind(client: AsyncClient, h: dict, **kw) -> None:
    r = await _create(client, h, due="2026-11-10", **kw)  # due in 2 days → immediate reminder
    assert r.status_code == 201, r.text
    async with get_sessionmaker()() as s:
        await dispatch_deliveries(s)


async def test_group_message_tags_assignees(client: AsyncClient, team: dict, bot: FakeBot) -> None:
    await _remind(
        client, team["admin"], title="Аренда <офис>", assignee_ids=[team["anna"], team["carl"]]
    )
    group = bot.calls[0]
    assert group["chat_id"] == GROUP and group["parse_mode"] == "HTML"
    assert "Аренда &lt;офис&gt;" in group["text"]  # escaped for HTML
    assert group["text"].endswith('Ответственные: <a href="tg://user?id=111">@anna_tg</a>, carl')
    # private messages: only the linked assignees (anna), not boris
    assert [str(c["chat_id"]) for c in bot.calls[1:]] == ["111"]


async def test_assign_all_tags_everyone_and_mentions_without_username(
    client: AsyncClient, team: dict, bot: FakeBot
) -> None:
    await _remind(client, team["admin"], assign_all=True)
    text = bot.calls[0]["text"]
    assert '<a href="tg://user?id=111">@anna_tg</a>' in text
    assert '<a href="tg://user?id=222">boris</a>' in text and "carl" in text
    assert sorted(str(c["chat_id"]) for c in bot.calls[1:]) == ["111", "222"]


async def test_without_assignees_nothing_changes(
    client: AsyncClient, team: dict, bot: FakeBot
) -> None:
    await _remind(client, team["admin"])
    assert "Ответственные" not in bot.calls[0]["text"]
    assert sorted(str(c["chat_id"]) for c in bot.calls[1:]) == ["111", "222", "999"]


def test_plain_text_for_email_and_slack() -> None:
    payload = {"title": "Сервер", "amount": "10.00", "currency": "USD", "due_date": "2026-11-10"}
    assert reminder_text(payload | {"assignees": ["anna", "boris"]}).endswith(
        "Ответственные: anna, boris"
    )
    assert reminder_text(payload | {"assign_all": True}).endswith("Ответственные: все пользователи")
    assert "Ответственные" not in reminder_text(payload)


# ---------- «Оплачено»: only assignees and admin ----------


async def _occurrence_id(client: AsyncClient, h: dict) -> int:
    return (await client.get(OCC, headers=h, params={"sort": "due_date"})).json()["items"][0]["id"]


async def _press(telegram_user_id: int, occurrence_id: int):
    async with get_sessionmaker()() as s:
        return await press_paid(s, telegram_user_id, occurrence_id)


async def test_only_assignee_or_admin_can_press(
    client: AsyncClient, db: AsyncSession, team: dict
) -> None:
    await _create(client, team["admin"], due="2026-11-10", assignee_ids=[team["anna"]])
    occ_id = await _occurrence_id(client, team["admin"])
    denied = await _press(222, occ_id)  # boris: linked but not responsible
    assert denied.paid_line is None and denied.alert == "Оплату отмечает ответственный: anna"
    event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "telegram.paid_button"))
    assert (
        event is not None
        and event.result == "failure"
        and event.details["reason"] == "not_assignee"
    )
    ok = await _press(111, occ_id)  # anna
    assert ok.paid_line == "✅ Оплачено 08.11.2026 — anna"


async def test_admin_can_press_anyway(client: AsyncClient, team: dict) -> None:
    await _create(client, team["admin"], due="2026-11-10", assignee_ids=[team["anna"]])
    occ_id = await _occurrence_id(client, team["admin"])
    assert (await _press(999, occ_id)).paid_line == "✅ Оплачено 08.11.2026 — admin"


async def test_assign_all_and_no_assignees_let_any_user_press(
    client: AsyncClient, team: dict
) -> None:
    await _create(client, team["admin"], due="2026-11-10", assign_all=True)
    occ_id = await _occurrence_id(client, team["admin"])
    assert (await _press(222, occ_id)).paid_line is not None


async def test_web_payment_is_not_restricted(
    client: AsyncClient, db: AsyncSession, team: dict
) -> None:
    """PDF p.9: a user marks payments in the panel — assignees restrict only the Telegram button."""
    await _create(client, team["admin"], due="2026-11-10", assignee_ids=[team["anna"]])
    boris = bearer(await login(client, "boris", "boris-password"))
    occ_id = await _occurrence_id(client, boris)
    r = await client.patch(
        f"{OCC}/{occ_id}", json={"status": "paid", "paid_date": "2026-11-08"}, headers=boris
    )
    assert r.status_code == 200 and r.json()["paid_by"]["login"] == "boris"
