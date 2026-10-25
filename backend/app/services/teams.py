"""Teams: name normalization and the first team from .env."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import real_now
from app.core.config import get_settings
from app.models.team import Team


def normalize(name: str) -> str:
    """The name as typed at login: case-insensitive, extra spaces ignored."""
    return " ".join(name.split()).lower()


async def by_name(db: AsyncSession, name: str) -> Team | None:
    slug = normalize(name)
    if not slug:
        return None
    return await db.scalar(select(Team).where(Team.slug == slug))


async def ensure_default(db: AsyncSession) -> Team:
    """The first team (DEFAULT_TEAM_NAME): created by the migration, or here on an empty DB."""
    name = " ".join(get_settings().default_team_name.split()) or "aeza"
    await db.execute(
        insert(Team)
        .values(name=name, slug=normalize(name), created_at=real_now())
        .on_conflict_do_nothing(index_elements=[Team.slug])
    )
    team = await db.scalar(select(Team).where(Team.slug == normalize(name)))
    assert team is not None
    return team
