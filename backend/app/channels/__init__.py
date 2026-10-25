"""Notification channels: one interface `send(notification, delivery) -> SendResult`.

Outcomes:
- sent    — the channel confirmed delivery (Telegram 200, SMTP 250, webhook 2xx);
- failed  — an explicit error answer; the outbox retries (up to 5 attempts, backoff);
- unknown — no answer (timeout, broken connection): never retried, a duplicate is worse than a miss.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from app.models.notification import Delivery, Notification

logger = logging.getLogger("app.channels")


@dataclass
class SendResult:
    outcome: Literal["sent", "failed", "unknown"]
    error: str | None = None
    external_id: str | None = None
    retry_after: int | None = None  # seconds, when the channel asked to wait (429)

    @classmethod
    def ok(cls, external_id: str | None = None) -> "SendResult":
        return cls("sent", external_id=external_id)

    @classmethod
    def failed(cls, error: str, retry_after: int | None = None) -> "SendResult":
        return cls("failed", error=error, retry_after=retry_after)

    @classmethod
    def unknown(cls, error: str) -> "SendResult":
        return cls("unknown", error=error)


class Channel(Protocol):
    name: str

    def handles(self, notification_type: str) -> bool: ...

    async def send(self, notification: Notification, delivery: Delivery) -> SendResult: ...


ChannelRegistry = dict[str, Channel]


def _default_registry() -> ChannelRegistry:
    from app.channels.email import EmailChannel
    from app.channels.extra import ExtraChannel
    from app.channels.telegram import TelegramChannel
    from app.channels.webhook import WebhookChannel, url_allowed
    from app.core.config import get_settings

    settings = get_settings()
    registry: ChannelRegistry = {}
    if settings.telegram_bot_token.get_secret_value() and settings.telegram_chat_id:
        registry["telegram"] = TelegramChannel()
    if settings.email_enabled:
        registry["email"] = EmailChannel()
    if settings.webhook_enabled:
        if url_allowed(settings.webhook_url, settings.dev_mode):
            registry["webhook"] = WebhookChannel()
        else:
            logger.warning("WEBHOOK_URL must be https:// (http only with DEV_MODE): webhook is off")
    if settings.extra_enabled:
        if url_allowed(settings.extra_channel_url, settings.dev_mode):
            registry["extra"] = ExtraChannel()
        else:
            logger.warning("EXTRA_CHANNEL_URL must be https:// (http only with DEV_MODE): off")
    return registry


_factory: Callable[[], ChannelRegistry] = _default_registry


def get_channels() -> ChannelRegistry:
    """Channels enabled by configuration (.env)."""
    return _factory()


def set_channels_factory(factory: Callable[[], ChannelRegistry] | None) -> None:
    """Tests: replace the real channels with fakes (None restores the default)."""
    global _factory
    _factory = factory or _default_registry
