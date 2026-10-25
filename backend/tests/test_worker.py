"""Worker process: the Telegram bot task must survive network failures."""

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetMe

from app.worker import __main__ as worker
from app.worker import bot as bot_module


class FlakyDispatcher:
    """start_polling fails `failures` times (like getMe timing out), then returns."""

    calls = 0

    def __init__(self, failures: int) -> None:
        self.failures = failures

    async def start_polling(self, bot, handle_signals: bool) -> None:  # noqa: ANN001
        FlakyDispatcher.calls += 1
        if FlakyDispatcher.calls <= self.failures:
            raise TelegramNetworkError(method=GetMe(), message="Request timeout error")


async def test_bot_retries_with_backoff_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FlakyDispatcher.calls = 0
    built: list[FlakyDispatcher] = []

    def build() -> FlakyDispatcher:
        built.append(FlakyDispatcher(failures=7))
        return built[-1]

    monkeypatch.setattr(bot_module, "build_dispatcher", build)
    monkeypatch.setattr("app.channels.telegram.get_bot", lambda: object())
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    await worker._bot(sleep=fake_sleep)
    assert FlakyDispatcher.calls == 8
    assert waits == [5, 10, 20, 40, 80, 160, 300]  # exponential, capped at 5 minutes
    assert len(built) == 1  # the same dispatcher is reused on every retry


def test_router_can_be_attached_only_once() -> None:
    """Why _bot must not rebuild the dispatcher: the second attach raises RuntimeError."""
    bot_module.build_dispatcher()
    with pytest.raises(RuntimeError):
        bot_module.build_dispatcher()
    bot_module.router._parent_router = None  # detach for other tests


async def test_bot_session_timeout_and_ipv6_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    from app.channels import telegram
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(
        settings, "telegram_bot_token", type(settings.telegram_bot_token)("123456:TEST")
    )
    monkeypatch.setattr(settings, "telegram_ipv6_only", True)
    monkeypatch.setattr(settings, "telegram_timeout", 25)
    await telegram.close_bot()
    try:
        bot = telegram.get_bot()
        assert bot.session.timeout == 25
        assert bot.session._connector_init["family"] == socket.AF_INET6
    finally:
        await telegram.close_bot()
