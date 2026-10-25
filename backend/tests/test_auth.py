from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import get_settings
from app.models.audit_event import AuditEvent
from app.models.user import User, UserSession
from app.services.bootstrap import ensure_admin
from tests.helpers import ADMIN, bearer, create_user, freeze, login


async def test_login_sets_cookie_and_returns_token(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login", json={"team": "aeza", "login": "ADMIN", "password": ADMIN[1]}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["login"] == "admin"
    assert body["user"]["role"] == "admin"
    assert body["user"]["is_protected"] is True
    assert body["session"]["expires_at"].endswith("+03:00")
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("ik_session=")
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower() and "Path=/" in cookie
    assert body["session"]["token"] in cookie


async def test_me_with_cookie_and_with_bearer(client: AsyncClient) -> None:
    token = await login(client, *ADMIN)
    assert (await client.get("/api/v1/auth/me")).json()["login"] == "admin"  # cookie
    client.cookies.clear()
    r = await client.get("/api/v1/auth/me", headers=bearer(token))
    assert r.status_code == 200
    assert r.json()["login"] == "admin"


async def test_me_without_session_is_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    r = await client.get("/api/v1/auth/me", headers=bearer("garbage"))
    assert r.status_code == 401


async def test_wrong_password_and_unknown_login(client: AsyncClient, db: AsyncSession) -> None:
    for creds in (
        {"team": "aeza", "login": "admin", "password": "nope-nope"},
        {"team": "aeza", "login": "ghost", "password": "x"},
    ):
        r = await client.post("/api/v1/auth/login", json=creds)
        assert r.status_code == 401
        assert r.json() == {
            "error": {
                "code": "invalid_credentials",
                "message": "Неверная команда, логин или пароль",
            }
        }
    events = (await db.scalars(select(AuditEvent).order_by(AuditEvent.id))).all()
    assert [(e.action, e.result, e.details) for e in events] == [
        ("auth.login_failed", "failure", {"team": "aeza", "login": "admin"}),
        ("auth.login_failed", "failure", {"team": "aeza", "login": "ghost"}),
    ]


async def test_login_validation(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/login", json={"team": "aeza", "login": "admin"})
    assert r.status_code == 422
    assert r.json()["error"]["details"] == [{"field": "password", "message": "Обязательное поле"}]


async def test_logout_revokes_session_and_is_idempotent(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await login(client, *ADMIN)
    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 204
    assert 'ik_session=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert (await client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 401
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    actions = (await db.scalars(select(AuditEvent.action).order_by(AuditEvent.id))).all()
    assert actions == ["auth.login", "auth.logout"]


async def test_session_expires_after_7_days(client: AsyncClient) -> None:
    freeze("2026-10-24T10:00:00+03:00")
    token = await login(client, *ADMIN)
    client.cookies.clear()
    freeze("2026-10-31T09:59:59+03:00")
    assert (await client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 200
    freeze("2026-10-31T10:00:01+03:00")
    assert (await client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 401


async def test_dev_clock_shift_does_not_expire_session(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await login(client, *ADMIN)
    await clock.set_offset_days(db, 40)
    await db.commit()
    assert (await client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 200


async def test_rate_limit_5_failures_in_5_minutes(client: AsyncClient) -> None:
    freeze("2026-10-24T10:00:00+03:00")
    for _ in range(5):
        r = await client.post(
            "/api/v1/auth/login", json={"team": "aeza", "login": "admin", "password": "bad"}
        )
        assert r.status_code == 401
    freeze("2026-10-24T10:01:00+03:00")
    r = await client.post(
        "/api/v1/auth/login", json={"team": "aeza", "login": "admin", "password": ADMIN[1]}
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_attempts"
    assert int(r.headers["retry-after"]) == 240
    freeze("2026-10-24T10:05:01+03:00")
    r = await client.post(
        "/api/v1/auth/login", json={"team": "aeza", "login": "admin", "password": ADMIN[1]}
    )
    assert r.status_code == 200


async def test_rate_limit_is_per_login(client: AsyncClient, db: AsyncSession) -> None:
    await create_user(db, "anna", "anna-password")
    for _ in range(5):
        await client.post(
            "/api/v1/auth/login", json={"team": "aeza", "login": "admin", "password": "bad"}
        )
    assert (
        await client.post(
            "/api/v1/auth/login", json={"team": "aeza", "login": "admin", "password": "x"}
        )
    ).status_code == 429
    await login(client, "anna", "anna-password")


async def test_secrets_not_in_audit_or_responses(client: AsyncClient, db: AsyncSession) -> None:
    token = await login(client, *ADMIN)
    await client.post(
        "/api/v1/auth/login", json={"team": "aeza", "login": "admin", "password": "wrong-secret"}
    )
    me = await client.get("/api/v1/auth/me")
    body = me.json()
    assert "password_hash" not in body and ADMIN[1] not in me.text and "$argon2" not in me.text
    assert [k for k in body if "password" in k] == ["must_change_password"]
    for event in (await db.scalars(select(AuditEvent))).all():
        dumped = str(event.details)
        assert token not in dumped and "wrong-secret" not in dumped and ADMIN[1] not in dumped
    stored = (await db.scalars(select(UserSession.token_hash))).all()
    assert token not in stored


async def test_admin_upsert_from_env(client: AsyncClient, db: AsyncSession, monkeypatch) -> None:
    token = await login(client, *ADMIN)
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_password", type(settings.admin_password)("new-admin-pass"))
    await ensure_admin(db)
    admins = (await db.scalars(select(User).where(User.role == "admin"))).all()
    assert len(admins) == 1 and admins[0].is_protected
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 401
    await login(client, "admin", "new-admin-pass")
