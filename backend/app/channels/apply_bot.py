"""The application bot: a separate bot that takes team applications.

Here only sending: decisions reach the applicant from the API process right after the commit.
"""

import logging
import socket

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError

from app.core.config import get_settings

logger = logging.getLogger("app.channels.apply_bot")

_bot: Bot | None = None


def apply_bot_configured() -> bool:
    return bool(get_settings().apply_bot_token.get_secret_value())


def get_apply_bot() -> Bot:
    """One shared Bot instance per process (token from .env, never logged)."""
    global _bot
    if _bot is None:
        settings = get_settings()
        session = AiohttpSession(timeout=settings.telegram_timeout)
        if settings.telegram_ipv6_only:
            session._connector_init["family"] = socket.AF_INET6
        _bot = Bot(token=settings.apply_bot_token.get_secret_value(), session=session)
    return _bot


async def close_apply_bot() -> None:
    global _bot
    if _bot is not None:
        await _bot.session.close()
    _bot = None


async def send_to_applicant(chat_id: int, text: str) -> bool:
    """Private message from the application bot; False when it could not be delivered."""
    if not apply_bot_configured():
        return False
    try:
        await get_apply_bot().send_message(chat_id=chat_id, text=text, request_timeout=20)
    except (TelegramAPIError, TimeoutError, OSError) as exc:
        logger.warning("Application bot could not message the applicant: %s", type(exc).__name__)
        return False
    return True
