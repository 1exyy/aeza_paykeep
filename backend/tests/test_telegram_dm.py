"""Private Telegram reminders on each user's schedule. Fake bot."""

from datetime import timedelta

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.methods import SendMessage
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import get_channels
from app.channels import telegram as telegram_channel
from app.core import clock
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.notification import Delivery, PersonalReminder
from app.models.user import User
from app.worker.jobs import dispatch_deliveries, run_cycle
from tests.helpers import ADMIN, bearer, create_recurring, create_user, freeze, login

GROUP = "-1001234567890"
_M = SendMessage(chat_id=1, text="x")


class FakeBot:
    """Records send_message calls; `errors` maps chat_id → exception to raise."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.errors: dict[str, list[Exception]] = {}

    async def send_message(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        queue = self.errors.get(str(kwargs["chat_id"]))
        if queue:
            raise queue.pop(0)

        class _Msg:
            message_id = len(self.calls)

        return _Msg()

    def chats(self) -> list[str]:
        return [str(c["chat_id"]) for c in self.calls]


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> FakeBot:
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", type(settings.telegram_bot_token)("1:T"))
    monkeypatch.setattr(settings, "telegram_chat_id", GROUP)
    fake = FakeBot()
    monkeypatch.setattr(telegram_channel, "get_bot", lambda: fake)
    return fake


@pytest.fixture
async def people(db: AsyncSession) -> None:
    """anna (tg 111) and boris (tg 222) linked; carl not linked; dora linked but deleted."""
    for login_name in ("anna", "boris", "carl", "dora"):
        await create_user(db, login_name, f"{login_name}-password")
    links = {"anna": 111, "boris": 222, "dora": 444}
    for login_name, tg in links.items():
        await db.execute(update(User).where(User.login == login_name).values(telegram_user_id=tg))
    await db.execute(
        update(User).where(User.login == "dora").values(deleted_at=clock.Clock().now())
    )
    await db.commit()


async def _remind(client: AsyncClient) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    await create_recurring(client, bearer(await login(client, *ADMIN)), "2026-11-10")
    await _dispatch()


async def _dispatch() -> None:
    async with get_sessionmaker()() as s:
        await dispatch_deliveries(s)


async def _delivery(db: AsyncSession) -> Delivery:
    db.expire_all()
    [d] = (await db.scalars(select(Delivery).where(Delivery.channel == "telegram"))).all()
    return d


async def test_group_then_linked_users(
    client: AsyncClient, db: AsyncSession, bot: FakeBot, people: None
) -> None:
    await _remind(client)
    assert bot.chats() == [GROUP, "111", "222"]  # not carl (no link), not dora (deleted)
    group, *private = [c["text"] for c in bot.calls]
    assert "Сервер (VPS)" in group and "Команда" not in group
    # a person may be in several teams: private messages name the team
    assert private and all(text == f"Команда «aeza»\n{group}" for text in private)
    assert all(
        c["reply_markup"].inline_keyboard[0][0].callback_data.startswith("paid:") for c in bot.calls
    )
    d = await _delivery(db)
    assert d.status == "sent" and d.last_error is None and d.external_id == "1"


async def test_failed_private_message_retries_independently_of_group(
    client: AsyncClient, db: AsyncSession, bot: FakeBot, people: None
) -> None:
    bot.errors["111"] = [
        TelegramForbiddenError(method=_M, message="Forbidden: bot was blocked by the user")
    ]
    bot.errors["222"] = [TelegramNetworkError(method=_M, message="timeout")]
    await _remind(client)
    d = await _delivery(db)
    assert d.status == "sent"
    assert d.last_error is None
    db.expire_all()
    rows = (await db.scalars(select(PersonalReminder).order_by(PersonalReminder.user_id))).all()
    assert [r.status for r in rows] == ["pending", "unknown"]
    assert "Telegram 403" in (rows[0].last_error or "")
    moment = clock.real_now() + timedelta(hours=1)
    clock.set_real_now(lambda: moment)
    await _dispatch()
    assert bot.chats() == [GROUP, "111", "222", "111"]  # no duplicate group or unknown DM


async def test_group_error_does_not_delay_private_messages(
    client: AsyncClient, db: AsyncSession, bot: FakeBot, people: None
) -> None:
    bot.errors[GROUP] = [TelegramBadRequest(method=_M, message="chat not found")]
    await _remind(client)
    assert bot.chats() == [GROUP, "111", "222"]
    d = await _delivery(db)
    assert d.status == "pending"
    moment = d.next_attempt_at + timedelta(seconds=1)
    clock.set_real_now(lambda: moment)
    await _dispatch()
    assert bot.chats() == [GROUP, "111", "222", GROUP]  # each private message exactly once
    assert (await _delivery(db)).status == "sent"


async def test_group_no_answer_does_not_block_private_messages(
    client: AsyncClient, db: AsyncSession, bot: FakeBot, people: None
) -> None:
    bot.errors[GROUP] = [TelegramNetworkError(method=_M, message="timeout")]
    await _remind(client)
    assert bot.chats() == [GROUP, "111", "222"]
    assert (await _delivery(db)).status == "unknown"


async def test_switch_off_private_messages(
    client: AsyncClient,
    db: AsyncSession,
    bot: FakeBot,
    people: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "telegram_dm_reminders", False)
    await _remind(client)
    assert bot.chats() == [GROUP]


async def test_user_can_opt_out_and_back_in_without_changing_other_recipients(
    client: AsyncClient, db: AsyncSession, bot: FakeBot, people: None
) -> None:
    freeze("2026-11-08T10:00:00+03:00")  # the moment _remind uses: the sessions stay valid
    anna = bearer(await login(client, "anna", "anna-password"))
    boris = bearer(await login(client, "boris", "boris-password"))
    off = await client.patch(
        "/api/v1/auth/me/notifications",
        json={"telegram_dm_enabled": False},
        headers=anna,
    )
    assert off.status_code == 200 and off.json()["telegram_dm_enabled"] is False
    assert (await client.get("/api/v1/auth/me", headers=anna)).json()[
        "telegram_dm_enabled"
    ] is False
    assert (await client.get("/api/v1/auth/me", headers=boris)).json()[
        "telegram_dm_enabled"
    ] is True

    await _remind(client)
    assert bot.chats() == [GROUP, "222"]

    on = await client.patch(
        "/api/v1/auth/me/notifications",
        json={"telegram_dm_enabled": True},
        headers=anna,
    )
    assert on.status_code == 200 and on.json()["telegram_dm_enabled"] is True
    db.expire_all()
    assert (await db.scalar(select(User).where(User.login == "anna"))).telegram_dm_enabled is True


async def test_opt_out_applies_to_assigned_reminders(
    client: AsyncClient, db: AsyncSession, bot: FakeBot, people: None
) -> None:
    anna = bearer(await login(client, "anna", "anna-password"))
    await client.patch(
        "/api/v1/auth/me/notifications",
        json={"telegram_dm_enabled": False},
        headers=anna,
    )
    freeze("2026-11-08T10:00:00+03:00")
    anna_id = await db.scalar(select(User.id).where(User.login == "anna"))
    boris_id = await db.scalar(select(User.id).where(User.login == "boris"))
    await create_recurring(
        client,
        bearer(await login(client, *ADMIN)),
        "2026-11-10",
        assignee_ids=[anna_id, boris_id],
    )
    await _dispatch()
    assert bot.chats() == [GROUP, "222"]
    assert "Ответственные:" in bot.calls[0]["text"]


async def test_each_user_receives_one_reminder_on_their_chosen_day(
    client: AsyncClient, db: AsyncSession, bot: FakeBot, people: None
) -> None:
    freeze("2026-11-05T10:00:00+03:00")
    anna = bearer(await login(client, "anna", "anna-password"))
    boris = bearer(await login(client, "boris", "boris-password"))
    assert (await client.get("/api/v1/auth/me", headers=anna)).json()[
        "telegram_dm_days_before"
    ] == 3
    changed = await client.patch(
        "/api/v1/auth/me/reminder-days",
        json={"telegram_dm_days_before": 5},
        headers=anna,
    )
    assert changed.status_code == 200 and changed.json()["telegram_dm_days_before"] == 5
    await client.patch(
        "/api/v1/auth/me/reminder-days",
        json={"telegram_dm_days_before": 1},
        headers=boris,
    )
    assert (await client.get("/api/v1/auth/me", headers=anna)).json()[
        "telegram_dm_days_before"
    ] == 5

    await create_recurring(client, bearer(await login(client, *ADMIN)), "2026-11-10")
    await _dispatch()
    assert bot.chats() == ["111"]

    freeze("2026-11-07T10:00:00+03:00")
    async with get_sessionmaker()() as session:
        await run_cycle(session)
    await _dispatch()
    assert bot.chats() == ["111", GROUP]

    freeze("2026-11-09T10:00:00+03:00")
    async with get_sessionmaker()() as session:
        await run_cycle(session)
    await _dispatch()
    assert bot.chats() == ["111", GROUP, "222"]
    await _dispatch()
    assert bot.chats() == ["111", GROUP, "222"]
    db.expire_all()
    assert [r.status for r in (await db.scalars(select(PersonalReminder))).all()] == [
        "sent",
        "sent",
    ]


async def test_reminder_days_validation_and_same_day(
    client: AsyncClient, db: AsyncSession, bot: FakeBot, people: None
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    anna = bearer(await login(client, "anna", "anna-password"))
    for value in (-1, 31, 1.5):
        response = await client.patch(
            "/api/v1/auth/me/reminder-days",
            json={"telegram_dm_days_before": value},
            headers=anna,
        )
        assert response.status_code == 422
    response = await client.patch(
        "/api/v1/auth/me/reminder-days",
        json={"telegram_dm_days_before": 0},
        headers=anna,
    )
    assert response.status_code == 200
    await create_recurring(client, bearer(await login(client, *ADMIN)), "2026-11-10")
    await _dispatch()
    assert bot.chats() == [GROUP, "222"]
    freeze("2026-11-10T10:00:00+03:00")
    async with get_sessionmaker()() as session:
        await run_cycle(session)
    await _dispatch()
    assert bot.chats() == [GROUP, "222", "111"]


async def test_private_only_without_group_chat(
    client: AsyncClient,
    db: AsyncSession,
    bot: FakeBot,
    people: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "telegram_chat_id", "")
    bot.errors["111"] = [TelegramForbiddenError(method=_M, message="Forbidden")]
    await _remind(client)
    assert bot.chats() == ["111", "222"]
    assert (await db.scalars(select(Delivery).where(Delivery.channel == "telegram"))).all() == []
    db.expire_all()
    rows = (await db.scalars(select(PersonalReminder).order_by(PersonalReminder.user_id))).all()
    assert [r.status for r in rows] == ["pending", "sent"]
    assert "Telegram 403" in (rows[0].last_error or "")


async def test_private_only_without_linked_users_queues_nothing(
    client: AsyncClient, db: AsyncSession, bot: FakeBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "telegram_chat_id", "")
    await _remind(client)  # no linked users at all
    assert (await db.scalars(select(Delivery))).all() == []
    assert (await db.scalars(select(PersonalReminder))).all() == []


def test_channel_enabled_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", type(settings.telegram_bot_token)(""))
    assert "telegram" not in get_channels()
    monkeypatch.setattr(settings, "telegram_bot_token", type(settings.telegram_bot_token)("1:T"))
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    assert "telegram" not in get_channels()  # private messages use their own queue
    monkeypatch.setattr(settings, "telegram_dm_reminders", False)
    assert "telegram" not in get_channels()
    monkeypatch.setattr(settings, "telegram_chat_id", GROUP)
    assert "telegram" in get_channels()
