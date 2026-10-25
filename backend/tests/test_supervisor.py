"""Supervisor, team applications and temporary passwords."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock
from app.core.errors import AppError
from app.models.app_settings import AppSettings
from app.models.team import Team
from app.models.user import User
from app.schemas.application import ApplicationInput
from app.services import applications
from tests.helpers import ADMIN, bearer, freeze, login
from tests.test_contract import check

SUP = ("boss", "boss-test-password")
A = "/api/v1/supervisor/applications"
NOW = "2026-11-10T12:00:00+03:00"


async def _submit(db: AsyncSession, team: str = "Beta Team", applicant: int = 5001, **kw):
    data = ApplicationInput.model_validate(
        {"team_name": team, "admin_login": "Chief", "telegram_chat_id": "-1001234567890"} | kw
    )
    application = await applications.submit(
        db,
        await get_clock(db),
        data,
        applicant_telegram_id=applicant,
        applicant_username="chief_tg",
        applicant_name="Chief Person",
    )
    await db.commit()
    return application


async def _supervisor(client: AsyncClient) -> dict:
    h = bearer(await login(client, *SUP, team=""))
    client.cookies.clear()
    return h


async def test_supervisor_has_only_applications(client: AsyncClient) -> None:
    freeze(NOW)
    h = await _supervisor(client)
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    assert me["role"] == "supervisor" and me["must_change_password"] is False
    assert (await client.get(A, headers=h)).status_code == 200
    for url in (
        "/api/v1/payment-occurrences",
        "/api/v1/config",
        "/api/v1/users",
        "/api/v1/audit-log",
    ):
        assert (await client.get(url, headers=h)).status_code == 403, url
    # the supervisor is not inside a team, and a team admin has no access to applications
    r = await client.post(
        "/api/v1/auth/login", json={"team": "aeza", "login": "boss", "password": SUP[1]}
    )
    assert r.status_code == 401
    ha = bearer(await login(client, *ADMIN))
    client.cookies.clear()
    assert (await client.get(A, headers=ha)).status_code == 403
    r = await client.post(
        "/api/v1/auth/login", json={"team": "", "login": "admin", "password": ADMIN[1]}
    )
    assert r.status_code == 401


async def test_approve_creates_team_and_temp_password(
    client: AsyncClient, db: AsyncSession
) -> None:
    freeze(NOW)
    smtp = {
        "host": "smtp-relay.brevo.com",
        "port": 2525,
        "user": "u@smtp",
        "password": "p-secret",
        "from": "b@beta.example",
        "recipients": ["boss@beta.example"],
    }
    application = await _submit(db, smtp=smtp)
    h = await _supervisor(client)

    listed = check("/supervisor/applications", "get", await client.get(A, headers=h))
    assert listed["total"] == 1
    item = listed["items"][0]
    assert item["team_name"] == "Beta Team" and item["admin_login"] == "chief"
    assert item["smtp"]["password_set"] is True and "p-secret" not in str(listed)
    assert item["applicant"] == {
        "telegram_id": 5001,
        "username": "chief_tg",
        "name": "Chief Person",
    }

    r = await client.post(f"{A}/{application.id}/approve", headers=h)
    body = check("/supervisor/applications/{id}/approve", "post", r)
    assert body["application"]["status"] == "approved" and body["notified"] is False
    password = body["temp_password"]
    assert password and len(password) >= 8

    team = await db.scalar(select(Team).where(Team.slug == "beta team"))
    assert team is not None
    admin = await db.scalar(select(User).where(User.team_id == team.id))
    assert admin and admin.role == "admin" and admin.is_protected and admin.must_change_password
    assert admin.telegram_user_id == 5001
    settings = await db.get(AppSettings, team.id)
    assert settings and settings.values["telegram_chat_id"] == "-1001234567890"
    assert settings.values["smtp_host"] == "smtp-relay.brevo.com"
    assert settings.values["smtp_port"] == 2525

    # first login: only the password change is allowed
    hb = bearer(await login(client, "chief", password, team="beta team"))
    client.cookies.clear()
    me = (await client.get("/api/v1/auth/me", headers=hb)).json()
    assert me["must_change_password"] is True
    r = await client.get("/api/v1/payment-occurrences", headers=hb)
    assert r.status_code == 403 and r.json()["error"]["code"] == "password_change_required"
    P = "/api/v1/auth/password"
    wrong = {"current_password": "wrong", "new_password": "brand-new-pass"}
    assert (await client.post(P, json=wrong, headers=hb)).status_code == 422
    same = {"current_password": password, "new_password": password}
    assert (await client.post(P, json=same, headers=hb)).status_code == 422
    good = {"current_password": password, "new_password": "brand-new-pass"}
    r = await client.post(P, json=good, headers=hb)
    assert check("/auth/password", "post", r)["must_change_password"] is False
    assert (await client.get("/api/v1/payment-occurrences", headers=hb)).status_code == 200
    cfg = (await client.get("/api/v1/config", headers=hb)).json()
    assert cfg["team"]["name"] == "Beta Team" and cfg["channels"]["email"] is True
    ns = (await client.get("/api/v1/settings/notifications", headers=hb)).json()
    assert ns["telegram_chat_id"] == "-1001234567890" and ns["smtp_password_set"] is True

    # decided once
    r = await client.post(f"{A}/{application.id}/approve", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "application_decided"


async def test_reject_and_notify(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze(NOW)
    sent: list[tuple[int, str]] = []

    async def fake_send(chat_id: int, text: str) -> bool:
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(applications, "send_to_applicant", fake_send)
    first = await _submit(db, "Gamma", applicant=7001)
    second = await _submit(db, "Delta", applicant=7002)
    h = await _supervisor(client)

    r = await client.post(f"{A}/{first.id}/reject", json={"reason": "  "}, headers=h)
    assert r.status_code == 422
    r = await client.post(
        f"{A}/{first.id}/reject", json={"reason": "Нет данных о компании"}, headers=h
    )
    body = check("/supervisor/applications/{id}/reject", "post", r)
    assert body["application"]["status"] == "rejected" and body["notified"] is True
    assert sent[-1][0] == 7001 and "Нет данных о компании" in sent[-1][1]

    r = await client.post(f"{A}/{second.id}/approve", headers=h)
    body = r.json()
    assert body["notified"] is True and body["temp_password"] is None
    assert sent[-1][0] == 7002 and "Временный пароль:" in sent[-1][1] and "Delta" in sent[-1][1]

    assert (await client.get(A, headers=h)).json()["total"] == 0
    everything = (await client.get(A, params={"status": "all"}, headers=h)).json()
    assert {i["status"] for i in everything["items"]} == {"approved", "rejected"}


async def test_names_and_one_open_application(client: AsyncClient, db: AsyncSession) -> None:
    freeze(NOW)
    await client.get("/api/v1/auth/me")  # the API started: the first team exists
    with pytest.raises(AppError) as taken:
        await _submit(db, "  AEZA ")
    assert taken.value.code == "team_name_taken"
    await _submit(db, "Omega", applicant=9001)
    with pytest.raises(AppError) as busy:
        await _submit(db, "Other", applicant=9001)
    assert busy.value.code == "application_pending"
    with pytest.raises(AppError) as twice:
        await _submit(db, "omega", applicant=9002)
    assert twice.value.code == "team_name_taken"
    with pytest.raises(ValueError):
        ApplicationInput.model_validate(
            {"team_name": "x", "admin_login": "chief", "telegram_chat_id": "-100"}
        )
    with pytest.raises(ValueError):
        ApplicationInput.model_validate(
            {"team_name": "Good", "admin_login": "a", "telegram_chat_id": "-100"}
        )
