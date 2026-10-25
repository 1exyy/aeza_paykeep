"""Test fixtures. Tests run against a real PostgreSQL (TEST_DATABASE_URL)."""

import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/invoice_keeper_test",
)
os.environ.update(
    {
        "DATABASE_URL": TEST_DATABASE_URL,
        "DB_NULL_POOL": "true",
        "ADMIN_LOGIN": "admin",
        "ADMIN_PASSWORD": "admin-test-password",
        "PUBLIC_BASE_URL": "http://test",
        "COOKIE_SECURE": "false",
        "DEV_MODE": "true",
        "APP_TZ_OFFSET": "+03:00",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "SMTP_HOST": "",
        "WEBHOOK_URL": "",
        "EXTRA_CHANNEL_URL": "",
        "SUPERVISOR_LOGIN": "boss",
        "SUPERVISOR_PASSWORD": "boss-test-password",
        "APPLY_BOT_TOKEN": "",
        "DEFAULT_TEAM_NAME": "aeza",
    }
)

from collections.abc import AsyncIterator, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core import clock  # noqa: E402
from app.core.config import apply_overrides, get_settings  # noqa: E402
from app.core.db import get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> None:
    """Clean database → alembic upgrade head (also checks the migrations on an empty DB)."""
    get_settings.cache_clear()
    cfg = _alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _real_clock() -> Iterator[None]:
    yield
    clock.reset_real_now()


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    clock.invalidate_cache()
    apply_overrides({})  # notification settings saved by a previous test
    tables = [t.name for t in Base.metadata.sorted_tables]
    if tables:
        async with get_sessionmaker()() as session:
            names = ", ".join(f'"{t}"' for t in tables)
            await session.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
            await session.commit()
    yield


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.services.bootstrap import on_startup

    await on_startup()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
