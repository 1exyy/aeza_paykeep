"""Application bot (long polling in the worker): renders services/apply_flow."""

import contextlib
import logging

from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.types import User as TgUser

from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.services import apply_flow
from app.services.apply_flow import Applicant, Reply

logger = logging.getLogger("app.worker.apply_bot")
router = Router(name="invoice-keeper-apply")


def _who(user: TgUser) -> Applicant:
    return Applicant(telegram_id=user.id, username=user.username, name=user.full_name or None)


def _markup(reply: Reply) -> InlineKeyboardMarkup | None:
    if not reply.buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=data)] for label, data in reply.buttons
        ]
    )


async def check_chat(chat_id: str) -> str | None:
    """The main (reminder) bot must be able to post in the team's chat."""
    if not get_settings().telegram_bot_token.get_secret_value():
        return None  # no main bot on this server: the supervisor checks it after approval
    from app.channels.telegram import get_bot

    try:
        await get_bot().send_message(
            chat_id=chat_id,
            text="✅ Проверка связи Invoice Keeper: сюда будут приходить напоминания о платежах.",
            request_timeout=20,
        )
    except TelegramAPIError as exc:
        return exc.message or type(exc).__name__
    except (TimeoutError, OSError) as exc:
        return f"сеть: {type(exc).__name__}"
    return None


async def _answer(message: Message, reply: Reply) -> None:
    if reply.delete_incoming:
        try:
            await message.delete()
        except TelegramAPIError:
            logger.warning("Could not delete a message with a password")
    await message.answer(reply.text, reply_markup=_markup(reply))


@router.message(CommandStart(), F.chat.type == "private")
async def on_start(message: Message) -> None:
    if message.from_user is None:
        return
    async with get_sessionmaker()() as db:
        reply = await apply_flow.start(db, await get_clock(db), _who(message.from_user))
        await db.commit()
    await _answer(message, reply)


@router.message(Command("cancel"), F.chat.type == "private")
async def on_cancel(message: Message) -> None:
    if message.from_user is None:
        return
    async with get_sessionmaker()() as db:
        reply = await apply_flow.cancel(db, _who(message.from_user))
        await db.commit()
    await _answer(message, reply)


@router.message(F.chat.type == "private", F.text)
async def on_text(message: Message) -> None:
    if message.from_user is None or message.text is None:
        return
    async with get_sessionmaker()() as db:
        reply = await apply_flow.on_text(
            db, await get_clock(db), _who(message.from_user), message.text, check_chat
        )
        await db.commit()
    await _answer(message, reply)


@router.callback_query(F.data.startswith("apply:"))
async def on_button(callback: CallbackQuery) -> None:
    async with get_sessionmaker()() as db:
        reply = await apply_flow.on_button(
            db, await get_clock(db), _who(callback.from_user), callback.data or "", check_chat
        )
        await db.commit()
    await callback.answer()
    if isinstance(callback.message, Message):
        with contextlib.suppress(TelegramAPIError):  # an old message: the buttons stay
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(reply.text, reply_markup=_markup(reply))


def build_apply_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
