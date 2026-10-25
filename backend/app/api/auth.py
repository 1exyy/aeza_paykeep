"""POST /auth/login, GET /auth/me, POST /auth/logout (DOMAIN §2)."""

import math
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SESSION_COOKIE,
    Principal,
    client_ip,
    clock_dep,
    current_account,
    current_principal,
    current_user,
    find_active_session,
    request_token,
)
from app.core import totp
from app.core.clock import Clock, real_now, to_local
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.security import hash_password, hash_token, new_session_token, verify_password
from app.models.notification import PersonalReminder
from app.models.team import Team
from app.models.user import LoginAttempt, User, UserSession
from app.schemas.user import (
    DmNotificationPreference,
    DmReminderDays,
    LoginRequest,
    LoginResponse,
    PasswordChange,
    SessionOut,
    TotpBegin,
    TotpConfirm,
    TotpSetup,
    UserOut,
)
from app.services import audit, teams

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_TTL = timedelta(days=7)
RATE_WINDOW = timedelta(minutes=5)
RATE_MAX_FAILURES = 5
TOTP_PENDING_TTL = timedelta(minutes=10)
TOTP_RATE_WINDOW = timedelta(minutes=5)


def _require_admin_totp(user: User) -> None:
    if user.role != "admin":
        raise AppError(403, "forbidden", "Двухфакторная защита доступна администратору")


async def _verify_totp(db: AsyncSession, user: User, code: str, secret: str) -> int:
    now = real_now()
    if (
        user.totp_failures >= RATE_MAX_FAILURES
        and user.totp_failed_at is not None
        and now - user.totp_failed_at < TOTP_RATE_WINDOW
    ):
        raise AppError(429, "too_many_attempts", "Слишком много попыток. Повторите через 5 минут")
    counter = totp.matching_counter(
        totp.decrypt(secret), code, now, after=user.totp_last_counter
    )
    if counter is None:
        if user.totp_failed_at is None or now - user.totp_failed_at >= TOTP_RATE_WINDOW:
            user.totp_failures = 0
        user.totp_failures += 1
        user.totp_failed_at = now
        await db.commit()
        raise AppError.validation("totp_code", "Неверный или уже использованный код")
    user.totp_failures = 0
    user.totp_failed_at = None
    return counter


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=get_settings().cookie_secure
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> LoginResponse:
    login_name = body.login.strip().lower()[:64]
    team_slug = teams.normalize(body.team)[:64]
    now = real_now()
    ip = client_ip(request)
    attempts = (LoginAttempt.team == team_slug, LoginAttempt.login == login_name)

    failures, oldest = (
        await db.execute(
            select(func.count(), func.min(LoginAttempt.attempted_at)).where(
                *attempts, LoginAttempt.attempted_at > now - RATE_WINDOW
            )
        )
    ).one()
    if failures >= RATE_MAX_FAILURES:
        retry_after = max(1, math.ceil((oldest + RATE_WINDOW - now).total_seconds()))
        audit.record(
            db,
            clock,
            "auth.login_failed",
            actor=None,
            result="failure",
            details={"team": team_slug, "login": login_name, "reason": "too_many_attempts"},
            ip=ip,
        )
        await db.commit()
        raise AppError(
            429,
            "too_many_attempts",
            f"Слишком много попыток. Попробуйте через {math.ceil(retry_after / 60)} мин.",
            headers={"Retry-After": str(retry_after)},
        )

    # The login is looked up inside the team (an empty team: the supervisor only);
    # one message for every mistake so the team names cannot be probed
    team = await teams.by_name(db, body.team) if team_slug else None
    if team_slug and team is None:
        user = None
    else:
        user = await db.scalar(
            select(User).where(
                User.team_id == team.id if team else User.role == "supervisor",
                func.lower(User.login) == login_name,
                User.deleted_at.is_(None),
            )
        )
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        db.add(LoginAttempt(team=team_slug, login=login_name, attempted_at=now))
        audit.record(
            db,
            clock,
            "auth.login_failed",
            actor=None,
            team_id=team.id if team else None,
            result="failure",
            details={"team": team_slug, "login": login_name},
            ip=ip,
        )
        await db.commit()
        raise AppError(401, "invalid_credentials", "Неверная команда, логин или пароль")

    await db.execute(delete(LoginAttempt).where(*attempts))
    token = new_session_token()
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        created_at=now,
        expires_at=now + SESSION_TTL,
        last_seen_at=now,
    )
    db.add(session)
    await db.flush()
    audit.record(
        db,
        clock,
        "auth.login",
        actor=user,
        object_type="user",
        object_id=user.id,
        details={"session_id": session.id},
        ip=ip,
    )
    await db.commit()
    _set_cookie(response, token)
    return LoginResponse(
        user=UserOut.of(user),
        session=SessionOut(token=token, expires_at=to_local(session.expires_at)),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_account)) -> UserOut:
    return UserOut.of(user)


@router.post("/me/totp/begin", response_model=TotpSetup)
async def begin_totp(
    body: TotpBegin,
    request: Request,
    response: Response,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> TotpSetup:
    user = await db.scalar(select(User).where(User.id == principal.user.id).with_for_update())
    assert user is not None
    _require_admin_totp(user)
    if user.totp_enabled:
        raise AppError(409, "totp_already_enabled", "Двухфакторная защита уже подключена")
    if not verify_password(user.password_hash, body.current_password):
        raise AppError.validation("current_password", "Неверный текущий пароль")
    secret = totp.new_secret()
    user.totp_pending_secret = totp.encrypt(secret)
    user.totp_pending_at = real_now()
    user.updated_at = clock.now()
    team = await db.get(Team, user.team_id)
    audit.record(
        db, clock, "auth.totp_setup_started", actor=user, object_type="user",
        object_id=user.id, ip=client_ip(request),
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return TotpSetup(
        secret=secret,
        otpauth_uri=totp.provisioning_uri(secret, team.name if team else "team", user.login),
        expires_at=to_local(user.totp_pending_at + TOTP_PENDING_TTL),
    )


@router.post("/me/totp/confirm", response_model=UserOut)
async def confirm_totp(
    body: TotpConfirm,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> UserOut:
    user = await db.scalar(select(User).where(User.id == principal.user.id).with_for_update())
    assert user is not None
    _require_admin_totp(user)
    if user.totp_enabled:
        raise AppError(409, "totp_already_enabled", "Двухфакторная защита уже подключена")
    if (
        user.totp_pending_secret is None
        or user.totp_pending_at is None
        or real_now() - user.totp_pending_at > TOTP_PENDING_TTL
    ):
        raise AppError(409, "totp_setup_expired", "Начните привязку заново")
    counter = await _verify_totp(db, user, body.code, user.totp_pending_secret)
    user.totp_secret = user.totp_pending_secret
    user.totp_pending_secret = None
    user.totp_pending_at = None
    user.totp_last_counter = counter
    user.version += 1
    user.updated_at = clock.now()
    audit.record(
        db, clock, "auth.totp_enabled", actor=user, object_type="user",
        object_id=user.id, ip=client_ip(request),
    )
    await db.commit()
    return UserOut.of(user)


@router.patch("/me/notifications", response_model=UserOut)
async def update_my_notifications(
    body: DmNotificationPreference,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> UserOut:
    if user.telegram_dm_enabled != body.telegram_dm_enabled:
        user.telegram_dm_enabled = body.telegram_dm_enabled
        user.version += 1
        user.updated_at = clock.now()
        audit.record(
            db,
            clock,
            "user.telegram_dm_preference_changed",
            actor=user,
            object_type="user",
            object_id=user.id,
            details={"telegram_dm_enabled": body.telegram_dm_enabled},
            ip=client_ip(request),
        )
        if body.telegram_dm_enabled:
            await db.execute(
                update(PersonalReminder)
                .where(
                    PersonalReminder.user_id == user.id,
                    PersonalReminder.status == "pending",
                )
                .values(next_attempt_at=real_now())
            )
        await db.commit()
    return UserOut.of(user)


@router.patch("/me/reminder-days", response_model=UserOut)
async def update_my_reminder_days(
    body: DmReminderDays,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> UserOut:
    if user.telegram_dm_days_before != body.telegram_dm_days_before:
        user.telegram_dm_days_before = body.telegram_dm_days_before
        user.version += 1
        user.updated_at = clock.now()
        await db.execute(
            update(PersonalReminder)
            .where(
                PersonalReminder.user_id == user.id,
                PersonalReminder.status == "pending",
            )
            .values(next_attempt_at=real_now())
        )
        audit.record(
            db,
            clock,
            "user.telegram_dm_days_changed",
            actor=user,
            object_type="user",
            object_id=user.id,
            details={"telegram_dm_days_before": body.telegram_dm_days_before},
            ip=client_ip(request),
        )
        await db.commit()
    return UserOut.of(user)


@router.post("/password", response_model=UserOut)
async def change_password(
    body: PasswordChange,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> UserOut:
    """Change one's own password; clears a temporary one. Other sessions are signed out."""
    user = principal.user
    if user.role == "supervisor":
        raise AppError(403, "forbidden", "Супервайзер не может менять свой пароль")
    if user.role == "admin":
        locked = await db.scalar(select(User).where(User.id == user.id).with_for_update())
        assert locked is not None
        user = locked
    if not verify_password(user.password_hash, body.current_password):
        raise AppError.validation("current_password", "Неверный текущий пароль")
    if body.new_password == body.current_password:
        raise AppError.validation("new_password", "Новый пароль должен отличаться от текущего")
    if user.role == "admin":
        if not user.totp_secret:
            raise AppError(403, "totp_required", "Сначала подключите двухфакторную защиту")
        if not body.totp_code:
            raise AppError.validation("totp_code", "Введите код из приложения-аутентификатора")
        user.totp_last_counter = await _verify_totp(db, user, body.totp_code, user.totp_secret)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.version += 1
    user.updated_at = clock.now()
    await db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.id != principal.session.id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=real_now())
    )
    audit.record(
        db,
        clock,
        "auth.password_change",
        actor=user,
        object_type="user",
        object_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return UserOut.of(user)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> Response:
    token, _ = request_token(request)
    if token:
        found = await find_active_session(db, token)
        if found is not None:
            session, user = found
            session.revoked_at = real_now()
            audit.record(
                db,
                clock,
                "auth.logout",
                actor=user,
                object_type="user",
                object_id=user.id,
                details={"session_id": session.id},
                ip=client_ip(request),
            )
            await db.commit()
    response = Response(status_code=204)
    _clear_cookie(response)
    return response
