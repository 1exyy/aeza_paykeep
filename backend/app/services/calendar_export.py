"""Export of a team's payment calendar: CSV and iCalendar.

Both contain existing periods and projected ones (marked «План»), like GET /calendar.
- CSV for spreadsheets: UTF-8 with BOM, «;» separator and decimal comma (Excel in a Russian
  locale opens it as is).
- iCalendar (RFC 5545): one all-day event per payment; UIDs are stable, so importing a
  newer export updates the same events instead of duplicating them.
"""

import csv
import io
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.money import format_money
from app.services.calendar import CalendarEntry

STATE_LABELS = {
    "upcoming": "Ожидает оплаты",
    "overdue": "Просрочен",
    "paid": "Оплачен",
    "paid_late": "Оплачен с опозданием",
}
PROJECTED = "План"


def _state(entry: CalendarEntry) -> str:
    return PROJECTED if entry.is_projected else STATE_LABELS.get(entry.state or "", "")


def _link(entry: CalendarEntry) -> str:
    if entry.occurrence_id is None:
        return ""
    return f"{get_settings().public_base_url.rstrip('/')}/payments/{entry.occurrence_id}"


def to_csv(entries: list[CalendarEntry]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Дата", "Платёж", "Сумма", "Валюта", "Статус", "Ссылка"])
    for e in entries:
        writer.writerow(
            [
                e.due_date.strftime("%d.%m.%Y"),
                e.title,
                format_money(e.amount).replace(".", ","),
                e.currency,
                _state(e),
                _link(e),
            ]
        )
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines of at most 75 octets, continuations start with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts: list[str] = []
    chunk = b""
    for char in line:
        encoded = char.encode("utf-8")
        if len(chunk) + len(encoded) > (75 if not parts else 74):
            parts.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += encoded
    parts.append(chunk.decode("utf-8"))
    return "\r\n ".join(parts)


def _uid(entry: CalendarEntry, team_id: int) -> str:
    if entry.occurrence_id is not None:
        return f"occurrence-{entry.occurrence_id}@invoice-keeper"
    # a projected period becomes a real one later; its due date identifies it meanwhile
    return f"plan-{team_id}-{entry.recurring_payment_id}-{entry.due_date:%Y%m%d}@invoice-keeper"


def to_ics(entries: list[CalendarEntry], team_id: int, team_name: str, now: datetime) -> bytes:
    """`now` is the business time from the clock (DTSTAMP)."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Aeza PayKeep//Invoice Keeper//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(f'Платежи — {team_name}')}",
    ]
    for e in entries:
        paid = e.state in ("paid", "paid_late")
        summary = f"{'✅ ' if paid else ''}{e.title} — {format_money(e.amount)} {e.currency}"
        description = f"Статус: {_state(e)}"
        if link := _link(e):
            description += f"\n{link}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_uid(e, team_id)}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{e.due_date:%Y%m%d}",
            f"DTEND;VALUE=DATE:{e.due_date + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(description)}",
            f"CATEGORIES:{_escape(_state(e))}",
            "TRANSP:TRANSPARENT",
        ]
        if link:
            lines.append(f"URL:{link}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8")
