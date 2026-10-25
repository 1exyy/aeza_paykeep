"""Telegram: initData signature, account link, «Оплачено» button (DOMAIN §9). No network."""

import asyncio
import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import pytest
from aiogram.types import Message
from aiogram.utils.web_app import check_webapp_signature
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import set_channels_factory
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.security import InitDataError, verify_init_data
from app.models.audit_event import AuditEvent
from app.models.notification import Delivery
from app.models.payment import PaymentOccurrence
from app.services.telegram_paid import NO_ACCESS, parse_callback, press_paid
from tests.helpers import ADMIN, bearer, create_recurring, create_user, freeze, login
from tests.test_reminders import FakeTelegram

TOKEN = "123456:TEST-token"
NOW = datetime(2026, 11, 8, 7, 0, tzinfo=UTC)  # 10:00 GMT+3
ANNA_TG = 111
BORIS_TG = 222


def make_init_data(
    user_id: int = ANNA_TG, token: str = TOKEN, auth_date: datetime = NOW, **extra: str
) -> str:
    """Signed exactly like Telegram does (independent of the code under test)."""
    data = {
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": user_id, "first_name": "Anna", "username": "anna_tg"}),
        "auth_date": str(int(auth_date.timestamp())),
        **extra,
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest.fixture(autouse=True)
def bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", type(settings.telegram_bot_token)(TOKEN))


@pytest.fixture
def tg() -> Iterator[FakeTelegram]:
    fake = FakeTelegram()
    set_channels_factory(lambda: {"telegram": fake})
    yield fake
    set_channels_factory(None)


# ---------- signature ----------


def test_valid_init_data_matches_aiogram() -> None:
    init_data = make_init_data()
    assert check_webapp_signature(TOKEN, init_data)  # reference implementation agrees
    user = verify_init_data(init_data, TOKEN, NOW)
    assert user["id"] == ANNA_TG and user["username"] == "anna_tg"


def test_signature_field_is_part_of_the_check() -> None:
    init_data = make_init_data(signature="abc")
    assert verify_init_data(init_data, TOKEN, NOW)["id"] == ANNA_TG


@pytest.mark.parametrize(
    "init_data",
    [
        make_init_data().replace("%22id%22%3A+111", "%22id%22%3A+999"),  # forged user id
        make_init_data(token="999:other-bot"),
        make_init_data(auth_date=NOW - timedelta(hours=24, seconds=1)),
        make_init_data(auth_date=NOW + timedelta(hours=1)),
        make_init_data().split("&hash=")[0],
        "not a query string",
        "",
    ],
)
def test_invalid_init_data(init_data: str) -> None:
    with pytest.raises(InitDataError):
        verify_init_data(init_data, TOKEN, NOW)


def test_23_hours_old_is_still_valid() -> None:
    assert verify_init_data(make_init_data(auth_date=NOW - timedelta(hours=23)), TOKEN, NOW)


def test_no_bot_token_rejects() -> None:
    with pytest.raises(InitDataError):
        verify_init_data(make_init_data(), "", NOW)


# ---------- link API ----------


@pytest.fixture
async def people(client: AsyncClient, db: AsyncSession) -> dict:
    freeze(NOW.isoformat())
    admin = bearer(await login(client, *ADMIN))
    await create_user(db, "anna", "anna-password")
    await create_user(db, "boris", "boris-password")
    anna = bearer(await login(client, "anna", "anna-password"))
    boris = bearer(await login(client, "boris", "boris-password"))
    client.cookies.clear()
    return {"admin": admin, "anna": anna, "boris": boris}


async def _link(client: AsyncClient, h: dict, init_data: str):
    return await client.post("/api/v1/telegram/link", json={"init_data": init_data}, headers=h)


async def test_link_and_unlink(client: AsyncClient, db: AsyncSession, people: dict) -> None:
    from tests.test_contract import check

    r = await _link(client, people["anna"], make_init_data())
    body = check("/telegram/link", "post", r)
    assert body["login"] == "anna" and body["telegram_linked"] is True
    me = (await client.get("/api/v1/auth/me", headers=people["anna"])).json()
    assert me["telegram_linked"] is True
    assert (await _link(client, people["anna"], make_init_data())).status_code == 200  # again

    check(
        "/telegram/link",
        "delete",
        await client.delete("/api/v1/telegram/link", headers=people["anna"]),
    )
    me = (await client.get("/api/v1/auth/me", headers=people["anna"])).json()
    assert me["telegram_linked"] is False
    assert (await client.delete("/api/v1/telegram/link", headers=people["anna"])).status_code == 204

    actions = (
        await db.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.action.like("telegram.%"))
            .order_by(AuditEvent.id)
        )
    ).all()
    assert actions == ["telegram.link", "telegram.unlink"]


async def test_one_telegram_one_user(client: AsyncClient, people: dict) -> None:
    from tests.test_contract import check

    await _link(client, people["anna"], make_init_data())
    body = check("/telegram/link", "post", await _link(client, people["boris"], make_init_data()))
    assert body["error"]["code"] == "telegram_already_linked"


async def test_invalid_link_is_422_and_audited_without_init_data(
    client: AsyncClient, db: AsyncSession, people: dict
) -> None:
    from tests.test_contract import check

    forged = make_init_data(token="999:other")
    body = check("/telegram/link", "post", await _link(client, people["anna"], forged))
    assert body["error"]["code"] == "telegram_invalid_init_data"
    event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "telegram.link"))
    assert event is not None and event.result == "failure"
    assert "hash" not in str(event.details) and forged not in str(event.details)
    assert (
        await client.post("/api/v1/telegram/link", json={}, headers=people["anna"])
    ).status_code == 422
    assert (await client.post("/api/v1/telegram/link", json={"init_data": "x"})).status_code == 401


async def test_deleted_user_loses_link(client: AsyncClient, db: AsyncSession, people: dict) -> None:
    await _link(client, people["anna"], make_init_data())
    anna_id = (await client.get("/api/v1/auth/me", headers=people["anna"])).json()["id"]
    await client.delete(f"/api/v1/users/{anna_id}", headers=people["admin"])
    # the Telegram account is free again
    assert (await _link(client, people["boris"], make_init_data())).status_code == 200


# ---------- «Оплачено» button ----------


@pytest.fixture
async def reminder(client: AsyncClient, db: AsyncSession, people: dict, tg: FakeTelegram) -> dict:
    """anna linked as ANNA_TG; a payment due in 2 days with a queued reminder."""
    await _link(client, people["anna"], make_init_data())
    await create_recurring(client, people["admin"], "2026-11-10")
    occ = (
        await client.get(
            "/api/v1/payment-occurrences", headers=people["anna"], params={"sort": "due_date"}
        )
    ).json()["items"][0]
    return {**people, "occ": occ}


async def _press(telegram_user_id: int, occurrence_id: int):
    async with get_sessionmaker()() as s:
        return await press_paid(s, telegram_user_id, occurrence_id)


async def test_linked_user_marks_paid_today(
    client: AsyncClient, db: AsyncSession, reminder: dict
) -> None:
    outcome = await _press(ANNA_TG, reminder["occ"]["id"])
    assert outcome.paid_line == "✅ Оплачено 08.11.2026 — anna"
    occ = (
        await client.get(
            f"/api/v1/payment-occurrences/{reminder['occ']['id']}", headers=reminder["anna"]
        )
    ).json()
    assert occ["status"] == "paid" and occ["paid_date"] == "2026-11-08"
    assert (
        occ["paid_via"] == "telegram" and occ["paid_by"]["login"] == "anna" and occ["version"] == 2
    )
    [delivery] = (await db.scalars(select(Delivery))).all()
    assert delivery.status == "failed" and delivery.last_error == "cancelled"
    event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "telegram.paid_button"))
    assert event is not None and event.source == "telegram" and event.actor_login == "anna"


async def test_stranger_gets_no_access(db: AsyncSession, reminder: dict) -> None:
    outcome = await _press(BORIS_TG, reminder["occ"]["id"])
    assert outcome.alert == NO_ACCESS and outcome.paid_line is None
    occ = await db.get(PaymentOccurrence, reminder["occ"]["id"])
    assert occ is not None and occ.status == "unpaid"


async def test_deleted_user_gets_no_access(
    client: AsyncClient, db: AsyncSession, reminder: dict
) -> None:
    anna_id = (await client.get("/api/v1/auth/me", headers=reminder["anna"])).json()["id"]
    await client.delete(f"/api/v1/users/{anna_id}", headers=reminder["admin"])
    assert (await _press(ANNA_TG, reminder["occ"]["id"])).alert == NO_ACCESS


async def test_double_press_pays_once(
    client: AsyncClient, db: AsyncSession, reminder: dict
) -> None:
    occ_id = reminder["occ"]["id"]
    first, second = await asyncio.gather(_press(ANNA_TG, occ_id), _press(ANNA_TG, occ_id))
    outcomes = sorted([first, second], key=lambda o: o.paid_line is None)
    assert outcomes[0].paid_line is not None
    assert outcomes[1].alert == "Уже оплачено 08.11.2026" and outcomes[1].paid_line is None
    occ = (
        await client.get(f"/api/v1/payment-occurrences/{occ_id}", headers=reminder["anna"])
    ).json()
    assert occ["version"] == 2
    later = await _press(ANNA_TG, occ_id)
    assert later.alert == "Уже оплачено 08.11.2026"


async def test_already_paid_in_web_keeps_its_date(client: AsyncClient, reminder: dict) -> None:
    occ_id = reminder["occ"]["id"]
    await client.patch(
        f"/api/v1/payment-occurrences/{occ_id}",
        json={"status": "paid", "paid_date": "2026-11-01"},
        headers=reminder["anna"],
    )
    assert (await _press(ANNA_TG, occ_id)).alert == "Уже оплачено 01.11.2026"
    occ = (
        await client.get(f"/api/v1/payment-occurrences/{occ_id}", headers=reminder["anna"])
    ).json()
    assert occ["paid_date"] == "2026-11-01" and occ["paid_via"] == "web"


async def test_period_removed_on_stop_is_not_found(client: AsyncClient, reminder: dict) -> None:
    await client.delete(
        f"/api/v1/recurring-payments/{reminder['occ']['recurring_payment_id']}",
        headers=reminder["admin"],
    )
    # the period due in 2 days is unpaid and after today → removed on stop; pay an existing one
    outcome = await _press(ANNA_TG, reminder["occ"]["id"])
    assert outcome.alert == "Платёж не найден"


async def test_stopped_payment_existing_period_can_be_paid(
    client: AsyncClient, db: AsyncSession, people: dict, tg: FakeTelegram
) -> None:
    await _link(client, people["anna"], make_init_data())
    rp = await create_recurring(client, people["admin"], "2026-11-08")  # due today, stays on stop
    await client.delete(f"/api/v1/recurring-payments/{rp['id']}", headers=people["admin"])
    occ = (
        await client.get(
            "/api/v1/payment-occurrences",
            headers=people["anna"],
            params={"recurring_payment_id": rp["id"]},
        )
    ).json()["items"][0]
    assert occ["recurring_status"] == "stopped"
    assert (await _press(ANNA_TG, occ["id"])).paid_line is not None


def test_parse_callback() -> None:
    assert parse_callback("paid:42") == 42
    assert parse_callback("paid:") is None
    assert parse_callback("paid:1;drop") is None
    assert parse_callback("other:1") is None
    assert parse_callback(None) is None


# ---------- bot handler ----------


async def test_bot_handler_answers_and_edits_message(reminder: dict) -> None:
    from app.worker.bot import on_paid

    message = MagicMock(spec=Message)
    message.html_text = (
        '🔔 Напоминание об оплате\nСервер (VPS)\nОтветственные: <a href="tg://user?id=111">'
        "@anna_tg</a>"
    )
    message.message_id = 5
    message.edit_text = AsyncMock()
    callback = MagicMock()
    callback.data = f"paid:{reminder['occ']['id']}"
    callback.from_user.id = ANNA_TG
    callback.from_user.username = None
    callback.message = message
    callback.answer = AsyncMock()

    await on_paid(callback)
    callback.answer.assert_awaited_once_with("✅ Оплачено 08.11.2026 — anna", show_alert=False)
    message.edit_text.assert_awaited_once_with(  # mention links survive the edit
        '🔔 Напоминание об оплате\nСервер (VPS)\nОтветственные: <a href="tg://user?id=111">'
        "@anna_tg</a>\n\n✅ Оплачено 08.11.2026 — anna",
        parse_mode="HTML",
        reply_markup=None,
    )

    callback.from_user.id = BORIS_TG
    callback.answer.reset_mock()
    message.edit_text.reset_mock()
    await on_paid(callback)
    callback.answer.assert_awaited_once_with(NO_ACCESS, show_alert=True)
    message.edit_text.assert_not_awaited()
