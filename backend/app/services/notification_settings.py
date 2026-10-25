"""Notification settings saved by the administrator. Callers commit.

Stored in `app_settings.values` as Settings field names; they override .env in every process:
the API applies them at startup and after a change, the worker on every loop tick.
Secrets (SMTP password, webhook secret) are write-only: the API never returns them.
"""

import uuid
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any, cast

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import SendResult
from app.channels import email as email_channel
from app.channels.telegram import _send_one
from app.channels.webhook import WebhookChannel, url_allowed
from app.core.clock import Clock, to_local
from app.core.config import Settings, apply_overrides, env_settings, get_settings, use_settings
from app.core.errors import AppError, version_conflict
from app.models.app_settings import AppSettings
from app.models.notification import Delivery, Notification
from app.models.team import Team
from app.models.user import User
from app.schemas.settings import NotificationSettingsOut, NotificationSettingsPatch
from app.services import audit, teams

# Settings fields the administrator may override.
FIELDS = (
    "telegram_chat_id",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "smtp_starttls",
    "smtp_ssl",
    "email_recipients",
    "webhook_url",
    "webhook_secret",
)
SECRETS = {"smtp_password", "webhook_secret"}


def _typed(values: dict[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in values.items() if key in FIELDS}
    for key in SECRETS & out.keys():
        out[key] = SecretStr(str(out[key]))
    return out


async def _row(db: AsyncSession, team_id: int, lock: bool = False) -> AppSettings | None:
    stmt = select(AppSettings).where(AppSettings.team_id == team_id)
    return await db.scalar(stmt.with_for_update() if lock else stmt)


# Blank notification settings: what a new team starts from (.env belongs to the first team).
_BLANK: dict[str, Any] = {
    "telegram_chat_id": "",
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": SecretStr(""),
    "smtp_from": "",
    "smtp_starttls": True,
    "smtp_ssl": False,
    "email_recipients": "",
    "webhook_url": "",
    "webhook_secret": SecretStr(""),
    "extra_channel_url": "",
}


async def _is_default(db: AsyncSession, team_id: int) -> bool:
    team = await db.get(Team, team_id)
    return team is not None and team.slug == teams.normalize(env_settings().default_team_name)


def effective(values: dict[str, Any], is_default: bool) -> Settings:
    """Settings of one team: its saved values over .env (first team) or over blanks."""
    base = env_settings() if is_default else env_settings().model_copy(update=_BLANK)
    return base.model_copy(update=_typed(values))


async def team_settings(db: AsyncSession, team_id: int) -> tuple[Settings, AppSettings | None]:
    row = await _row(db, team_id)
    return effective(row.values if row else {}, await _is_default(db, team_id)), row


async def refresh(db: AsyncSession) -> None:
    """Apply the first team's stored settings to this process (the global overlay)."""
    team = await teams.by_name(db, env_settings().default_team_name)
    row = await _row(db, team.id) if team else None
    apply_overrides(_typed(row.values) if row else {})


def view(s: Settings, row: AppSettings | None) -> NotificationSettingsOut:
    with use_settings(s):
        recipients = email_channel.recipients()
    webhook_on = s.webhook_enabled and url_allowed(s.webhook_url, s.dev_mode)
    return NotificationSettingsOut(
        telegram_chat_id=s.telegram_chat_id,
        telegram_bot_configured=bool(s.telegram_bot_token.get_secret_value()),
        telegram_bot_username=s.telegram_bot_username,
        smtp_host=s.smtp_host,
        smtp_port=s.smtp_port,
        smtp_user=s.smtp_user,
        smtp_password_set=bool(s.smtp_password.get_secret_value()),
        smtp_from=s.smtp_from,
        smtp_security=cast(Any, "ssl" if s.smtp_ssl else "starttls" if s.smtp_starttls else "none"),
        email_recipients=recipients,
        webhook_url=s.webhook_url,
        webhook_secret_set=bool(s.webhook_secret.get_secret_value()),
        channels={"telegram": s.telegram_enabled, "email": s.email_enabled, "webhook": webhook_on},
        updated_at=to_local(row.updated_at) if row else None,
        updated_by=row.updated_by_login if row else None,
        version=row.version if row else 0,
    )


async def get(db: AsyncSession, team_id: int) -> NotificationSettingsOut:
    s, row = await team_settings(db, team_id)
    return view(s, row)


async def update(
    db: AsyncSession,
    clock: Clock,
    actor: User,
    data: NotificationSettingsPatch,
    ip: str | None,
) -> NotificationSettingsOut:
    given = data.model_fields_set - {"expected_version"}
    if not given:
        raise AppError.validation("body", "Передайте хотя бы одну настройку")
    if data.webhook_url and not url_allowed(data.webhook_url, env_settings().dev_mode):
        raise AppError.validation("webhook_url", "Адрес webhook должен начинаться с https://")

    now = clock.now()
    team_id = actor.team_id
    await db.execute(
        insert(AppSettings)
        .values(team_id=team_id, values={}, version=0, updated_at=now)
        .on_conflict_do_nothing(index_elements=[AppSettings.team_id])
    )
    row = await _row(db, team_id, lock=True)
    assert row is not None
    is_default = await _is_default(db, team_id)
    current = effective(row.values, is_default)
    if data.expected_version is not None and data.expected_version != row.version:
        raise version_conflict()

    values = dict(row.values)
    changed: list[str] = []

    def put(field: str, value: Any) -> None:
        old = getattr(current, field)
        old = old.get_secret_value() if isinstance(old, SecretStr) else old
        if old != value or field not in values:
            values[field] = value
            if old != value:
                changed.append(field)

    for field in (
        "telegram_chat_id",
        "smtp_host",
        "smtp_port",
        "smtp_user",
        "smtp_from",
        "webhook_url",
        "smtp_password",
        "webhook_secret",
    ):
        if field in given and getattr(data, field) is not None:
            put(field, getattr(data, field))
    if "email_recipients" in given and data.email_recipients is not None:
        put("email_recipients", ", ".join(data.email_recipients))
    if "smtp_security" in given and data.smtp_security is not None:
        put("smtp_ssl", data.smtp_security == "ssl")
        put("smtp_starttls", data.smtp_security == "starttls")

    if values != row.values:
        row.values = values
        row.version += 1
        row.updated_at = now
        row.updated_by_login = actor.login
        if is_default:
            apply_overrides(_typed(values))
    if changed:
        audit.record(
            db,
            clock,
            "settings.update",
            actor=actor,
            object_type=None,
            details={"changed": sorted(set(changed))},  # names only, never the values
            ip=ip,
        )
    await db.flush()
    return view(effective(values, is_default), row)


def _test_notification(clock: Clock) -> Notification:
    return Notification(
        event_id=uuid.uuid4(),
        type="settings.test",
        payload={"message": "Тестовое уведомление Invoice Keeper: канал настроен верно."},
        created_at=clock.now(),
    )


async def send_test(clock: Clock, channel: str) -> SendResult:
    """Send a test message through one channel with the current settings."""
    s = get_settings()
    if channel == "telegram":
        if not s.telegram_bot_token.get_secret_value():
            return SendResult.failed("Не задан TELEGRAM_BOT_TOKEN в .env на сервере")
        if not s.telegram_chat_id:
            return SendResult.failed("Не указан ID чата или канала")
        return await _send_one(
            s.telegram_chat_id,
            "✅ Тестовое сообщение Invoice Keeper: напоминания будут приходить в этот чат.",
            None,
        )
    if channel == "email":
        to = email_channel.recipients()
        if not s.smtp_host:
            return SendResult.failed("Не указан SMTP-сервер")
        if not to:
            return SendResult.failed("Не указаны получатели")
        message = EmailMessage()
        message["From"] = formataddr(("Invoice Keeper", s.smtp_from or s.smtp_user))
        message["To"] = ", ".join(to)
        message["Subject"] = "Invoice Keeper: тестовое письмо"
        message["Message-ID"] = make_msgid(domain="invoice-keeper")
        message.set_content(
            "Тестовое письмо Invoice Keeper: напоминания будут приходить на этот адрес."
        )
        return await email_channel.deliver(message, to)
    if not s.webhook_url:
        return SendResult.failed("Не указан адрес webhook")
    if not url_allowed(s.webhook_url, s.dev_mode):
        return SendResult.failed("Адрес webhook должен начинаться с https://")
    return await WebhookChannel().send(_test_notification(clock), cast(Delivery, None))
