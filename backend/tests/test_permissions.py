"""Every admin-only endpoint: user → 403 with no data change; no session → 401."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base
from app.models.audit_event import AuditEvent
from tests.helpers import ADMIN, bearer, create_user, login

ADMIN_ENDPOINTS = [
    ("GET", "/api/v1/users", None),
    ("POST", "/api/v1/users", {"login": "eve", "password": "eve-password"}),
    ("PATCH", "/api/v1/users/{other}", {"login": "renamed"}),
    ("DELETE", "/api/v1/users/{other}", None),
    ("PATCH", "/api/v1/users/{admin}", {"password": "hacked-password"}),
    ("DELETE", "/api/v1/users/{admin}", None),
    (
        "POST",
        "/api/v1/recurring-payments",
        {
            "title": "X",
            "amount": "1",
            "currency": "RUB",
            "next_due_date": "2099-01-01",
            "periodicity": "monthly",
        },
    ),
    ("DELETE", "/api/v1/recurring-payments/{recurring}", None),
    ("PATCH", "/api/v1/recurring-payments/{recurring}", {"assign_all": True}),
    ("GET", "/api/v1/notifications/deliveries", None),
    ("GET", "/api/v1/audit-log", None),
    ("PUT", "/api/v1/dev/clock", {"offset_days": 30}),
    ("POST", "/api/v1/dev/run-jobs", None),
]

AUTH_ENDPOINTS = [
    *ADMIN_ENDPOINTS,
    ("GET", "/api/v1/auth/me", None),
    ("GET", "/api/v1/recurring-payments", None),
    ("GET", "/api/v1/payment-occurrences", None),
    ("GET", "/api/v1/payment-occurrences/1", None),
    ("PATCH", "/api/v1/payment-occurrences/1", {"status": "unpaid"}),
    ("GET", "/api/v1/dev/clock", None),
    ("POST", "/api/v1/telegram/link", {"init_data": "x"}),
    ("DELETE", "/api/v1/telegram/link", None),
    ("GET", "/api/v1/payment-occurrences/1/attachments", None),
    ("POST", "/api/v1/payment-occurrences/1/attachments", {"url": "https://a.example"}),
    ("GET", "/api/v1/attachments/1/file", None),
    ("DELETE", "/api/v1/attachments/1", None),
    ("GET", "/api/v1/calendar", None),
    ("GET", "/api/v1/budget?period=year&year=2026", None),
]


SKIP_TABLES = {"sessions", "login_attempts", "audit_events"}


async def _snapshot(db: AsyncSession) -> tuple:
    """All business data (every table except session bookkeeping) + non-auth audit count."""
    data = []
    for table in Base.metadata.sorted_tables:
        if table.name not in SKIP_TABLES:
            rows = (await db.execute(select(table).order_by(*table.primary_key.columns))).all()
            data.append((table.name, tuple(rows)))
    audit = await db.scalar(
        select(func.count()).select_from(AuditEvent).where(~AuditEvent.action.like("auth.%"))
    )
    return tuple(data), audit


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ENDPOINTS)
async def test_user_gets_403_and_nothing_changes(
    client: AsyncClient, db: AsyncSession, method: str, path: str, body: dict | None
) -> None:
    other = await create_user(db, "boris", "boris-password")
    await create_user(db, "anna", "anna-password")
    admin_token = await login(client, *ADMIN)
    admin_id = (await client.get("/api/v1/auth/me", headers=bearer(admin_token))).json()["id"]
    recurring = await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": "Аренда",
            "amount": "100",
            "currency": "RUB",
            "next_due_date": "2099-01-01",
            "periodicity": "monthly",
        },
        headers=bearer(admin_token),
    )
    client.cookies.clear()
    token = await login(client, "anna", "anna-password")
    client.cookies.clear()
    before = await _snapshot(db)

    url = path.format(other=other.id, admin=admin_id, recurring=recurring.json()["id"])
    r = await client.request(method, url, json=body, headers=bearer(token))
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "forbidden"
    db.expire_all()
    assert await _snapshot(db) == before


@pytest.mark.parametrize(("method", "path", "body"), AUTH_ENDPOINTS)
async def test_no_session_401(
    client: AsyncClient, method: str, path: str, body: dict | None
) -> None:
    r = await client.request(method, path.format(other=1, admin=1, recurring=1), json=body)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
