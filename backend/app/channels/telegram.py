"""Telegram channel: reminder to TELEGRAM_CHAT_ID and to linked users' private chats.

One delivery per reminder (the contract has one `telegram` channel):
1. the group chat first — its outcome is the delivery outcome (explicit error → retry,
   no answer → `unknown`); if it was not delivered, no private message is sent, so a retry
   cannot duplicate anything;
2. then a private message to every linked active user (only the assignees when the payment
   has them), once. Their failures (bot blocked,
   429, network) are listed in `last_error` and never retried.
Without TELEGRAM_CHAT_ID only private messages are sent; at least one must succeed.
"""

import logging
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import SendResult
from app.channels.texts import reminder_text
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.notification import Delivery, Notification
from app.models.team import Team
from app.models.user import User
from app.services import assignees

logger = logging.getLogger("app.channels.telegram")

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
    """Who the reminder is for: the mention line and the private-message recipients."""

    mention_line: str | None  # HTML, None when the payment has no assignees
    recipients: list[tuple[str, int]]  # (login, telegram_user_id)
    team_name: str = ""  # shown in private messages: a person may be in several teams


def mention(user: User) -> str:
    """HTML mention: by ID when known, by @username when only that is set, else the login."""
    if user.telegram_user_id is None:
        return escape(f"@{user.telegram_username}" if user.telegram_username else user.login)
    label = f"@{user.telegram_username}" if user.telegram_username else user.login
    return f'<a href="tg://user?id={user.telegram_user_id}">{escape(label)}</a>'


async def audience(team_id: int, recurring_payment_id: int | None) -> Audience:
    async with get_sessionmaker()() as db:
        team = await db.get(Team, team_id) if team_id else None
        found = await _audience(db, team_id, recurring_payment_id)
        found.team_name = team.name if team else ""
        return found


async def _audience(db: AsyncSession, team_id: int, recurring_payment_id: int | None) -> Audience:
    has_assignees, responsible = (
        await assignees.responsible_users(db, recurring_payment_id)
        if recurring_payment_id
        else (False, [])
    )
    if has_assignees:
        line = "Ответственные: " + (
            ", ".join(mention(u) for u in responsible) if responsible else "—"
        )
        linked = [(u.login, u.telegram_user_id) for u in responsible if u.telegram_user_id]
        return Audience(line, [(login, tg) for login, tg in linked if tg is not None])
    rows = await db.execute(
        select(User.login, User.telegram_user_id)
        .where(
            User.team_id == team_id,
            User.deleted_at.is_(None),
            User.telegram_user_id.is_not(None),
        )
        .order_by(User.id)
    )
    return Audience(None, [(login, tg) for login, tg in rows.all() if tg is not None])


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
        who = await audience(notification.team_id, notification.recurring_payment_id)
        text = reminder_text(notification.payload, assignees_line=who.mention_line, html=True)
        markup = paid_keyboard(notification.occurrence_id) if notification.occurrence_id else None

        group: SendResult | None = None
        if settings.telegram_chat_id:
            group = await _send_one(settings.telegram_chat_id, text, markup)
            if group.outcome != "sent":
                return group  # nothing else was sent: a retry cannot duplicate

        recipients = who.recipients if settings.telegram_dm_reminders else []
        # a person may be in several teams: private messages name the team
        dm_text = f"Команда «{escape(who.team_name)}»\n{text}" if who.team_name else text
        if group is None and not recipients:
            return SendResult.failed("no TELEGRAM_CHAT_ID and no linked users")

        sent: list[str] = []
        problems: list[str] = []
        first_dm_id: str | None = None
        for login, telegram_id in recipients:
            result = await _send_one(telegram_id, dm_text, markup)
            if result.outcome == "sent":
                sent.append(login)
                first_dm_id = first_dm_id or result.external_id
            else:
                problems.append(f"{login}: {result.error}")
        if recipients:
            logger.info("Private reminders: %d of %d sent", len(sent), len(recipients))

        if group is None and not sent:
            # DM-only mode and nobody got it: report like a failed group send (retry is safe)
            return SendResult.failed("private messages: " + "; ".join(problems)[:900])
        result = SendResult.ok(external_id=group.external_id if group else first_dm_id)
        if problems:
            result.error = (
                f"private messages {len(sent)}/{len(recipients)}; " + "; ".join(problems)
            )[:1000]
        return result
