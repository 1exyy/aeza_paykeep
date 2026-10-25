from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent
from app.models.user import User
from tests.helpers import ADMIN, bearer, login

U = "/api/v1/users"
ANNA = {"login": "anna", "password": "anna-demo-123"}


async def _admin(client: AsyncClient) -> dict[str, str]:
    return bearer(await login(client, *ADMIN))


async def _create(client: AsyncClient, h: dict[str, str], body: dict = ANNA) -> dict:
    r = await client.post(U, json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_list_and_admin_hidden(client: AsyncClient) -> None:
    h = await _admin(client)
    anna = await _create(client, h, {"login": "Anna", "password": "anna-demo-123"})
    assert anna["login"] == "anna" and anna["role"] == "user" and anna["is_protected"] is False
    assert anna["telegram_linked"] is False
    page = (await client.get(U, headers=h)).json()
    assert page["total"] == 1 and [u["login"] for u in page["items"]] == ["anna"]
    assert page["limit"] == 50 and page["offset"] == 0


async def test_create_validation(client: AsyncClient) -> None:
    h = await _admin(client)
    r = await client.post(U, json={"login": "a!", "password": "short"}, headers=h)
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert fields == {"login", "password"}
    assert "short" not in r.text
    r = await client.post(U, json={**ANNA, "role": "admin"}, headers=h)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "field_not_allowed"


async def test_duplicate_login_409_case_insensitive(client: AsyncClient) -> None:
    h = await _admin(client)
    await _create(client, h)
    r = await client.post(U, json={"login": "ANNA", "password": "anna-demo-123"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "login_taken"
    r = await client.post(U, json={"login": "admin", "password": "anna-demo-123"}, headers=h)
    assert r.status_code == 409


async def test_patch_login_keeps_sessions_password_revokes(client: AsyncClient) -> None:
    h = await _admin(client)
    uid = (await _create(client, h))["id"]
    anna_token = await login(client, *ANNA.values())
    client.cookies.clear()

    r = await client.patch(f"{U}/{uid}", json={"login": "anna2", "expected_version": 1}, headers=h)
    assert r.status_code == 200 and r.json()["login"] == "anna2"
    assert (await client.get("/api/v1/auth/me", headers=bearer(anna_token))).status_code == 200

    stale = {"password": "new-pass-123", "expected_version": 1}
    r = await client.patch(f"{U}/{uid}", json=stale, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "version_conflict"
    r = await client.patch(f"{U}/{uid}", json={"password": "new-pass-123"}, headers=h)
    assert r.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=bearer(anna_token))).status_code == 401
    client.cookies.clear()
    await login(client, "anna2", "new-pass-123")


async def test_patch_errors(client: AsyncClient) -> None:
    h = await _admin(client)
    a = await _create(client, h)
    await _create(client, h, {"login": "boris", "password": "boris-demo-123"})
    r = await client.patch(f"{U}/{a['id']}", json={"login": "boris"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "login_taken"
    r = await client.patch(f"{U}/{a['id']}", json={}, headers=h)
    assert r.status_code == 422
    r = await client.patch(f"{U}/999", json={"login": "zzz"}, headers=h)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = await client.patch(f"{U}/{a['id']}", json={"role": "admin"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "field_not_allowed"


async def test_admin_protected(client: AsyncClient) -> None:
    h = await _admin(client)
    admin_id = (await client.get("/api/v1/auth/me", headers=h)).json()["id"]
    r = await client.patch(f"{U}/{admin_id}", json={"password": "hacked-pass-1"}, headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_protected"
    r = await client.delete(f"{U}/{admin_id}", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_protected"
    client.cookies.clear()
    await login(client, *ADMIN)


async def test_delete_soft_revokes_and_frees_login(client: AsyncClient, db: AsyncSession) -> None:
    h = await _admin(client)
    uid = (await _create(client, h))["id"]
    anna_token = await login(client, *ANNA.values())
    client.cookies.clear()
    assert (await client.delete(f"{U}/{uid}", headers=h)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=bearer(anna_token))).status_code == 401
    r = await client.post("/api/v1/auth/login", json=ANNA)
    assert r.status_code == 401
    assert (await client.delete(f"{U}/{uid}", headers=h)).status_code == 404
    assert (await client.get(U, headers=h)).json()["total"] == 0
    again = await _create(client, h, {"login": "anna", "password": "anna-other-1"})
    assert again["id"] != uid
    old = await db.get(User, uid)
    assert old is not None and old.deleted_at is not None


async def test_user_audit_events(client: AsyncClient, db: AsyncSession) -> None:
    h = await _admin(client)
    uid = (await _create(client, h))["id"]
    await client.patch(f"{U}/{uid}", json={"password": "another-pass"}, headers=h)
    await client.delete(f"{U}/{uid}", headers=h)
    stmt = select(AuditEvent).where(AuditEvent.action.like("user.%")).order_by(AuditEvent.id)
    events = (await db.scalars(stmt)).all()
    assert [(e.action, e.actor_login, e.object_id) for e in events] == [
        ("user.create", "admin", uid),
        ("user.update", "admin", uid),
        ("user.delete", "admin", uid),
    ]
    assert events[1].details == {"changed": ["password"]}
    assert all("another-pass" not in str(e.details) for e in events)


async def test_origin_check_for_cookie_mutations(client: AsyncClient) -> None:
    await login(client, *ADMIN)  # the cookie stays in the client
    r = await client.post(U, json=ANNA, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    r = await client.post(U, json=ANNA, headers={"Origin": "http://test"})
    assert r.status_code == 201
