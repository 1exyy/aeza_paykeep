"""Telegram account ↔ user link (DOMAIN §9). Callers commit unless noted.

- Mini App initData (the user links themselves);
- the administrator sets `@username` or a numeric ID;
- a username-only link gets its ID when the person first writes to the bot.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock, real_now
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import InitDataError, verify_init_data
from app.models.user import User
from app.services import audit


def already_linked() -> AppError:
    return AppError(
        409,
        "telegram_already_linked",
        "Этот Telegram-аккаунт уже привязан к другому пользователю",
    )


async def link(db: AsyncSession, clock: Clock, user: User, init_data: str, ip: str | None) -> User:
    token = get_settings().telegram_bot_token.get_secret_value()
    try:
        tg_user = verify_init_data(init_data, token, real_now())
    except InitDataError as exc:
        audit.record(
            db,
            clock,
            "telegram.link",
            actor=user,
            object_type="user",
            object_id=user.id,
            result="failure",
            details={"reason": str(exc)},
            ip=ip,
        )
        await db.commit()
        raise AppError(
            422,
            "telegram_invalid_init_data",
            "Не удалось проверить данные Telegram. Откройте приложение из бота заново",
        ) from exc

    telegram_id = tg_user["id"]
    owner = await db.scalar(
        select(User).where(
            User.team_id == user.team_id,
            User.telegram_user_id == telegram_id,
            User.deleted_at.is_(None),
        )
    )
    if owner is not None and owner.id != user.id:
        raise already_linked()
    username = tg_user.get("username")
    user.telegram_username = str(username)[:64] if username else None
    if user.telegram_user_id != telegram_id:
        user.telegram_user_id = telegram_id
        user.version += 1
        user.updated_at = clock.now()
        audit.record(
            db,
            clock,
            "telegram.link",
            actor=user,
            object_type="user",
            object_id=user.id,
            details={"telegram_user_id": telegram_id, "username": tg_user.get("username")},
            ip=ip,
        )
    return user


async def unlink(db: AsyncSession, clock: Clock, user: User, ip: str | None) -> None:
    if user.telegram_user_id is None:
        return
    old = user.telegram_user_id
    user.telegram_user_id = None
    user.telegram_username = None
    user.version += 1
    user.updated_at = clock.now()
    audit.record(
        db,
        clock,
        "telegram.unlink",
        actor=user,
        object_type="user",
        object_id=user.id,
        details={"telegram_user_id": old},
        ip=ip,
    )


async def _username_owner(
    db: AsyncSession, team_id: int, username: str, exclude_id: int
) -> User | None:
    return await db.scalar(
        select(User).where(
            User.team_id == team_id,
            func.lower(User.telegram_username) == username.lower(),
            User.deleted_at.is_(None),
            User.id != exclude_id,
        )
    )


async def set_by_admin(
    db: AsyncSession, clock: Clock, actor: User, user: User, value: str, ip: str | None
) -> bool:
    """Apply a normalized admin value: '' unlinks, digits = ID, '@name' = username.

    Returns True when something changed (the caller bumps the version).
    """
    old = {"telegram_user_id": user.telegram_user_id, "username": user.telegram_username}
    if value == "":
        if user.telegram_user_id is None and user.telegram_username is None:
            return False
        user.telegram_user_id, user.telegram_username = None, None
        action = "telegram.unlink"
    elif value.isdigit():
        telegram_id = int(value)
        if user.telegram_user_id == telegram_id:
            return False
        owner = await db.scalar(
            select(User).where(
                User.team_id == user.team_id,
                User.telegram_user_id == telegram_id,
                User.deleted_at.is_(None),
                User.id != user.id,
            )
        )
        if owner is not None:
            raise already_linked()
        user.telegram_user_id, user.telegram_username = telegram_id, None
        action = "telegram.link"
    else:
        username = value.removeprefix("@")
        if (user.telegram_username or "").lower() == username:
            return False
        if await _username_owner(db, user.team_id, username, user.id) is not None:
            raise already_linked()
        # The ID is learned when this person writes to the bot (bind_on_contact).
        user.telegram_user_id, user.telegram_username = None, username
        action = "telegram.link"
    audit.record(
        db,
        clock,
        action,
        actor=actor,
        object_type="user",
        object_id=user.id,
        details={
            "user": user.login,
            "from": old,
            "to": {"telegram_user_id": user.telegram_user_id, "username": user.telegram_username},
        },
        ip=ip,
    )
    return True


async def bind_on_contact(
    db: AsyncSession,
    clock: Clock,
    telegram_id: int,
    username: str | None,
    team_id: int | None = None,
) -> list[User]:
    """Users behind a Telegram account the bot just heard from, one per team.

    Linked by ID → those users (the username is refreshed). In every team where the
    administrator set this person up by username and no one has this ID yet, the ID is bound
    now (audit telegram.link, source telegram). `team_id` limits it to one team. Flushes, the
    caller commits.
    """
    scope = [User.team_id == team_id] if team_id is not None else []
    users = list(
        await db.scalars(
            select(User)
            .where(User.telegram_user_id == telegram_id, User.deleted_at.is_(None), *scope)
            .order_by(User.team_id)
        )
    )
    for user in users:
        if username and user.telegram_username != username[:64]:
            user.telegram_username = username[:64]
    if username:
        linked_teams = {user.team_id for user in users}
        candidates = await db.scalars(
            select(User)
            .where(
                func.lower(User.telegram_username) == username.lower(),
                User.telegram_user_id.is_(None),
                User.deleted_at.is_(None),
                *scope,
            )
            .order_by(User.team_id)
            .with_for_update()
        )
        for user in candidates:
            if user.team_id in linked_teams:
                continue  # this Telegram already belongs to someone else in that team
            user.telegram_user_id, user.telegram_username = telegram_id, username[:64]
            user.version += 1
            user.updated_at = clock.now()
            audit.record(
                db,
                clock,
                "telegram.link",
                actor=user,
                source="telegram",
                object_type="user",
                object_id=user.id,
                details={"telegram_user_id": telegram_id, "username": username, "via": "username"},
            )
            linked_teams.add(user.team_id)
            users.append(user)
    await db.flush()
    return users
