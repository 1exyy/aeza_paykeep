"""Telegram bot (long polling in the worker): /start with the Mini App button, «Оплачено» button."""

import logging
from html import escape

from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy import select

from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models.team import Team
from app.services import telegram_link
from app.services.telegram_paid import parse_callback, press_paid

logger = logging.getLogger("app.worker.bot")
router = Router(name="invoice-keeper")


@router.message(CommandStart(), F.chat.type == "private")
async def on_start(message: Message) -> None:
    text = "Invoice Keeper: напоминания о регулярных платежах."
    sender = message.from_user
    if sender is not None:
        # A user the administrator set up by @username gets their ID here,
        # in every team where they are set up.
        async with get_sessionmaker()() as db:
            users = await telegram_link.bind_on_contact(
                db, await get_clock(db), sender.id, sender.username
            )
            names = {
                team.id: team.name
                for team in await db.scalars(
                    select(Team).where(Team.id.in_({u.team_id for u in users}))
                )
            }
            await db.commit()
        if users:
            who = ", ".join(f"{u.login} (команда {names.get(u.team_id, '?')})" for u in users)
            text += f"\nВы вошли как {who}: кнопка «Оплачено» и личные напоминания работают."
    url = get_settings().miniapp_url
    if not url:
        await message.answer(text)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть Invoice Keeper", web_app=WebAppInfo(url=url))]
        ]
    )
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("chatid"), F.chat.type.in_({"group", "supergroup"}))
async def on_chat_id(message: Message) -> None:
    """Tells the chat ID to put into a team application or the settings tab."""
    await message.reply(f"ID этого чата: {message.chat.id}")


@router.channel_post(F.text.startswith("/chatid"))
async def on_channel_chat_id(message: Message) -> None:
    await message.answer(f"ID этого канала: {message.chat.id}")


@router.callback_query(F.data.startswith("paid:"))
async def on_paid(callback: CallbackQuery) -> None:
    occurrence_id = parse_callback(callback.data)
    if occurrence_id is None:
        await callback.answer("Неизвестная кнопка")
        return
    async with get_sessionmaker()() as db:
        outcome = await press_paid(
            db, callback.from_user.id, occurrence_id, callback.from_user.username
        )
    await callback.answer(outcome.alert, show_alert=outcome.paid_line is None)
    message = callback.message
    if outcome.paid_line and isinstance(message, Message):
        try:
            # html_text keeps the mention links of the reminder
            await message.edit_text(
                f"{message.html_text}\n\n{escape(outcome.paid_line)}",
                parse_mode="HTML",
                reply_markup=None,
            )
        except TelegramAPIError:  # the payment is saved; a failed edit is cosmetic
            logger.warning("Could not edit the reminder message %s", message.message_id)


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
