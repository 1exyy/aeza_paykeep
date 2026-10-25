"""Teams: login inside a team and full data isolation between teams."""

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import real_now
from app.models.audit_event import AuditEvent
from app.models.notification import Delivery, Notification
from app.models.payment import PaymentOccurrence
from app.models.team import Team
from app.models.user import User
from app.services.telegram_paid import press_paid
from tests.helpers import ADMIN, bearer, create_recurring, create_user, freeze, login

TODAY = "2026-11-10T12:00:00+03:00"
R = "/api/v1/recurring-payments"
OCC = "/api/v1/payment-occurrences"


async def _team(db: AsyncSession, name: str) -> Team:
    team = Team(name=name, slug=name.lower(), created_at=real_now())
    db.add(team)
    await db.commit()
    return team


@pytest.fixture
async def teams(client: AsyncClient, db: AsyncSession) -> dict:
    """Team A (the first one, admin from .env) and team B («Beta Team») with its own admin.

    Both teams have a user «anna» and an admin called «admin» — logins repeat across teams.
    """
    freeze(TODAY)
    beta = await _team(db, "Beta Team")
    beta_admin = await create_user(
        db, "admin", "beta-admin-password", role="admin", team_id=beta.id
    )
    beta_admin.is_protected = True  # each team has its own protected administrator
    await db.commit()
    anna_a = await create_user(db, "anna", "anna-a-password")
    anna_b = await create_user(db, "anna", "anna-b-password", team_id=beta.id)
    ha = bearer(await login(client, *ADMIN))
    client.cookies.clear()
    hb = bearer(await login(client, "admin", "beta-admin-password", team="beta team"))
    client.cookies.clear()
    rp_a = await create_recurring(
        client,
        ha,
        "2026-11-20",
        title="A: аренда",
        amount="1000.00",
        currency="RUB",
        assignee_ids=[anna_a.id],
    )
    rp_b = await create_recurring(
        client, hb, "2026-11-25", title="B: сервер", amount="20.00", currency="USD"
    )
    occ_a = await db.scalar(
        select(PaymentOccurrence.id)
        .where(PaymentOccurrence.recurring_payment_id == rp_a["id"])
        .order_by(PaymentOccurrence.due_date)
    )
    return {
        "beta": beta,
        "ha": ha,
        "hb": hb,
        "anna_a": anna_a,
        "anna_b": anna_b,
        "rp_a": rp_a,
        "rp_b": rp_b,
        "occ_a": occ_a,
    }


# ---------- login ----------


async def test_same_login_in_two_teams(client: AsyncClient, teams: dict) -> None:
    for team, password in (("aeza", "anna-a-password"), ("  BETA   team ", "anna-b-password")):
        r = await client.post(
            "/api/v1/auth/login", json={"team": team, "login": "anna", "password": password}
        )
        assert r.status_code == 200, r.text
        client.cookies.clear()
    for team, password in (
        ("aeza", "anna-b-password"),
        ("nope", "anna-a-password"),
        ("", "anna-a-password"),
    ):
        r = await client.post(
            "/api/v1/auth/login", json={"team": team, "login": "anna", "password": password}
        )
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Неверная команда, логин или пароль"


async def test_config_names_the_team(client: AsyncClient, teams: dict) -> None:
    r = await client.get("/api/v1/config", headers=teams["hb"])
    assert r.json()["team"] == {"id": teams["beta"].id, "name": "Beta Team"}


# ---------- isolation ----------


async def test_lists_show_only_own_team(client: AsyncClient, teams: dict) -> None:
    hb = teams["hb"]
    titles = [i["title"] for i in (await client.get(R, headers=hb)).json()["items"]]
    assert titles == ["B: сервер"]
    occ = (await client.get(OCC, params={"limit": 100}, headers=hb)).json()["items"]
    assert occ and {i["title"] for i in occ} == {"B: сервер"}
    users = [u["login"] for u in (await client.get("/api/v1/users", headers=hb)).json()["items"]]
    assert users == ["anna"]
    assert (await client.get("/api/v1/users", headers=hb)).json()["items"][0]["id"] == teams[
        "anna_b"
    ].id

    summary = (
        await client.get(
            "/api/v1/payments/summary",
            params={"from": "2026-11-01", "to": "2026-12-31"},
            headers=hb,
        )
    ).json()
    by = {c["currency"]: c for c in summary["currencies"]}
    assert by["RUB"]["total"] == "0.00" and by["USD"]["total"] != "0.00"

    cal = (await client.get("/api/v1/calendar", params={"month": "2026-11"}, headers=hb)).json()
    titles = {i["title"] for d in cal["days"] for i in d["items"]}
    assert titles == {"B: сервер"}
    budget = (
        await client.get("/api/v1/budget", params={"period": "year", "year": 2026}, headers=hb)
    ).json()
    rub = next(t for t in budget["currencies"] if t["currency"] == "RUB")
    assert rub["planned"] == "0.00"

    audit = (await client.get("/api/v1/audit-log", params={"limit": 200}, headers=hb)).json()[
        "items"
    ]
    assert audit and all("A: аренда" not in str(e["details"]) for e in audit)
    assert all(e["actor"] is None or e["actor"]["id"] != 1 for e in audit)


async def test_foreign_ids_are_not_found(
    client: AsyncClient, db: AsyncSession, teams: dict
) -> None:
    hb, rp_a, occ_a = teams["hb"], teams["rp_a"]["id"], teams["occ_a"]
    assert (await client.get(f"{R}/{rp_a}", headers=hb)).status_code == 404
    assert (
        await client.patch(f"{R}/{rp_a}", json={"title": "взлом"}, headers=hb)
    ).status_code == 404
    assert (await client.delete(f"{R}/{rp_a}", headers=hb)).status_code == 404
    assert (await client.get(f"{OCC}/{occ_a}", headers=hb)).status_code == 404
    r = await client.patch(
        f"{OCC}/{occ_a}", json={"status": "paid", "paid_date": "2026-11-10"}, headers=hb
    )
    assert r.status_code == 404
    assert (await client.get(f"{OCC}/{occ_a}/attachments", headers=hb)).status_code == 404
    r = await client.post(
        f"{OCC}/{occ_a}/attachments", json={"url": "https://example.com/x"}, headers=hb
    )
    assert r.status_code == 404

    # an attachment of team A cannot be downloaded or deleted from team B
    r = await client.post(
        f"{OCC}/{occ_a}/attachments", json={"url": "https://example.com/a"}, headers=teams["ha"]
    )
    att = r.json()["id"]
    assert (await client.get(f"/api/v1/attachments/{att}/file", headers=hb)).status_code == 404
    assert (await client.delete(f"/api/v1/attachments/{att}", headers=hb)).status_code == 404

    anna_a = teams["anna_a"].id
    assert (
        await client.patch(f"/api/v1/users/{anna_a}", json={"login": "x-anna"}, headers=hb)
    ).status_code == 404
    assert (await client.delete(f"/api/v1/users/{anna_a}", headers=hb)).status_code == 404
    # a user of another team cannot be made responsible
    r = await client.post(
        R,
        json={
            "title": "t",
            "amount": "1",
            "currency": "RUB",
            "next_due_date": "2026-11-30",
            "periodicity": "monthly",
            "assignee_ids": [anna_a],
        },
        headers=hb,
    )
    assert r.status_code == 422

    # nothing of team A changed
    a = (await client.get(f"{R}/{rp_a}", headers=teams["ha"])).json()
    assert a["title"] == "A: аренда" and a["status"] == "active"
    assert (await db.get(User, anna_a)).deleted_at is None  # type: ignore[union-attr]


async def test_settings_and_deliveries_are_per_team(
    client: AsyncClient, db: AsyncSession, teams: dict
) -> None:
    hb, ha = teams["hb"], teams["ha"]
    S = "/api/v1/settings/notifications"
    r = await client.patch(
        S, json={"telegram_chat_id": "-1009999999999", "smtp_host": "smtp.beta.example"}, headers=hb
    )
    assert r.status_code == 200
    a = (await client.get(S, headers=ha)).json()
    assert a["telegram_chat_id"] != "-1009999999999" and a["smtp_host"] != "smtp.beta.example"
    b = (await client.get(S, headers=hb)).json()
    assert b["telegram_chat_id"] == "-1009999999999" and b["version"] == 1

    # a delivery of team A is not listed for team B
    now = real_now()
    notification = Notification(type="occurrence.paid", team_id=1, payload={}, created_at=now)
    db.add(notification)
    await db.flush()
    db.add(
        Delivery(
            notification_id=notification.id,
            channel="webhook",
            status="sent",
            attempts=1,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await db.commit()
    assert (await client.get("/api/v1/notifications/deliveries", headers=hb)).json()["total"] == 0
    assert (await client.get("/api/v1/notifications/deliveries", headers=ha)).json()["total"] == 1


async def test_one_telegram_in_two_teams(
    client: AsyncClient, db: AsyncSession, teams: dict
) -> None:
    for user in (teams["anna_a"], teams["anna_b"]):
        await client.patch(
            f"/api/v1/users/{user.id}",
            json={"telegram": "4242"},
            headers=teams["ha"] if user.team_id == 1 else teams["hb"],
        )
    a = await db.get(User, teams["anna_a"].id, populate_existing=True)
    b = await db.get(User, teams["anna_b"].id, populate_existing=True)
    assert a and b and a.telegram_user_id == b.telegram_user_id == 4242

    # «Оплачено» on a period of team A is pressed by anna of team A
    outcome = await press_paid(db, 4242, teams["occ_a"])
    assert outcome.paid_line and "anna" in outcome.paid_line
    paid_by = await db.scalar(
        select(PaymentOccurrence.paid_by_id).where(PaymentOccurrence.id == teams["occ_a"])
    )
    assert paid_by == teams["anna_a"].id
    event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "telegram.paid_button"))
    assert event is not None and event.team_id == 1


async def test_each_team_uses_its_own_channels(
    client: AsyncClient, db: AsyncSession, teams: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Webhook of team B gets only team B's events; the worker sends with team B's URL."""
    hb, ha = teams["hb"], teams["ha"]
    S = "/api/v1/settings/notifications"
    r = await client.patch(S, json={"webhook_url": "https://hooks.beta.example/in"}, headers=hb)
    assert r.json()["channels"]["webhook"] is True
    assert (await client.get(S, headers=ha)).json()["channels"]["webhook"] is False

    await create_recurring(client, ha, "2026-12-01", title="A: ещё")
    await create_recurring(client, hb, "2026-12-02", title="B: ещё")
    rows = (
        await db.execute(
            select(Notification.team_id, Delivery.channel)
            .join(Delivery, Delivery.notification_id == Notification.id)
            .where(Delivery.channel == "webhook")
        )
    ).all()
    assert rows and {team for team, _ in rows} == {teams["beta"].id}

    sent_to: list[str] = []

    async def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        sent_to.append(url)
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    from app.worker.jobs import dispatch_deliveries

    await dispatch_deliveries(db)
    assert sent_to and set(sent_to) == {"https://hooks.beta.example/in"}
