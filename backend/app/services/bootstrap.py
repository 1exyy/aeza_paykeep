"""Startup tasks of the API process."""

import logging

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock, real_now
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.security import hash_password, verify_password
from app.models.user import User, UserSession
from app.services import teams

logger = logging.getLogger("app.bootstrap")


async def _apply_env_password(db: AsyncSession, user: User, password: str) -> bool:
    """Apply the .env password only when it changed since it was last applied.

    A password changed in the app (POST /auth/password) then survives restarts; changing
    ADMIN_PASSWORD / SUPERVISOR_PASSWORD in .env still resets it. Returns True on a reset.
    """
    if user.env_password_hash and verify_password(user.env_password_hash, password):
        return False  # .env unchanged: keep whatever the user set
    if verify_password(user.password_hash, password):
        user.env_password_hash = user.password_hash  # first start after the upgrade
        return False
    user.password_hash = hash_password(password)
    user.env_password_hash = user.password_hash
    user.must_change_password = False
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=real_now())
    )
    return True


async def ensure_admin(db: AsyncSession) -> User | None:
    """Create or update the single protected administrator from ADMIN_LOGIN / ADMIN_PASSWORD."""
    settings = get_settings()
    login = settings.admin_login.strip().lower()
    password = settings.admin_password.get_secret_value()
    if not login or not password:
        logger.error("ADMIN_LOGIN/ADMIN_PASSWORD are not set: administrator login is disabled")
        return None

    clock = await get_clock(db)
    now = clock.now()
    team = await teams.ensure_default(db)  # The .env administrator runs the first team
    clash = await db.scalar(
        select(User).where(
            User.team_id == team.id,
            func.lower(User.login) == login,
            User.deleted_at.is_(None),
            User.is_protected.is_(False),
        )
    )
    if clash is not None:
        raise RuntimeError(f"ADMIN_LOGIN '{login}' is already used by a regular user")

    protected = select(User).where(User.team_id == team.id, User.is_protected.is_(True))
    admin = await db.scalar(protected)
    if admin is None:
        admin = User(
            team_id=team.id,
            login=login,
            password_hash=hash_password(password),
            role="admin",
            is_protected=True,
            created_at=now,
            updated_at=now,
        )
        admin.env_password_hash = admin.password_hash
        db.add(admin)
    else:
        changed = False
        if admin.login != login or admin.role != "admin" or admin.deleted_at is not None:
            admin.login, admin.role, admin.deleted_at = login, "admin", None
            changed = True
        if await _apply_env_password(db, admin, password):
            changed = True
        if changed:
            admin.updated_at = now
            admin.version += 1
    try:
        await db.commit()
    except IntegrityError:  # another process created it at the same moment
        await db.rollback()
        return await db.scalar(protected)
    return admin


async def ensure_supervisor(db: AsyncSession) -> User | None:
    """The single supervisor from SUPERVISOR_LOGIN / SUPERVISOR_PASSWORD."""
    settings = get_settings()
    login = settings.supervisor_login.strip().lower()
    password = settings.supervisor_password.get_secret_value()
    if not login or not password:
        logger.info("SUPERVISOR_LOGIN/SUPERVISOR_PASSWORD are not set: no supervisor")
        return None
    clock = await get_clock(db)
    now = clock.now()
    supervisor = await db.scalar(select(User).where(User.role == "supervisor"))
    if supervisor is None:
        supervisor = User(
            team_id=None,
            login=login,
            password_hash=hash_password(password),
            role="supervisor",
            is_protected=True,
            created_at=now,
            updated_at=now,
        )
        supervisor.env_password_hash = supervisor.password_hash
        db.add(supervisor)
    else:
        changed = supervisor.login != login or supervisor.deleted_at is not None
        supervisor.login, supervisor.deleted_at = login, None
        if await _apply_env_password(db, supervisor, password):
            changed = True
        if changed:
            supervisor.updated_at = now
            supervisor.version += 1
    try:
        await db.commit()
    except IntegrityError:  # another process created it at the same moment
        await db.rollback()
        return await db.scalar(select(User).where(User.role == "supervisor"))
    return supervisor


async def on_startup() -> None:
    from app.services.notification_settings import refresh

    async with get_sessionmaker()() as db:
        await ensure_admin(db)
        await ensure_supervisor(db)
        await refresh(db)
