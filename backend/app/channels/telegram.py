"""Telegram group channel. Private reminders have their own per-user schedule."""

import socket
from dataclasses import dataclass
from html import escape

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import ClientConnectorError
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import SendResult
from app.channels.texts import reminder_text
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.notification import Delivery, Notification
from app.models.user import User
from app.services import assignees

_bot: Bot | None = None


def get_bot() -> Bot:
    """One shared Bot instance per process (token from .env, never logged)."""
    global _bot
    if _bot is None:
        settings = get_settings()
        session = AiohttpSession(timeout=settings.telegram_timeout)
        if settings.telegram_ipv6_only:
            # Some hosters drop IPv4 to api.telegram.org; skip the doomed IPv4 attempts.
            session._connector_init["family"] = socket.AF_INET6
        _bot = Bot(token=settings.telegram_bot_token.get_secret_value(), session=session)
    return _bot


async def close_bot() -> None:
    global _bot
    if _bot is not None:
        await _bot.session.close()
    _bot = None


def paid_keyboard(occurrence_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Оплачено", callback_data=f"paid:{occurrence_id}")]
        ]
    )


@dataclass
class Audience:
    """Responsible users mentioned in the group reminder."""

    mention_line: str | None  # HTML, None when the payment has no assignees


def mention(user: User) -> str:
    """HTML mention: by ID when known, by @username when only that is set, else the login."""
    if user.telegram_user_id is None:
        return escape(f"@{user.telegram_username}" if user.telegram_username else user.login)
    label = f"@{user.telegram_username}" if user.telegram_username else user.login
    return f'<a href="tg://user?id={user.telegram_user_id}">{escape(label)}</a>'


async def audience(recurring_payment_id: int | None) -> Audience:
    async with get_sessionmaker()() as db:
        return await _audience(db, recurring_payment_id)


async def _audience(db: AsyncSession, recurring_payment_id: int | None) -> Audience:
    has_assignees, responsible = (
        await assignees.responsible_users(db, recurring_payment_id)
        if recurring_payment_id
        else (False, [])
    )
    if has_assignees:
        line = "Ответственные: " + (
            ", ".join(mention(u) for u in responsible) if responsible else "—"
        )
        return Audience(line)
    return Audience(None)


async def _send_one(
    chat_id: str | int, text: str, markup: InlineKeyboardMarkup | None
) -> SendResult:
    try:
        message = await get_bot().send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
            request_timeout=20,
        )
    except TelegramRetryAfter as exc:
        return SendResult.failed("Telegram 429: too many requests", retry_after=exc.retry_after)
    except TelegramNetworkError as exc:
        if isinstance(exc.__cause__, ClientConnectorError):
            # The connection was never established: nothing was sent, a retry is safe.
            return SendResult.failed(f"network: could not connect ({type(exc.__cause__).__name__})")
        # No answer from Telegram: the message may or may not have been delivered.
        return SendResult.unknown(f"network: {type(exc).__name__}")
    except TelegramForbiddenError:
        return SendResult.failed("Telegram 403: the bot is blocked or was never started")
    except TelegramServerError as exc:
        return SendResult.failed(f"Telegram 5xx: {exc.message}")
    except TelegramAPIError as exc:
        return SendResult.failed(f"Telegram error: {exc.message}")
    except TimeoutError:
        return SendResult.unknown("timeout")
    return SendResult.ok(external_id=str(message.message_id))


class TelegramChannel:
    name = "telegram"

    def handles(self, notification_type: str) -> bool:
        return notification_type == "payment.due_soon"

    async def send(self, notification: Notification, delivery: Delivery) -> SendResult:
        settings = get_settings()
        who = await audience(notification.recurring_payment_id)
        text = reminder_text(notification.payload, assignees_line=who.mention_line, html=True)
        markup = paid_keyboard(notification.occurrence_id) if notification.occurrence_id else None

        if not settings.telegram_chat_id:
            return SendResult.failed("no TELEGRAM_CHAT_ID")
        return await _send_one(settings.telegram_chat_id, text, markup)
