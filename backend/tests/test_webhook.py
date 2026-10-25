"""Webhook channel and business events. httpx.MockTransport instead of network."""

import hashlib
import hmac
import json
from collections.abc import Callable, Iterator
from datetime import timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import get_channels, set_channels_factory
from app.channels.webhook import WebhookChannel, url_allowed
from app.core import clock
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.notification import Delivery
from app.models.user import User
from app.services.telegram_paid import press_paid
from app.worker.jobs import dispatch_deliveries
from tests.helpers import ADMIN, bearer, create_recurring, freeze, login

URL = "https://hooks.example.test/invoice-keeper"
SECRET = "whsec-test-secret"
OCC = "/api/v1/payment-occurrences"


class Receiver:
    """Fake receiver: records requests, answers from a queue (default 200)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answers: list[Callable[[httpx.Request], httpx.Response]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.answers:
            return self.answers.pop(0)(request)
        return httpx.Response(200, json={"ok": True})

    def events(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]

    def types(self) -> list[str]:
        return [e["type"] for e in self.events()]


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[Receiver]:
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_url", URL)
    monkeypatch.setattr(settings, "webhook_secret", type(settings.webhook_secret)(SECRET))
    receiver = Receiver()
    set_channels_factory(
        lambda: {"webhook": WebhookChannel(transport=httpx.MockTransport(receiver))}
    )
    yield receiver
    set_channels_factory(None)


async def _dispatch() -> None:
    async with get_sessionmaker()() as s:
        await dispatch_deliveries(s)


async def _deliveries(db: AsyncSession) -> list[Delivery]:
    db.expire_all()
    return list(await db.scalars(select(Delivery).order_by(Delivery.id)))


def _expected_signature(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


async def test_body_headers_and_signature(client: AsyncClient, hook: Receiver) -> None:
    freeze("2026-10-24T12:00:00+03:00")
    rp = await create_recurring(client, bearer(await login(client, *ADMIN)), "2026-11-10")
    await _dispatch()
    [request] = hook.requests
    assert str(request.url) == URL and request.method == "POST"
    assert request.headers["content-type"].startswith("application/json")
    assert request.headers["x-invoicekeeper-signature"] == _expected_signature(request.content)
    event = json.loads(request.content)
    assert set(event) == {"event_id", "type", "occurred_at", "data"}
    assert request.headers["x-invoicekeeper-event-id"] == event["event_id"]
    assert (
        event["type"] == "recurring.created" and event["occurred_at"] == "2026-10-24T12:00:00+03:00"
    )
    assert event["data"] == {
        "recurring_payment_id": rp["id"],
        "title": "Сервер (VPS)",
        "amount": "120.00",
        "currency": "USD",
        "periodicity": "monthly",
        "anchor_day": 10,
        "first_due_date": "2026-11-10",
        "status": "active",
        "created_by": "admin",
        "stopped_at": None,
        "assign_all": False,
        "assignees": [],
    }
    assert SECRET not in request.content.decode()


async def test_all_event_types(client: AsyncClient, db: AsyncSession, hook: Receiver) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    h = bearer(await login(client, *ADMIN))
    rp = await create_recurring(client, h, "2026-11-10")  # due in 2 days → also a reminder
    await _dispatch()
    assert sorted(hook.types()) == ["payment.due_soon", "recurring.created"]
    due_soon = next(e for e in hook.events() if e["type"] == "payment.due_soon")
    assert (
        due_soon["data"]["title"] == "Сервер (VPS)" and due_soon["data"]["due_date"] == "2026-11-10"
    )

    occ_id = (await client.get(OCC, headers=h, params={"sort": "due_date"})).json()["items"][0][
        "id"
    ]
    await client.patch(
        f"{OCC}/{occ_id}", json={"status": "paid", "paid_date": "2026-11-08"}, headers=h
    )
    await client.patch(f"{OCC}/{occ_id}", json={"paid_date": "2026-11-07"}, headers=h)  # no event
    await client.patch(f"{OCC}/{occ_id}", json={"status": "unpaid"}, headers=h)
    await db.execute(update(User).where(User.login == "admin").values(telegram_user_id=555))
    await db.commit()
    async with get_sessionmaker()() as s:
        await press_paid(s, 555, occ_id)
    await client.delete(f"/api/v1/recurring-payments/{rp['id']}", headers=h)
    await _dispatch()

    assert hook.types()[2:] == [
        "occurrence.paid",
        "occurrence.unpaid",
        "occurrence.paid",
        "recurring.stopped",
    ]
    paid_web, unpaid, paid_tg, stopped = hook.events()[2:]
    assert paid_web["data"]["paid_via"] == "web" and paid_web["data"]["paid_date"] == "2026-11-08"
    assert unpaid["data"]["status"] == "unpaid" and unpaid["data"]["paid_date"] is None
    assert paid_tg["data"]["paid_via"] == "telegram" and paid_tg["data"]["paid_by"] == "admin"
    assert stopped["data"]["status"] == "stopped" and stopped["data"]["stopped_at"]
    assert len({e["event_id"] for e in hook.events()}) == len(hook.events())


async def test_retry_keeps_event_id_body_and_signature(
    client: AsyncClient, db: AsyncSession, hook: Receiver
) -> None:
    freeze("2026-10-24T12:00:00+03:00")
    await create_recurring(client, bearer(await login(client, *ADMIN)), "2026-11-10")
    hook.answers = [lambda r: httpx.Response(500)]
    await _dispatch()
    [d] = await _deliveries(db)
    assert d.status == "pending" and d.last_error == "webhook HTTP 500"
    moment = d.next_attempt_at + timedelta(seconds=1)
    clock.set_real_now(lambda: moment)
    await _dispatch()
    first, second = hook.requests
    assert first.content == second.content
    assert first.headers["x-invoicekeeper-signature"] == second.headers["x-invoicekeeper-signature"]
    assert first.headers["x-invoicekeeper-event-id"] == second.headers["x-invoicekeeper-event-id"]
    [d] = await _deliveries(db)
    assert d.status == "sent" and d.attempts == 2


def _raise(error: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        raise error

    return answer


@pytest.mark.parametrize(
    "answer",
    [
        _raise(httpx.ConnectError("refused")),
        _raise(httpx.ReadTimeout("timeout")),  # the receiver dedupes by event_id → retry is safe
        lambda r: httpx.Response(400),
        lambda r: httpx.Response(503),
    ],
)
async def test_non_2xx_and_network_errors_are_retried(
    client: AsyncClient, db: AsyncSession, hook: Receiver, answer: Callable
) -> None:
    freeze("2026-10-24T12:00:00+03:00")
    await create_recurring(client, bearer(await login(client, *ADMIN)), "2026-11-10")
    hook.answers = [answer] * 5
    for attempt in range(1, 6):
        await _dispatch()
        [d] = await _deliveries(db)
        assert d.attempts == attempt
        if attempt < 5:
            assert d.status == "pending"
            moment = d.next_attempt_at + timedelta(seconds=1)
            clock.set_real_now(lambda m=moment: m)
    assert d.status == "failed"


async def test_429_respects_retry_after(
    client: AsyncClient, db: AsyncSession, hook: Receiver
) -> None:
    freeze("2026-10-24T12:00:00+03:00")
    await create_recurring(client, bearer(await login(client, *ADMIN)), "2026-11-10")
    hook.answers = [lambda r: httpx.Response(429, headers={"Retry-After": "9"})]
    await _dispatch()
    [d] = await _deliveries(db)
    assert d.next_attempt_at == clock.real_now() + timedelta(seconds=9)


async def test_payment_cancels_reminder_but_not_events(
    client: AsyncClient, db: AsyncSession, hook: Receiver
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    h = bearer(await login(client, *ADMIN))
    await create_recurring(client, h, "2026-11-10")
    occ_id = (await client.get(OCC, headers=h, params={"sort": "due_date"})).json()["items"][0][
        "id"
    ]
    await client.patch(
        f"{OCC}/{occ_id}", json={"status": "paid", "paid_date": "2026-11-08"}, headers=h
    )
    await _dispatch()
    assert sorted(hook.types()) == ["occurrence.paid", "recurring.created"]
    page = (
        await client.get(
            "/api/v1/notifications/deliveries", headers=h, params={"channel": "webhook"}
        )
    ).json()
    by_type = {i["notification_type"]: i["status"] for i in page["items"]}
    assert by_type == {
        "payment.due_soon": "failed",
        "recurring.created": "sent",
        "occurrence.paid": "sent",
    }


def test_url_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    assert url_allowed("https://a.example/x", dev_mode=False)
    assert not url_allowed("http://a.example/x", dev_mode=False)
    assert url_allowed("http://webhook-sink:9000/", dev_mode=True)
    assert not url_allowed("ftp://a.example/x", dev_mode=True)
    assert not url_allowed("https://", dev_mode=True)
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_url", "http://webhook-sink:9000/hook")
    monkeypatch.setattr(settings, "dev_mode", False)
    assert "webhook" not in get_channels()
    monkeypatch.setattr(settings, "dev_mode", True)
    assert "webhook" in get_channels()


async def test_webhook_sink_checks_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.devtools.webhook_sink import app as sink

    monkeypatch.setattr(
        get_settings(), "webhook_secret", type(get_settings().webhook_secret)(SECRET)
    )
    body = b'{"event_id":"e1","type":"recurring.created","data":{}}'
    async with AsyncClient(transport=httpx.ASGITransport(app=sink), base_url="http://sink") as c:
        ok = await c.post(
            "/hook", content=body, headers={"X-InvoiceKeeper-Signature": _expected_signature(body)}
        )
        bad = await c.post(
            "/hook",
            content=body + b" ",
            headers={"X-InvoiceKeeper-Signature": _expected_signature(body)},
        )
    assert ok.json() == {"ok": True} and bad.json() == {"ok": False}
