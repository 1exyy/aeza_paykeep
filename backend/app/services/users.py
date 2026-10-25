"""User management by the administrator (DOMAIN §1)."""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock, real_now
from app.core.errors import AppError, admin_protected, not_found, version_conflict
from app.core.security import hash_password
from app.models.user import User, UserSession
from app.schemas.user import UserCreate, UserPatch
from app.services import assignees, audit, telegram_link


def login_taken() -> AppError:
    return AppError(
        409,
        "login_taken",
        "Такой логин уже занят",
        [{"field": "login", "message": "Такой логин уже занят"}],
    )


async def _login_exists(
    db: AsyncSession, team_id: int, login: str, exclude_id: int | None = None
) -> bool:
    stmt = select(User.id).where(
        User.team_id == team_id, func.lower(User.login) == login, User.deleted_at.is_(None)
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return (await db.scalar(stmt)) is not None


async def revoke_sessions(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=real_now())
    )


async def get_manageable(db: AsyncSession, team_id: int, user_id: int) -> User:
    """Active user of the team for PATCH/DELETE; the protected administrator is refused."""
    user = await db.scalar(
        select(User)
        .where(User.id == user_id, User.team_id == team_id, User.deleted_at.is_(None))
        .with_for_update()
    )
    if user is None:
        raise not_found("Пользователь не найден")
    if user.is_protected:
        raise admin_protected()
    return user


async def create_user(
    db: AsyncSession, clock: Clock, actor: User, data: UserCreate, ip: str | None
) -> User:
    if await _login_exists(db, actor.team_id, data.login):
        raise login_taken()
    now = clock.now()
    user = User(
        team_id=actor.team_id,
        login=data.login,
        password_hash=hash_password(data.password),
        role="user",
        is_protected=False,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.flush()
    audit.record(
        db,
        clock,
        "user.create",
        actor=actor,
        object_type="user",
        object_id=user.id,
        details={"login": user.login},
        ip=ip,
    )
    if data.telegram:
        await telegram_link.set_by_admin(db, clock, actor, user, data.telegram, ip)
    return user


async def update_user(
    db: AsyncSession, clock: Clock, actor: User, user_id: int, data: UserPatch, ip: str | None
) -> User:
    if data.login is None and data.password is None and "telegram" not in data.model_fields_set:
        raise AppError.validation("body", "Передайте новый логин, пароль или Telegram")
    user = await get_manageable(db, actor.team_id, user_id)
    if data.expected_version is not None and data.expected_version != user.version:
        raise version_conflict()

    changed: list[str] = []
    details: dict[str, object] = {}
    if data.login is not None and data.login != user.login:
        if await _login_exists(db, actor.team_id, data.login, exclude_id=user.id):
            raise login_taken()
        details.update(login_from=user.login, login_to=data.login)
        user.login = data.login
        changed.append("login")
    if data.password is not None:
        # set by the administrator: the member must replace it at the next login
        user.password_hash = hash_password(data.password)
        user.must_change_password = True
        await revoke_sessions(db, user.id)
        changed.append("password")
    if "telegram" in data.model_fields_set and await telegram_link.set_by_admin(
        db, clock, actor, user, data.telegram or "", ip
    ):
        changed.append("telegram")
    if not changed:
        return user
    user.version += 1
    user.updated_at = clock.now()
    details["changed"] = changed
    audit.record(
        db,
        clock,
        "user.update",
        actor=actor,
        object_type="user",
        object_id=user.id,
        details=details,
        ip=ip,
    )
    return user


async def delete_user(
    db: AsyncSession, clock: Clock, actor: User, user_id: int, ip: str | None
) -> None:
    user = await get_manageable(db, actor.team_id, user_id)
    now = clock.now()
    user.deleted_at = now
    user.updated_at = now
    user.telegram_user_id = None
    user.telegram_username = None
    user.version += 1
    await revoke_sessions(db, user.id)
    await assignees.forget_user(db, user.id)
    audit.record(
        db,
        clock,
        "user.delete",
        actor=actor,
        object_type="user",
        object_id=user.id,
        details={"login": user.login},
        ip=ip,
    )
