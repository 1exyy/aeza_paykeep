"""Reminders and delivery (DOMAIN §6). The Telegram channel is a fake; no network."""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import SendMessage
from aiohttp import ClientConnectorError
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import SendResult, set_channels_factory
from app.channels.telegram import TelegramChannel
from app.core import clock
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.audit_event import AuditEvent
from app.models.notification import Delivery, Notification
from app.services import outbox
from app.worker.jobs import dispatch_deliveries, run_cycle
from tests.helpers import ADMIN, bearer, create_recurring, create_user, freeze, login

OCC = "/api/v1/payment-occurrences"


class FakeTelegram:
    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[int, dict]] = []
        self.results: list[SendResult] = []
        self.delay = 0.0

    def handles(self, notification_type: str) -> bool:
        return notification_type == "payment.due_soon"

    async def send(self, notification: Notification, delivery: Delivery) -> SendResult:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.sent.append((delivery.id, dict(notification.payload)))
        return self.results.pop(0) if self.results else SendResult.ok(str(len(self.sent)))


@pytest.fixture
def tg() -> Iterator[FakeTelegram]:
    fake = FakeTelegram()
    set_channels_factory(lambda: {"telegram": fake})
    yield fake
    set_channels_factory(None)


async def _admin(client: AsyncClient) -> dict:
    client.cookies.clear()
    return bearer(await login(client, *ADMIN))


async def _count(db: AsyncSession, model) -> int:  # noqa: ANN001
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def _deliveries(db: AsyncSession) -> list[Delivery]:
    db.expire_all()
    return list(await db.scalars(select(Delivery).order_by(Delivery.id)))


async def _cycle() -> None:
    async with get_sessionmaker()() as s:
        await run_cycle(s)


async def _dispatch() -> int:
    async with get_sessionmaker()() as s:
        return await dispatch_deliveries(s)


# ---------- when ----------


async def test_from_9am_on_due_minus_3(client: AsyncClient, db: AsyncSession, tg) -> None:  # noqa: ANN001
    freeze("2026-10-24T12:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    await _cycle()
    assert await _count(db, Notification) == 0

    freeze("2026-11-07T08:59:59+03:00")
    await _cycle()
    assert await _count(db, Notification) == 0

    freeze("2026-11-07T09:00:00+03:00")
    await _cycle()
    assert await _count(db, Notification) == 1
    assert await _dispatch() == 1
    assert tg.sent[0][1]["due_date"] == "2026-11-10" and tg.sent[0][1]["overdue"] is False

    h = await _admin(client)
    items = (await client.get(OCC, headers=h, params={"sort": "due_date"})).json()["items"]
    assert items[0]["reminder_sent_at"] == "2026-11-07T09:00:00+03:00"
    assert items[1]["reminder_sent_at"] is None


async def test_late_creation_is_immediate(client: AsyncClient, db: AsyncSession, tg) -> None:  # noqa: ANN001
    freeze("2026-11-08T03:00:00+03:00")  # before 09:00, 2 days before the due date
    await create_recurring(client, await _admin(client), "2026-11-10")
    assert await _count(db, Notification) == 1  # queued in the POST transaction
    assert await _dispatch() == 1
    assert [d.status for d in await _deliveries(db)] == ["sent"]


async def test_due_today_is_immediate(client: AsyncClient, db: AsyncSession, tg) -> None:  # noqa: ANN001
    freeze("2026-11-10T23:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    assert await _dispatch() == 1
    assert tg.sent[0][1]["overdue"] is False


async def test_catch_up_after_downtime(client: AsyncClient, db: AsyncSession, tg) -> None:  # noqa: ANN001
    freeze("2026-10-24T12:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    freeze("2026-11-12T07:00:00+03:00")  # the worker was down from 10-24 to 11-12
    await _cycle()
    await _dispatch()
    assert len(tg.sent) == 1
    assert tg.sent[0][1]["due_date"] == "2026-11-10" and tg.sent[0][1]["overdue"] is True


# ---------- who is not reminded ----------


async def test_paid_and_stopped_are_not_reminded(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-10-24T12:00:00+03:00")
    h = await _admin(client)
    paid = await create_recurring(client, h, "2026-11-10", title="Оплачен заранее")
    stopped = await create_recurring(client, h, "2026-11-10", title="Прекращён")
    occ = (
        await client.get(
            OCC, headers=h, params={"recurring_payment_id": paid["id"], "sort": "due_date"}
        )
    ).json()
    await client.patch(
        f"{OCC}/{occ['items'][0]['id']}",
        json={"status": "paid", "paid_date": "2026-10-24"},
        headers=h,
    )
    await client.delete(f"/api/v1/recurring-payments/{stopped['id']}", headers=h)
    freeze("2026-11-07T10:00:00+03:00")
    await _cycle()
    assert await _count(db, Notification) == 0


async def test_no_duplicates_across_cycles_and_restart(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    for _ in range(3):
        await _cycle()  # every call is a fresh DB session, like a restarted worker
        await _dispatch()
    assert len(tg.sent) == 1
    assert await _count(db, Notification) == 1 and await _count(db, Delivery) == 1


async def test_unpay_after_reminder_gives_no_new_one(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    h = await _admin(client)
    await create_recurring(client, h, "2026-11-10")
    await _dispatch()
    occ_id = (await client.get(OCC, headers=h, params={"sort": "due_date"})).json()["items"][0][
        "id"
    ]
    await client.patch(
        f"{OCC}/{occ_id}", json={"status": "paid", "paid_date": "2026-11-08"}, headers=h
    )
    await client.patch(f"{OCC}/{occ_id}", json={"status": "unpaid"}, headers=h)
    await _cycle()
    await _dispatch()
    assert len(tg.sent) == 1


# ---------- cancellation ----------


async def test_payment_before_dispatch_cancels(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    h = await _admin(client)
    await create_recurring(client, h, "2026-11-10")
    occ_id = (await client.get(OCC, headers=h, params={"sort": "due_date"})).json()["items"][0][
        "id"
    ]
    await client.patch(
        f"{OCC}/{occ_id}", json={"status": "paid", "paid_date": "2026-11-08"}, headers=h
    )
    assert await _dispatch() == 0
    [d] = await _deliveries(db)
    assert d.status == "failed" and d.last_error == "cancelled" and tg.sent == []


async def test_stop_cancels_pending(client: AsyncClient, db: AsyncSession, tg) -> None:  # noqa: ANN001
    freeze("2026-11-08T10:00:00+03:00")
    h = await _admin(client)
    rp = await create_recurring(client, h, "2026-11-10")
    r = await client.delete(f"/api/v1/recurring-payments/{rp['id']}", headers=h)
    assert r.status_code == 200
    assert await _dispatch() == 0
    [d] = await _deliveries(db)
    assert d.status == "failed" and d.last_error == "cancelled" and tg.sent == []


async def test_cancelled_at_send_time_if_paid_meanwhile(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    """Claimed, then paid before the network call: not sent."""
    freeze("2026-11-08T10:00:00+03:00")
    h = await _admin(client)
    await create_recurring(client, h, "2026-11-10")
    async with get_sessionmaker()() as s:
        ids = await outbox.claim(s)
    occ_id = (await client.get(OCC, headers=h, params={"sort": "due_date"})).json()["items"][0][
        "id"
    ]
    await client.patch(
        f"{OCC}/{occ_id}", json={"status": "paid", "paid_date": "2026-11-08"}, headers=h
    )
    async with get_sessionmaker()() as s:
        assert await outbox.deliver(s, ids[0], {"telegram": tg}) == "failed"
    assert tg.sent == []


# ---------- delivery outcomes ----------


async def test_explicit_errors_are_retried_up_to_5(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    tg.results = [SendResult.failed("Telegram 5xx") for _ in range(5)]
    moment = clock.real_now()
    for attempt in range(1, 6):
        assert await _dispatch() == 1
        [d] = await _deliveries(db)
        assert d.attempts == attempt
        if attempt < 5:
            assert d.status == "pending"
            assert await _dispatch() == 0  # not before the backoff
            moment = d.next_attempt_at + timedelta(seconds=1)
            clock.set_real_now(lambda m=moment: m)
    assert d.status == "failed" and d.last_error == "Telegram 5xx"
    assert len(tg.sent) == 5
    failed = await db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "notification.failed")
    )
    assert failed == 1


async def test_429_waits_retry_after(client: AsyncClient, db: AsyncSession, tg) -> None:  # noqa: ANN001
    freeze("2026-11-08T10:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    tg.results = [SendResult.failed("429", retry_after=7)]
    await _dispatch()
    [d] = await _deliveries(db)
    assert d.status == "pending"
    assert d.next_attempt_at == clock.real_now() + timedelta(seconds=7)
    freeze("2026-11-08T10:00:08+03:00")
    await _dispatch()
    assert [x.status for x in await _deliveries(db)] == ["sent"]
    assert len(tg.sent) == 2


async def test_unknown_result_is_never_retried(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    tg.results = [SendResult.unknown("timeout")]
    await _dispatch()
    freeze("2026-11-09T10:00:00+03:00")
    await _cycle()
    await _dispatch()
    [d] = await _deliveries(db)
    assert d.status == "unknown" and len(tg.sent) == 1


async def test_stuck_sending_becomes_unknown(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    async with get_sessionmaker()() as s:
        await outbox.claim(s)  # the worker "dies" right after claiming
    freeze("2026-11-08T10:04:59+03:00")
    await _dispatch()
    assert [d.status for d in await _deliveries(db)] == ["sending"]
    freeze("2026-11-08T10:05:01+03:00")
    await _dispatch()
    assert [d.status for d in await _deliveries(db)] == ["unknown"]
    assert tg.sent == []


async def test_parallel_dispatchers_send_each_once(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    h = await _admin(client)
    for n in range(4):
        await create_recurring(client, h, "2026-11-10", title=f"Платёж {n}")
    tg.delay = 0.05
    claimed = await asyncio.gather(_dispatch(), _dispatch(), _dispatch())
    assert sum(claimed) == 4
    sent_ids = [delivery_id for delivery_id, _ in tg.sent]
    assert len(sent_ids) == 4 and len(set(sent_ids)) == 4
    assert {d.status for d in await _deliveries(db)} == {"sent"}


async def test_no_channel_means_no_notification(client: AsyncClient, db: AsyncSession) -> None:
    set_channels_factory(lambda: {})
    try:
        freeze("2026-11-08T10:00:00+03:00")
        await create_recurring(client, await _admin(client), "2026-11-10")
        await _cycle()
        assert await _count(db, Notification) == 0
    finally:
        set_channels_factory(None)


async def test_channel_disabled_after_queueing(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    set_channels_factory(lambda: {})
    await _dispatch()
    [d] = await _deliveries(db)
    assert d.status == "failed" and d.last_error == "channel is disabled"


async def test_sent_is_audited_without_secrets(
    client: AsyncClient,
    db: AsyncSession,
    tg,  # noqa: ANN001
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    await create_recurring(client, await _admin(client), "2026-11-10")
    await _dispatch()
    event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "notification.sent"))
    assert event is not None and event.source == "system" and event.actor_id is None
    assert event.details["channel"] == "telegram" and event.details["status"] == "sent"


# ---------- Telegram channel: error mapping and text ----------


class _FakeBot:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.calls: list[dict] = []

    async def send_message(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        if self.error:
            raise self.error

        class _Msg:
            message_id = 42

        return _Msg()


_METHOD = SendMessage(chat_id=1, text="x")


def _connect_failure() -> ClientConnectorError:
    return ClientConnectorError(MagicMock(), OSError(101, "Network is unreachable"))


def _network_error_from(cause: Exception) -> TelegramNetworkError:
    error = TelegramNetworkError(method=_METHOD, message=f"{type(cause).__name__}")
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (None, "sent"),
        (TelegramRetryAfter(method=_METHOD, message="Too Many Requests", retry_after=3), "failed"),
        (TelegramServerError(method=_METHOD, message="Bad Gateway"), "failed"),
        (TelegramBadRequest(method=_METHOD, message="chat not found"), "failed"),
        (TelegramNetworkError(method=_METHOD, message="timeout"), "unknown"),
        (_network_error_from(_connect_failure()), "failed"),  # never connected: retry is safe
        (TimeoutError(), "unknown"),
    ],
)
async def test_telegram_channel_outcomes(monkeypatch, error, outcome) -> None:  # noqa: ANN001
    from app.channels import telegram

    bot = _FakeBot(error)
    monkeypatch.setattr(telegram, "get_bot", lambda: bot)
    monkeypatch.setattr(get_settings(), "telegram_chat_id", "-100500")
    notification = Notification(
        id=1,
        type="payment.due_soon",
        occurrence_id=7,
        payload={
            "title": "Сервер",
            "amount": "120.00",
            "currency": "USD",
            "due_date": "2026-11-10",
        },
    )
    result = await TelegramChannel().send(notification, Delivery(id=1, channel="telegram"))
    assert result.outcome == outcome
    if outcome == "sent":
        assert result.external_id == "42"
        call = bot.calls[0]
        assert call["chat_id"] == "-100500"
        assert call["text"] == (
            "🔔 Напоминание об оплате\nСервер\nСумма: 120.00 USD\nСрок оплаты: 10.11.2026"
        )
        button = call["reply_markup"].inline_keyboard[0][0]
        assert button.text == "✅ Оплачено" and button.callback_data == "paid:7"
    if isinstance(error, TelegramRetryAfter):
        assert result.retry_after == 3


def test_overdue_text() -> None:
    from app.channels.texts import reminder_text

    payload = {"title": "Аренда", "amount": "85000.00", "currency": "RUB", "due_date": "2026-11-05"}
    assert reminder_text(payload | {"overdue": True}).endswith("⚠️ Срок оплаты прошёл")


# ---------- API: deliveries and dev clock ----------


async def test_deliveries_api_and_dev_endpoints(
    client: AsyncClient,
    db: AsyncSession,
    tg,
    monkeypatch,  # noqa: ANN001
) -> None:
    from tests.test_contract import check

    freeze("2026-10-24T12:00:00+03:00")
    h = await _admin(client)
    await create_user(db, "anna", "anna-password")
    anna = bearer(await login(client, "anna", "anna-password"))
    client.cookies.clear()
    await create_recurring(client, h, "2026-10-26")  # immediate reminder

    body = check("/dev/clock", "get", await client.get("/api/v1/dev/clock", headers=anna))
    assert body == {"today": "2026-10-24", "real_today": "2026-10-24", "offset_days": 0}
    check(
        "/dev/clock",
        "put",
        await client.put("/api/v1/dev/clock", json={"offset_days": 31}, headers=anna),
    )  # 403
    body = check(
        "/dev/clock",
        "put",
        await client.put("/api/v1/dev/clock", json={"offset_days": 31}, headers=h),
    )
    assert body["today"] == "2026-11-24" and body["offset_days"] == 31
    assert (
        await client.put("/api/v1/dev/clock", json={"offset_days": 1000}, headers=h)
    ).status_code == 422
    check("/dev/run-jobs", "post", await client.post("/api/v1/dev/run-jobs", headers=h))
    assert len(tg.sent) >= 1  # run-jobs also dispatches

    page = check(
        "/notifications/deliveries",
        "get",
        await client.get(
            "/api/v1/notifications/deliveries", headers=h, params={"channel": "telegram"}
        ),
    )
    assert page["total"] >= 1 and page["items"][0]["notification_type"] == "payment.due_soon"
    check(
        "/notifications/deliveries",
        "get",
        await client.get("/api/v1/notifications/deliveries", headers=anna),
    )  # 403

    monkeypatch.setattr(get_settings(), "dev_mode", False)
    assert (await client.get("/api/v1/dev/clock", headers=h)).status_code == 404
    assert (await client.post("/api/v1/dev/run-jobs", headers=h)).status_code == 404
    # fmt: skip
