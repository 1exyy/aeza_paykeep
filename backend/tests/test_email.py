"""Email channel. aiosmtplib.send is replaced by a fake; no network."""

import uuid
from collections.abc import Iterator

import pytest
from aiosmtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPConnectTimeoutError,
    SMTPDataError,
    SMTPReadTimeoutError,
    SMTPRecipientsRefused,
    SMTPServerDisconnected,
)
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import email as email_channel
from app.channels import get_channels
from app.channels.email import EmailChannel, build_message
from app.core.clock import real_now
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.notification import Delivery, Notification
from app.worker.jobs import dispatch_deliveries
from tests.helpers import ADMIN, bearer, create_recurring, freeze, login

PAYLOAD = {"title": "Сервер (VPS)", "amount": "120.00", "currency": "USD", "due_date": "2026-11-10"}


class FakeSMTP:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.errors: list[Exception | None] = []
        self.refused: dict = {}

    async def __call__(self, message, **kwargs):  # noqa: ANN001, ANN003, ANN204
        self.calls.append({"message": message, **kwargs})
        error = self.errors.pop(0) if self.errors else None
        if error:
            raise error
        return self.refused, "250 OK queued"


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSMTP]:
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_user", "bot@example.test")
    monkeypatch.setattr(settings, "smtp_password", type(settings.smtp_password)("smtp-secret-42"))
    monkeypatch.setattr(settings, "smtp_from", "noreply@example.test")
    monkeypatch.setattr(settings, "email_recipients", "boss@example.test, team@example.test")
    fake = FakeSMTP()
    monkeypatch.setattr(email_channel.aiosmtplib, "send", fake)
    yield fake


def _notification() -> Notification:
    return Notification(
        id=1, event_id=uuid.uuid4(), type="payment.due_soon", occurrence_id=7, payload=PAYLOAD
    )


def test_message(smtp: FakeSMTP) -> None:
    message = build_message(_notification())
    assert message["Subject"] == "Напоминание об оплате: Сервер (VPS) — 120.00 USD до 10.11.2026"
    assert message["To"] == "boss@example.test, team@example.test"
    assert "noreply@example.test" in message["From"]
    body = message.get_content()
    assert (
        "🔔 Напоминание об оплате\nСервер (VPS)\nСумма: 120.00 USD\nСрок оплаты: 10.11.2026" in body
    )


async def test_send_starttls(smtp: FakeSMTP) -> None:
    result = await EmailChannel().send(_notification(), Delivery(id=1, channel="email"))
    assert result.outcome == "sent" and result.external_id and result.error is None
    call = smtp.calls[0]
    assert call["hostname"] == "smtp.example.test" and call["port"] == 587
    assert call["recipients"] == ["boss@example.test", "team@example.test"]
    assert call["start_tls"] is True and call["use_tls"] is False
    assert call["username"] == "bot@example.test" and call["password"] == "smtp-secret-42"


async def test_send_ssl(smtp: FakeSMTP, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "smtp_ssl", True)
    monkeypatch.setattr(get_settings(), "smtp_port", 465)
    await EmailChannel().send(_notification(), Delivery(id=1, channel="email"))
    assert smtp.calls[0]["use_tls"] is True and smtp.calls[0]["start_tls"] is False


async def test_partial_refusal_is_sent_with_note(smtp: FakeSMTP) -> None:
    smtp.refused = {"team@example.test": (550, "no such user")}
    result = await EmailChannel().send(_notification(), Delivery(id=1, channel="email"))
    assert result.outcome == "sent" and result.error == "refused: team@example.test"


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (SMTPConnectError("connection refused"), "failed"),
        (SMTPConnectTimeoutError("connect timeout"), "failed"),
        (SMTPAuthenticationError(535, "authentication failed"), "failed"),
        (SMTPRecipientsRefused([]), "failed"),
        (SMTPDataError(451, "try again later"), "failed"),
        (SMTPServerDisconnected("lost"), "unknown"),
        (SMTPReadTimeoutError("read timeout"), "unknown"),
        (OSError("network down"), "unknown"),
    ],
)
async def test_error_mapping(smtp: FakeSMTP, error: Exception, outcome: str) -> None:
    smtp.errors = [error]
    result = await EmailChannel().send(_notification(), Delivery(id=1, channel="email"))
    assert result.outcome == outcome
    assert "smtp-secret-42" not in (result.error or "")


async def test_no_recipients_fails(smtp: FakeSMTP, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "email_recipients", " , ")
    result = await EmailChannel().send(_notification(), Delivery(id=1, channel="email"))
    assert result.outcome == "failed" and smtp.calls == []


async def test_channel_enabled_by_config(smtp: FakeSMTP, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "email" in get_channels()
    monkeypatch.setattr(get_settings(), "email_recipients", "")
    assert "email" not in get_channels()


async def test_reminder_by_email_retries_without_duplicates(
    client: AsyncClient, db: AsyncSession, smtp: FakeSMTP
) -> None:
    freeze("2026-11-08T10:00:00+03:00")
    h = bearer(await login(client, *ADMIN))
    config = (await client.get("/api/v1/config", headers=h)).json()
    assert config["channels"]["email"] is True and config["channels"]["telegram"] is False

    await create_recurring(client, h, "2026-11-10")  # due in 2 days → immediate reminder
    smtp.errors = [SMTPDataError(451, "temporary failure")]
    async with get_sessionmaker()() as s:
        await dispatch_deliveries(s)
    [d] = (await db.scalars(select(Delivery))).all()
    assert d.channel == "email" and d.status == "pending" and d.attempts == 1
    assert d.last_error == "SMTP 451: temporary failure"

    freeze((d.next_attempt_at.astimezone(real_now().tzinfo)).isoformat())
    async with get_sessionmaker()() as s:
        await dispatch_deliveries(s)
    db.expire_all()
    [d] = (await db.scalars(select(Delivery))).all()
    assert d.status == "sent" and d.attempts == 2
    assert len(smtp.calls) == 2
    assert len((await db.scalars(select(Notification))).all()) == 1
