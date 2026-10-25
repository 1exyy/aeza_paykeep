"""Background worker: `python -m app.worker`.

- jobs every 60 s: period generator → reminders;
- delivery dispatcher every 5 s;
- Telegram bot long polling (only when TELEGRAM_BOT_TOKEN is set).
Several workers may run at once: claiming uses FOR UPDATE SKIP LOCKED.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import dispose_engine, get_sessionmaker
from app.core.logging import setup_logging
from app.services.notification_settings import refresh as refresh_settings
from app.worker.jobs import dispatch_deliveries, run_cycle

logger = logging.getLogger("app.worker")

JOBS_INTERVAL = 60
DISPATCH_INTERVAL = 5


async def _loop(name: str, interval: int, job: Callable[[AsyncSession], Awaitable[object]]) -> None:
    while True:
        try:
            async with get_sessionmaker()() as db:
                await refresh_settings(db)  # the administrator may change channels at any time
                await job(db)
        except Exception:  # keep the loop alive; the next tick retries
            logger.exception("%s failed", name)
        await asyncio.sleep(interval)


BOT_RETRY_MIN = 5
BOT_RETRY_MAX = 300


async def _bot(sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Long polling that survives Telegram being unreachable (e.g. getMe timeout at start).

    A bot failure must never stop the jobs and the dispatcher: retry with backoff instead.
    """
    from app.channels.telegram import get_bot
    from app.worker.bot import build_dispatcher

    await _polling("Telegram bot", build_dispatcher, get_bot, sleep)


async def _apply_bot(sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """The application bot, same retry rules."""
    from app.channels.apply_bot import get_apply_bot
    from app.worker.apply_bot import build_apply_dispatcher

    await _polling("Application bot", build_apply_dispatcher, get_apply_bot, sleep)


async def _polling(
    name: str,
    build: Callable[[], Dispatcher],
    get: Callable[[], Bot],
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    dispatcher = build()  # once: the router can be attached to one dispatcher only
    delay = BOT_RETRY_MIN
    while True:
        try:
            await dispatcher.start_polling(get(), handle_signals=False)
            return  # stopped on purpose
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "%s is unavailable (%s); retrying in %d s", name, type(exc).__name__, delay
            )
            await sleep(delay)
            delay = min(delay * 2, BOT_RETRY_MAX)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    tasks = [
        asyncio.create_task(_loop("jobs", JOBS_INTERVAL, run_cycle)),
        asyncio.create_task(_loop("dispatcher", DISPATCH_INTERVAL, dispatch_deliveries)),
    ]
    if settings.telegram_bot_token.get_secret_value():
        tasks.append(asyncio.create_task(_bot()))
        logger.info("Worker started: jobs, dispatcher, Telegram bot")
    else:
        logger.info("Worker started: jobs, dispatcher (TELEGRAM_BOT_TOKEN is empty: no bot)")
    if settings.apply_bot_token.get_secret_value():
        tasks.append(asyncio.create_task(_apply_bot()))
        logger.info("Application bot started")
    if not settings.telegram_enabled:
        logger.warning("Telegram channel is off (no bot token): reminders are not queued")
    try:
        await asyncio.gather(*tasks)
    finally:
        from app.channels.apply_bot import close_apply_bot
        from app.channels.telegram import close_bot

        await close_bot()
        await close_apply_bot()
        await dispose_engine()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
