"""Application settings from environment / .env (DOMAIN §7).

Notification settings saved by the administrator are an overlay on top of .env:
`apply_overrides()` replaces them for this process, `get_settings()` returns the result.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT_PATH = BACKEND_DIR.parent / "docs" / "api" / "openapi.yaml"

_TZ_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/invoice_keeper"
    db_null_pool: bool = False

    # First team: existing data and the administrator from .env belong to it
    default_team_name: str = "aeza"

    # Supervisor: one account outside the teams, reviews team applications
    supervisor_login: str = ""
    supervisor_password: SecretStr = SecretStr("")

    # Application bot: a separate bot that takes team applications
    apply_bot_token: SecretStr = SecretStr("")

    # Administrator from .env
    admin_login: str = "admin"
    admin_password: SecretStr = SecretStr("")

    # Environment
    public_base_url: str = "http://localhost:8080"
    cookie_secure: bool = True
    dev_mode: bool = False
    log_level: str = "INFO"
    contract_path: Path = DEFAULT_CONTRACT_PATH

    # Time zone: one fixed offset for the whole system (PDF p.4)
    app_tz_offset: str = "+03:00"

    # Reminders
    reminder_days_before: int = Field(default=3, ge=3)
    reminder_send_from_hour: int = Field(default=9, ge=0, le=23)

    # Telegram
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""
    telegram_bot_username: str = ""
    miniapp_url: str = ""
    telegram_dm_reminders: bool = True  # also remind linked users in private chats
    telegram_ipv6_only: bool = False  # connect to api.telegram.org over IPv6 only (IPv4 blocked)
    telegram_timeout: int = Field(default=25, ge=5, le=120)  # seconds per Bot API request

    # Email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    email_recipients: str = ""

    # Webhook
    webhook_url: str = ""
    webhook_secret: SecretStr = SecretStr("")

    # Extra channel
    extra_channel_url: str = ""

    # Attachments
    attachments_dir: Path = BACKEND_DIR / "data" / "attachments"

    @field_validator("app_tz_offset")
    @classmethod
    def _check_tz(cls, value: str) -> str:
        m = _TZ_RE.match(value)
        if not m or int(m.group(2)) > 14 or int(m.group(3)) >= 60:
            raise ValueError("APP_TZ_OFFSET must look like +03:00")
        return value

    @property
    def tz(self) -> timezone:
        m = _TZ_RE.match(self.app_tz_offset)
        assert m
        sign = 1 if m.group(1) == "+" else -1
        delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3))) * sign
        return timezone(delta)

    @property
    def tz_label(self) -> str:
        m = _TZ_RE.match(self.app_tz_offset)
        assert m
        label = f"GMT{m.group(1)}{int(m.group(2))}"
        return label if m.group(3) == "00" else f"{label}:{m.group(3)}"

    @property
    def telegram_enabled(self) -> bool:
        has_target = bool(self.telegram_chat_id) or self.telegram_dm_reminders
        return bool(self.telegram_bot_token.get_secret_value()) and has_target

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.email_recipients)

    @property
    def webhook_enabled(self) -> bool:
        return bool(self.webhook_url)

    @property
    def extra_enabled(self) -> bool:
        return bool(self.extra_channel_url)


@lru_cache
def env_settings() -> Settings:
    """Settings from the environment / .env only."""
    return Settings()


_overrides: dict[str, Any] = {}
_effective: Settings | None = None
_scoped: ContextVar[Settings | None] = ContextVar("team_settings", default=None)


@contextmanager
def use_settings(settings: Settings) -> Iterator[None]:
    """Run a block with one team's settings: channels read them via get_settings()."""
    token = _scoped.set(settings)
    try:
        yield
    finally:
        _scoped.reset(token)


def set_scope(settings: Settings | None) -> Token[Settings | None]:
    """Use one team's settings until `reset_scope` (an API request)."""
    return _scoped.set(settings)


def reset_scope(token: Token[Settings | None]) -> None:
    try:
        _scoped.reset(token)
    except ValueError:  # cleanup ran in another context: just clear this one
        _scoped.set(None)


def get_settings() -> Settings:
    """Settings of the current team scope, else .env with the first team's overlay."""
    global _effective
    scoped = _scoped.get()
    if scoped is not None:
        return scoped
    base = env_settings()
    if not _overrides:
        return base
    if _effective is None:
        _effective = base.model_copy(update=_overrides)
    return _effective


def apply_overrides(values: dict[str, Any]) -> None:
    """Replace the overlay (values are already validated and typed, secrets as SecretStr)."""
    global _overrides, _effective
    _overrides, _effective = dict(values), None


def _cache_clear() -> None:
    env_settings.cache_clear()
    apply_overrides({})


get_settings.cache_clear = _cache_clear  # type: ignore[attr-defined]
