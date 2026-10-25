"""Request dependencies: DB session, clock, authentication and roles (checked on the server)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock, get_clock, real_now
from app.core.config import get_settings, reset_scope, set_scope
from app.core.db import get_session
from app.core.errors import forbidden, password_change_required, unauthorized
from app.core.security import hash_token
from app.models.user import User, UserSession

SESSION_COOKIE = "ik_session"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Principal:
    user: User
    session: UserSession
    via_cookie: bool


async def clock_dep(db: AsyncSession = Depends(get_session)) -> Clock:
    return await get_clock(db)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def request_token(request: Request) -> tuple[str | None, bool]:
    """Bearer header wins over the cookie. Returns (token, via_cookie)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token, False
    cookie = request.cookies.get(SESSION_COOKIE)
    return (cookie, True) if cookie else (None, False)


def _origin(url: str) -> str:
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}".lower()


async def find_active_session(db: AsyncSession, token: str) -> tuple[UserSession, User] | None:
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == hash_token(token),
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > real_now(),
                User.deleted_at.is_(None),
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


async def current_principal(
    request: Request, db: AsyncSession = Depends(get_session)
) -> AsyncIterator[Principal]:
    token, via_cookie = request_token(request)
    if not token:
        raise unauthorized()
    found = await find_active_session(db, token)
    if found is None:
        raise unauthorized()
    session, user = found
    if via_cookie and request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin and _origin(origin) != _origin(get_settings().public_base_url):
            raise forbidden()
    if user.team_id is None:  # the supervisor: no team, no team channels
        yield Principal(user=user, session=session, via_cookie=via_cookie)
        return
    # Channels, reminders and events of this request use the user's team settings
    from app.services.notification_settings import team_settings

    settings, _row = await team_settings(db, user.team_id)
    scope = set_scope(settings)
    try:
        yield Principal(user=user, session=session, via_cookie=via_cookie)
    finally:
        reset_scope(scope)


async def current_account(principal: Principal = Depends(current_principal)) -> User:
    """Any signed-in account, even with a temporary password (/auth/me, /auth/password)."""
    return principal.user


async def current_user(principal: Principal = Depends(current_principal)) -> User:
    """A member of a team who may work: the supervisor and temporary passwords are refused."""
    user = principal.user
    if user.must_change_password:
        raise password_change_required()
    if user.role == "supervisor":
        raise forbidden()
    return user


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise forbidden()
    return user


async def require_supervisor(principal: Principal = Depends(current_principal)) -> User:
    user = principal.user
    if user.must_change_password:
        raise password_change_required()
    if user.role != "supervisor":
        raise forbidden()
    return user
