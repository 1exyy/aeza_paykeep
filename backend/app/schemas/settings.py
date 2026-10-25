"""Notification settings: what the administrator sees and may change."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SmtpSecurity = Literal["starttls", "ssl", "none"]

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
_CHAT_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")


def split_recipients(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;\s]+", value) if part.strip()]


class NotificationSettingsOut(BaseModel):
    telegram_chat_id: str
    telegram_bot_configured: bool
    telegram_bot_username: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password_set: bool
    smtp_from: str
    smtp_security: SmtpSecurity
    email_recipients: list[str]
    webhook_url: str
    webhook_secret_set: bool
    channels: dict[str, bool]
    updated_at: datetime | None
    updated_by: str | None
    version: int


class NotificationSettingsPatch(BaseModel):
    """Only the fields to change. '' clears a value (channel off); secrets are write-only."""

    model_config = ConfigDict(extra="forbid")

    telegram_chat_id: str | None = Field(None, max_length=64)
    smtp_host: str | None = Field(None, max_length=253)
    smtp_port: int | None = Field(None, ge=1, le=65535)
    smtp_user: str | None = Field(None, max_length=256)
    smtp_password: str | None = Field(None, max_length=256)
    smtp_from: str | None = Field(None, max_length=254)
    smtp_security: SmtpSecurity | None = None
    email_recipients: list[str] | None = Field(None, max_length=50)
    webhook_url: str | None = Field(None, max_length=2000)
    webhook_secret: str | None = Field(None, max_length=256)
    expected_version: int | None = None

    @field_validator("telegram_chat_id", "smtp_host", "smtp_user", "smtp_from", "webhook_url")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return None if v is None else v.strip()

    @field_validator("telegram_chat_id")
    @classmethod
    def _v_chat(cls, v: str | None) -> str | None:
        if v and not _CHAT_RE.match(v):
            raise ValueError("ID чата: число (у групп и каналов начинается с -100) или @имя_канала")
        return v

    @field_validator("smtp_host")
    @classmethod
    def _v_host(cls, v: str | None) -> str | None:
        if v and not _HOST_RE.match(v):
            raise ValueError("Укажите имя SMTP-сервера, например smtp-relay.brevo.com")
        return v

    @field_validator("smtp_from")
    @classmethod
    def _v_from(cls, v: str | None) -> str | None:
        if v and not _EMAIL_RE.match(v):
            raise ValueError("Укажите адрес отправителя, например billing@example.com")
        return v

    @field_validator("email_recipients")
    @classmethod
    def _v_recipients(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [address.strip() for address in v if address.strip()]
        bad = [address for address in cleaned if not _EMAIL_RE.match(address)]
        if bad:
            raise ValueError(f"Некорректный адрес: {bad[0]}")
        return list(dict.fromkeys(cleaned))


class SettingsTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["telegram", "email", "webhook"]


class SettingsTestResult(BaseModel):
    channel: str
    ok: bool
    error: str | None
