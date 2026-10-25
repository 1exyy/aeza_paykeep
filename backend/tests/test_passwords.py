"""Changing passwords: one's own with the current one, the admin for members."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, totp
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.services.bootstrap import ensure_admin
from tests.helpers import ADMIN, bearer, create_user, freeze, login

P = "/api/v1/auth/password"
NOW = "2026-11-10T12:00:00+03:00"


def otp(secret: str) -> str:
    return totp._code(secret, int(clock.real_now().timestamp()) // 30)


async def enroll_admin(client: AsyncClient, headers: dict[str, str], password: str) -> str:
    started = await client.post(
        "/api/v1/auth/me/totp/begin", json={"current_password": password}, headers=headers
    )
    assert started.status_code == 200
    secret = started.json()["secret"]
    assert secret in started.json()["otpauth_uri"]
    confirmed = await client.post(
        "/api/v1/auth/me/totp/confirm", json={"code": otp(secret)}, headers=headers
    )
    assert confirmed.status_code == 200 and confirmed.json()["totp_enabled"] is True
    return secret


async def test_member_changes_own_password(client: AsyncClient, db: AsyncSession) -> None:
    freeze(NOW)
    await create_user(db, "anna", "anna-old-password")
    h = bearer(await login(client, "anna", "anna-old-password"))
    client.cookies.clear()
    other = bearer(await login(client, "anna", "anna-old-password"))  # a second device
    client.cookies.clear()
    body = {"current_password": "anna-old-password", "new_password": "anna-new-password"}
    assert (await client.post(P, json=body, headers=h)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 200  # this session
    assert (await client.get("/api/v1/auth/me", headers=other)).status_code == 401  # others out
    r = await client.post(
        "/api/v1/auth/login",
        json={"team": "aeza", "login": "anna", "password": "anna-old-password"},
    )
    assert r.status_code == 401
    await login(client, "anna", "anna-new-password")


async def test_env_admin_keeps_a_changed_password(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze(NOW)
    h = bearer(await login(client, *ADMIN))
    client.cookies.clear()
    missing = {"current_password": ADMIN[1], "new_password": "admin-own-password"}
    blocked = await client.post(P, json=missing, headers=h)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "totp_required"
    secret = await enroll_admin(client, h, ADMIN[1])
    freeze("2026-11-10T12:00:31+03:00")
    body = {**missing, "totp_code": otp(secret)}
    assert (await client.post(P, json=body, headers=h)).status_code == 200

    await ensure_admin(db)  # an API restart with the same .env
    await login(client, "admin", "admin-own-password")
    client.cookies.clear()

    # changing ADMIN_PASSWORD in .env still resets it
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-reset-from-env")
    get_settings.cache_clear()
    try:
        await ensure_admin(db)
        await login(client, "admin", "admin-reset-from-env")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


async def test_admin_totp_is_required_single_use_and_limited(client: AsyncClient) -> None:
    freeze(NOW)
    admin = bearer(await login(client, *ADMIN))
    client.cookies.clear()
    member_login = "anna"
    async with get_sessionmaker()() as db:
        await create_user(db, member_login, "anna-password")
    member = bearer(await login(client, member_login, "anna-password"))
    client.cookies.clear()
    assert (
        await client.post(
            "/api/v1/auth/me/totp/begin",
            json={"current_password": "anna-password"},
            headers=member,
        )
    ).status_code == 403
    secret = await enroll_admin(client, admin, ADMIN[1])
    body = {"current_password": ADMIN[1], "new_password": "new-admin-password"}
    assert (await client.post(P, json=body, headers=admin)).status_code == 422
    body["totp_code"] = otp(secret)  # enrollment consumed this time step
    assert (await client.post(P, json=body, headers=admin)).status_code == 422
    freeze("2026-11-10T12:00:31+03:00")
    body["totp_code"] = "000000" if otp(secret) != "000000" else "999999"
    for _ in range(4):  # the reused code above was the first of five failures
        assert (await client.post(P, json=body, headers=admin)).status_code == 422
    body["totp_code"] = otp(secret)
    assert (await client.post(P, json=body, headers=admin)).status_code == 429
    freeze("2026-11-10T12:05:32+03:00")
    body["totp_code"] = otp(secret)
    assert (await client.post(P, json=body, headers=admin)).status_code == 200


async def test_supervisor_cannot_change_password(client: AsyncClient) -> None:
    freeze(NOW)
    h = bearer(await login(client, "boss", "boss-test-password", team=""))
    client.cookies.clear()
    body = {"current_password": "boss-test-password", "new_password": "boss-own-password"}
    assert (await client.post(P, json=body, headers=h)).status_code == 403
    await login(client, "boss", "boss-test-password", team="")


async def test_admin_sets_member_password(client: AsyncClient, db: AsyncSession) -> None:
    freeze(NOW)
    anna = await create_user(db, "anna", "anna-old-password")
    member = bearer(await login(client, "anna", "anna-old-password"))
    client.cookies.clear()
    admin = bearer(await login(client, *ADMIN))
    client.cookies.clear()

    r = await client.patch(
        f"/api/v1/users/{anna.id}", json={"password": "temp-from-admin"}, headers=admin
    )
    assert r.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=member)).status_code == 401  # signed out

    h = bearer(await login(client, "anna", "temp-from-admin"))
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me", headers=h)).json()["must_change_password"] is True
    r = await client.get("/api/v1/payment-occurrences", headers=h)
    assert r.json()["error"]["code"] == "password_change_required"
    body = {"current_password": "temp-from-admin", "new_password": "anna-own-password"}
    assert (await client.post(P, json=body, headers=h)).status_code == 200
    assert (await client.get("/api/v1/payment-occurrences", headers=h)).status_code == 200

    # a member cannot change someone else's password
    r = await client.patch(f"/api/v1/users/{anna.id}", json={"password": "x" * 10}, headers=h)
    assert r.status_code == 403
