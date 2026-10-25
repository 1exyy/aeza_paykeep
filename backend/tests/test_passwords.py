"""Changing passwords: one's own with the current one, the admin for members."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.bootstrap import ensure_admin, ensure_supervisor
from tests.helpers import ADMIN, bearer, create_user, freeze, login

P = "/api/v1/auth/password"
NOW = "2026-11-10T12:00:00+03:00"


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
    body = {"current_password": ADMIN[1], "new_password": "admin-own-password"}
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


async def test_supervisor_keeps_a_changed_password(client: AsyncClient, db: AsyncSession) -> None:
    freeze(NOW)
    h = bearer(await login(client, "boss", "boss-test-password", team=""))
    client.cookies.clear()
    body = {"current_password": "boss-test-password", "new_password": "boss-own-password"}
    assert (await client.post(P, json=body, headers=h)).status_code == 200
    await ensure_supervisor(db)
    await login(client, "boss", "boss-own-password", team="")


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
