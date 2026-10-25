"""Notification settings in the app."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import email as email_channel
from app.channels import get_channels
from app.core.config import apply_overrides, get_settings
from app.models.audit_event import AuditEvent
from app.services import notification_settings
from tests.helpers import ADMIN, bearer, create_user, login
from tests.test_contract import check

S = "/api/v1/settings/notifications"


async def test_get_defaults_from_env(client: AsyncClient) -> None:
    h = bearer(await login(client, *ADMIN))
    body = check("/settings/notifications", "get", await client.get(S, headers=h))
    assert body["version"] == 0 and body["updated_by"] is None
    assert "smtp_password" not in body and "webhook_secret" not in body
    assert set(body["channels"]) == {"telegram", "email", "webhook"}


async def test_admin_saves_smtp_and_channel_turns_on(client: AsyncClient, db: AsyncSession) -> None:
    h = bearer(await login(client, *ADMIN))
    r = await client.patch(
        S,
        json={
            "smtp_host": "smtp-relay.brevo.com",
            "smtp_port": 2525,
            "smtp_security": "starttls",
            "smtp_user": "a1b2@smtp-brevo.com",
            "smtp_password": "super-secret",
            "smtp_from": "billing@example.com",
            "email_recipients": ["admin@example.com", " buh@example.com ", "admin@example.com"],
        },
        headers=h,
    )
    body = check("/settings/notifications", "patch", r)
    assert body["smtp_host"] == "smtp-relay.brevo.com" and body["smtp_port"] == 2525
    assert body["smtp_password_set"] is True and "super-secret" not in r.text
    assert body["email_recipients"] == ["admin@example.com", "buh@example.com"]
    assert body["channels"]["email"] is True and body["version"] == 1
    assert get_settings().smtp_password.get_secret_value() == "super-secret"
    assert "email" in get_channels()

    event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "settings.update"))
    assert event is not None and "smtp_password" in event.details["changed"]
    assert "super-secret" not in str(event.details)

    # another process (the worker) picks the values up from the database
    apply_overrides({})
    assert get_settings().smtp_host != "smtp-relay.brevo.com"
    await notification_settings.refresh(db)
    assert get_settings().smtp_host == "smtp-relay.brevo.com"

    # '' clears: the channel turns off
    body = (await client.patch(S, json={"smtp_host": ""}, headers=h)).json()
    assert body["channels"]["email"] is False


async def test_validation_and_access(client: AsyncClient, db: AsyncSession) -> None:
    h = bearer(await login(client, *ADMIN))
    for payload, field in [
        ({"webhook_url": "ftp://example.com/hook"}, "webhook_url"),
        ({"email_recipients": ["not-an-email"]}, "email_recipients"),
        ({"telegram_chat_id": "chat"}, "telegram_chat_id"),
        ({"smtp_port": 0}, "smtp_port"),
        ({"smtp_host": "bad host"}, "smtp_host"),
    ]:
        r = await client.patch(S, json=payload, headers=h)
        assert r.status_code == 422, payload
        assert field in [d["field"] for d in r.json()["error"]["details"]], r.text
    assert (await client.patch(S, json={}, headers=h)).status_code == 422
    assert (await client.patch(S, json={"bot_token": "x"}, headers=h)).status_code == 422
    ok = await client.patch(S, json={"telegram_chat_id": "-1004331177965"}, headers=h)
    assert ok.json()["telegram_chat_id"] == "-1004331177965"
    stale = await client.patch(S, json={"smtp_port": 25, "expected_version": 0}, headers=h)
    assert stale.status_code == 409

    await create_user(db, "anna", "anna-password")
    await db.commit()
    client.cookies.clear()
    hu = bearer(await login(client, "anna", "anna-password"))
    assert (await client.get(S, headers=hu)).status_code == 403


async def test_test_email(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    h = bearer(await login(client, *ADMIN))
    sent: list[list[str]] = []

    async def fake(message, **kwargs):  # type: ignore[no-untyped-def]
        sent.append(kwargs["recipients"])
        assert kwargs["hostname"] == "smtp.example.com" and kwargs["port"] == 2525
        return {}, "250 OK"

    monkeypatch.setattr(email_channel.aiosmtplib, "send", fake)
    r = await client.post(f"{S}/test", json={"channel": "email"}, headers=h)
    assert r.json()["ok"] is False and r.json()["error"]  # nothing configured yet
    await client.patch(
        S,
        json={
            "smtp_host": "smtp.example.com",
            "smtp_port": 2525,
            "email_recipients": ["a@example.com"],
        },
        headers=h,
    )
    r = await client.post(f"{S}/test", json={"channel": "email"}, headers=h)
    body = check("/settings/notifications/test", "post", r)
    assert body == {"channel": "email", "ok": True, "error": None}
    assert sent == [["a@example.com"]]
