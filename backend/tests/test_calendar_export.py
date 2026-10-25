"""Calendar export: CSV and iCalendar."""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import real_now
from app.models.payment import PaymentOccurrence
from app.models.team import Team
from app.services.calendar import CalendarEntry
from app.services.calendar_export import _fold, to_csv, to_ics
from tests.helpers import ADMIN, bearer, create_recurring, create_user, freeze, login

E = "/api/v1/calendar/export"
NOW = "2026-11-10T12:00:00+03:00"


def _entry(**kw) -> CalendarEntry:
    base = dict(
        occurrence_id=7,
        recurring_payment_id=3,
        title="Аренда; офис, «Север»",
        amount=Decimal("85000"),
        currency="RUB",
        due_date=date(2026, 11, 5),
        state="paid",
        is_projected=False,
    )
    return CalendarEntry(**(base | kw))  # type: ignore[arg-type]


def test_csv_for_excel() -> None:
    data = to_csv([_entry(), _entry(occurrence_id=None, state=None, is_projected=True)])
    assert data.startswith("﻿".encode())
    lines = data.decode("utf-8-sig").split("\r\n")
    assert lines[0] == "Дата;Платёж;Сумма;Валюта;Статус;Ссылка"
    assert (
        lines[1] == '05.11.2026;"Аренда; офис, «Север»";85000,00;RUB;Оплачен;http://test/payments/7'
    )
    assert lines[2].endswith(";План;")


def test_ics_escaping_folding_and_uids() -> None:
    long_title = "Очень длинное название платежа " * 4
    data = to_ics(
        [_entry(), _entry(occurrence_id=None, state=None, is_projected=True, title=long_title)],
        team_id=1,
        team_name="aeza",
        now=real_now(),
    ).decode("utf-8")
    assert data.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and data.endswith(
        "END:VCALENDAR\r\n"
    )
    assert "UID:occurrence-7@invoice-keeper" in data
    assert "UID:plan-1-3-20261105@invoice-keeper" in data
    assert "DTSTART;VALUE=DATE:20261105\r\nDTEND;VALUE=DATE:20261106" in data
    assert "SUMMARY:✅ Аренда\\; офис\\, «Север» — 85000.00 RUB" in data
    assert "DESCRIPTION:Статус: Оплачен\\nhttp://test/payments/7" in data
    assert all(len(line.encode()) <= 75 for line in data.split("\r\n"))
    assert "\r\n " in data  # the long summary was folded


def test_fold_keeps_multibyte_characters() -> None:
    line = "SUMMARY:" + "ё" * 60
    folded = _fold(line)
    assert folded.replace("\r\n ", "") == line
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))


async def test_export_endpoint(client: AsyncClient, db: AsyncSession) -> None:
    freeze(NOW)
    h = bearer(await login(client, *ADMIN))
    await create_recurring(client, h, "2026-11-20", title="Сервер", amount="120.00")
    r = await client.get(E, params={"format": "csv"}, headers=h)
    assert r.status_code == 200  # a file, not JSON: check() validates JSON bodies only
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment;" in r.headers["content-disposition"]
    assert (
        "filename*=UTF-8''calendar-aeza-2026-11-01-2026-11-30.csv"
        in r.headers["content-disposition"]
    )
    assert "20.11.2026;Сервер;120,00;USD;Ожидает оплаты" in r.content.decode("utf-8-sig")

    r = await client.get(
        E, params={"format": "ics", "from": "2026-11-01", "to": "2027-01-31"}, headers=h
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    text = r.text
    assert text.count("BEGIN:VEVENT") == 3  # November, December and a projected January
    assert "X-WR-CALNAME:Платежи — aeza" in text

    for params, field in (
        ({"format": "pdf"}, "format"),
        ({"format": "csv", "from": "2026-12-01", "to": "2026-11-01"}, "to"),
        ({"format": "csv", "from": "2026-01-01", "to": "2027-01-02"}, "to"),
    ):
        r = await client.get(E, params=params, headers=h)
        assert r.status_code == 422 and field in [d["field"] for d in r.json()["error"]["details"]]
    client.cookies.clear()  # the login above also set the session cookie
    assert (await client.get(E, params={"format": "csv"})).status_code == 401


async def test_export_is_per_team(client: AsyncClient, db: AsyncSession) -> None:
    freeze(NOW)
    beta = Team(name="Beta", slug="beta", created_at=real_now())
    db.add(beta)
    await db.commit()
    await create_user(db, "anna", "anna-b-password", team_id=beta.id)
    ha = bearer(await login(client, *ADMIN))
    client.cookies.clear()
    await create_recurring(client, ha, "2026-11-20", title="Секрет команды A")
    hb = bearer(await login(client, "anna", "anna-b-password", team="beta"))
    r = await client.get(E, params={"format": "ics"}, headers=hb)
    assert (
        r.status_code == 200 and "Секрет команды A" not in r.text and "BEGIN:VEVENT" not in r.text
    )
    assert await db.scalar(select(PaymentOccurrence.id)) is not None
