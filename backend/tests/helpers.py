"""Shared test helpers."""

from datetime import datetime

from app.core import clock


def freeze(moment: str) -> None:
    """Freeze the real clock at an ISO moment, e.g. "2026-11-07T09:00:00+03:00"."""
    fixed = datetime.fromisoformat(moment)
    clock.set_real_now(lambda: fixed)


ADMIN = ("admin", "admin-test-password")


TEAM = "aeza"  # the first team (DEFAULT_TEAM_NAME)


async def create_user(db, login: str, password: str, role: str = "user", team_id=None):
    """Insert a user directly (bypassing the API); the first team by default."""
    from app.core.clock import get_clock
    from app.core.security import hash_password
    from app.models.user import User
    from app.services.teams import ensure_default

    now = (await get_clock(db)).now()
    if team_id is None:
        team_id = (await ensure_default(db)).id
    user = User(
        team_id=team_id,
        login=login,
        password_hash=hash_password(password),
        role=role,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.commit()
    return user


async def login(client, login: str, password: str, team: str = TEAM) -> str:
    r = await client.post(
        "/api/v1/auth/login", json={"team": team, "login": login, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()["session"]["token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def set_business_today(db, day) -> None:
    """Move the dev clock so that the business day equals `day` (real time stays frozen)."""
    from app.core.clock import Clock, set_offset_days

    real_today = Clock().real_today()
    await set_offset_days(db, (day - real_today).days)
    await db.commit()


async def create_recurring(client, headers, due: str, **kw) -> dict:
    payload = {
        "title": "Сервер (VPS)",
        "amount": "120.00",
        "currency": "USD",
        "next_due_date": due,
        "periodicity": "monthly",
    } | kw
    r = await client.post("/api/v1/recurring-payments", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()
