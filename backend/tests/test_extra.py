"""Extra channel: Slack-compatible incoming webhook. httpx.MockTransport."""

import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import get_channels, set_channels_factory
from app.channels.extra import ExtraChannel
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.notification import Delivery
from app.worker.jobs import dispatch_deliveries
from tests.helpers import ADMIN, bearer, create_recurring, freeze, login

URL = "https://hooks.slack.example.test/services/T000/B000/XXXX"


class Receiver:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answers: list[Callable[[httpx.Request], httpx.Response]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answers.pop(0)(request) if self.answers else httpx.Response(200, text="ok")


@pytest.fixture
def slack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Receiver]:
    monkeypatch.setattr(get_settings(), "extra_channel_url", URL)
    receiver = Receiver()
    set_channels_factory(lambda: {"extra": ExtraChannel(transport=httpx.MockTransport(receiver))})
    yield receiver
    set_channels_factory(None)


async def _remind(client: AsyncClient) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    await create_recurring(client, bearer(await login(client, *ADMIN)), "2026-11-10")
    async with get_sessionmaker()() as s:
        await dispatch_deliveries(s)


async def _delivery(db: AsyncSession) -> Delivery:
    db.expire_all()
    [d] = (await db.scalars(select(Delivery))).all()
    return d


async def test_sends_slack_text(client: AsyncClient, db: AsyncSession, slack: Receiver) -> None:
    await _remind(client)
    [request] = slack.requests
    assert str(request.url) == URL
    assert json.loads(request.content) == {
        "text": "🔔 Напоминание об оплате\nСервер (VPS)\nСумма: 120.00 USD\nСрок оплаты: 10.11.2026"
    }
    d = await _delivery(db)
    assert d.channel == "extra" and d.status == "sent"


def _raise(error: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        raise error

    return answer


@pytest.mark.parametrize(
    ("answer", "status", "error"),
    [
        (_raise(httpx.ConnectError("refused")), "pending", "extra connect: ConnectError"),
        (_raise(httpx.ConnectTimeout("slow")), "pending", "extra connect: ConnectTimeout"),
        (lambda r: httpx.Response(500), "pending", "extra HTTP 500"),
        (lambda r: httpx.Response(404, text="no_service"), "pending", "extra HTTP 404"),
        (_raise(httpx.ReadTimeout("no answer")), "unknown", "extra no result: ReadTimeout"),
        (
            _raise(httpx.RemoteProtocolError("closed")),
            "unknown",
            "extra no result: RemoteProtocolError",
        ),
    ],
)
async def test_outcomes(
    client: AsyncClient,
    db: AsyncSession,
    slack: Receiver,
    answer: Callable,
    status: str,
    error: str,
) -> None:
    slack.answers = [answer]
    await _remind(client)
    d = await _delivery(db)
    assert d.status == status and d.last_error == error and d.attempts == 1


async def test_429_waits(client: AsyncClient, db: AsyncSession, slack: Receiver) -> None:
    slack.answers = [lambda r: httpx.Response(429, headers={"Retry-After": "30"})]
    await _remind(client)
    d = await _delivery(db)
    assert (
        d.status == "pending" and (d.next_attempt_at - d.sending_started_at).total_seconds() == 30
    )


async def test_only_reminders() -> None:
    channel = ExtraChannel()
    assert channel.handles("payment.due_soon")
    assert not channel.handles("occurrence.paid") and not channel.handles("recurring.created")


def test_enabled_by_config(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "extra_channel_url", URL)
    assert "extra" in get_channels()
    monkeypatch.setattr(settings, "extra_channel_url", "http://mattermost.local/hooks/x")
    monkeypatch.setattr(settings, "dev_mode", False)
    assert "extra" not in get_channels()
    monkeypatch.setattr(settings, "extra_channel_url", "")
    assert "extra" not in get_channels()


async def test_config_shows_extra(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "extra_channel_url", URL)
    h = bearer(await login(client, *ADMIN))
    assert (await client.get("/api/v1/config", headers=h)).json()["channels"]["extra"] is True
