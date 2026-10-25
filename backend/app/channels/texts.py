"""Message texts in Russian (DOMAIN §6)."""

from datetime import date
from html import escape
from typing import Any


def ru_date(value: date | str) -> str:
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return day.strftime("%d.%m.%Y")


def assignees_plain(payload: dict[str, Any]) -> str | None:
    """«Ответственные: …» for plain-text channels (email, Slack), from the queued payload."""
    if payload.get("assign_all"):
        return "Ответственные: все пользователи"
    logins = payload.get("assignees") or []
    return f"Ответственные: {', '.join(logins)}" if logins else None


def reminder_text(
    payload: dict[str, Any], assignees_line: str | None = None, html: bool = False
) -> str:
    """🔔 Напоминание об оплате / <название> / Сумма: 120.00 USD / Срок оплаты: 10.11.2026.

    With `html=True` the text is escaped for Telegram parse_mode=HTML and `assignees_line`
    is inserted as is (it may contain mention links).
    """

    def esc(value: str) -> str:
        return escape(value) if html else value

    lines = [
        "🔔 Напоминание об оплате",
        esc(payload["title"]),
        f"Сумма: {payload['amount']} {payload['currency']}",
        f"Срок оплаты: {ru_date(payload['due_date'])}",
    ]
    if payload.get("overdue"):
        lines.append("⚠️ Срок оплаты прошёл")
    if assignees_line is not None:  # built by the caller, already safe for the target format
        lines.append(assignees_line)
    elif plain := assignees_plain(payload):
        lines.append(esc(plain))
    return "\n".join(lines)
