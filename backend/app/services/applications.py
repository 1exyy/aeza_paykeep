"""Team applications: submitted through the bot, decided by the supervisor.

Approve, in one transaction: the team, its protected administrator with a temporary password
(must change it at the first login) and the team's notification settings from the application.
After the commit the application bot tells the applicant how to sign in. Callers commit.
"""

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.apply_bot import send_to_applicant
from app.core.clock import Clock
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.core.security import hash_password
from app.models.app_settings import AppSettings
from app.models.application import TeamApplication
from app.models.team import Team
from app.models.user import User
from app.schemas.application import ApplicationInput
from app.services import audit, teams


def team_name_taken() -> AppError:
    return AppError(
        409,
        "team_name_taken",
        "Команда с таким названием уже есть",
        [{"field": "team_name", "message": "Команда с таким названием уже есть"}],
    )


def application_pending() -> AppError:
    return AppError(409, "application_pending", "Предыдущая заявка ещё рассматривается")


def not_pending() -> AppError:
    return AppError(409, "application_decided", "По заявке уже принято решение")


async def name_available(db: AsyncSession, slug: str, exclude_id: int | None = None) -> bool:
    """No team and no other open application with this name."""
    if await db.scalar(select(Team.id).where(Team.slug == slug)) is not None:
        return False
    stmt = select(TeamApplication.id).where(
        TeamApplication.team_slug == slug, TeamApplication.status == "pending"
    )
    if exclude_id is not None:
        stmt = stmt.where(TeamApplication.id != exclude_id)
    return await db.scalar(stmt) is None


async def submit(
    db: AsyncSession,
    clock: Clock,
    data: ApplicationInput,
    *,
    applicant_telegram_id: int,
    applicant_username: str | None,
    applicant_name: str | None,
) -> TeamApplication:
    """A new pending application (from the bot)."""
    slug = teams.normalize(data.team_name)
    if await db.scalar(
        select(TeamApplication.id).where(
            TeamApplication.applicant_telegram_id == applicant_telegram_id,
            TeamApplication.status == "pending",
        )
    ):
        raise application_pending()
    if not await name_available(db, slug):
        raise team_name_taken()
    application = TeamApplication(
        status="pending",
        team_name=data.team_name,
        team_slug=slug,
        admin_login=data.admin_login,
        applicant_telegram_id=applicant_telegram_id,
        applicant_username=(applicant_username or None) and applicant_username[:64],
        applicant_name=(applicant_name or None) and applicant_name[:128],
        telegram_chat_id=data.telegram_chat_id,
        smtp=data.smtp.as_settings() if data.smtp else None,
        created_at=clock.now(),
    )
    db.add(application)
    await db.flush()
    audit.record(
        db,
        clock,
        "application.submit",
        actor=None,
        source="telegram",
        object_type="team_application",
        object_id=application.id,
        details={"team": data.team_name, "admin_login": data.admin_login},
    )
    return application


async def _pending(db: AsyncSession, application_id: int) -> TeamApplication:
    application = await db.scalar(
        select(TeamApplication).where(TeamApplication.id == application_id).with_for_update()
    )
    if application is None:
        raise not_found("Заявка не найдена")
    if application.status != "pending":
        raise not_pending()
    return application


def temporary_password() -> str:
    return secrets.token_urlsafe(9)  # 12 characters, ≥ 8 as the password rules require


async def approve(
    db: AsyncSession, clock: Clock, supervisor: User, application_id: int, ip: str | None
) -> tuple[TeamApplication, str]:
    """Create the team; returns the application and the administrator's temporary password."""
    application = await _pending(db, application_id)
    if not await name_available(db, application.team_slug, exclude_id=application.id):
        raise team_name_taken()
    now = clock.now()
    team = Team(name=application.team_name, slug=application.team_slug, created_at=now)
    db.add(team)
    await db.flush()
    password = temporary_password()
    admin = User(
        team_id=team.id,
        login=application.admin_login,
        password_hash=hash_password(password),
        role="admin",
        is_protected=True,
        must_change_password=True,
        telegram_user_id=application.applicant_telegram_id,
        telegram_username=application.applicant_username,
        created_at=now,
        updated_at=now,
    )
    db.add(admin)
    values: dict[str, Any] = {"telegram_chat_id": application.telegram_chat_id}
    values.update(application.smtp or {})
    db.add(AppSettings(team_id=team.id, values=values, version=1, updated_at=now))
    application.status, application.team_id = "approved", team.id
    application.decided_at, application.decided_by_login = now, supervisor.login
    await db.flush()
    audit.record(
        db,
        clock,
        "application.approve",
        actor=supervisor,
        object_type="team_application",
        object_id=application.id,
        details={"team": team.name, "team_id": team.id, "admin_login": admin.login},
        ip=ip,
    )
    return application, password


async def reject(
    db: AsyncSession,
    clock: Clock,
    supervisor: User,
    application_id: int,
    reason: str,
    ip: str | None,
) -> TeamApplication:
    application = await _pending(db, application_id)
    application.status, application.reject_reason = "rejected", reason
    application.decided_at, application.decided_by_login = clock.now(), supervisor.login
    audit.record(
        db,
        clock,
        "application.reject",
        actor=supervisor,
        object_type="team_application",
        object_id=application.id,
        details={"team": application.team_name, "reason": reason},
        ip=ip,
    )
    return application


def approved_text(application: TeamApplication, password: str) -> str:
    url = get_settings().public_base_url
    return (
        f"✅ Заявка одобрена: команда «{application.team_name}» создана.\n\n"
        f"Адрес: {url}\n"
        f"Команда: {application.team_name}\n"
        f"Логин: {application.admin_login}\n"
        f"Временный пароль: {password}\n\n"
        "При первом входе задайте свой пароль. Напоминания будут приходить в указанный чат: "
        "проверьте их во вкладке «Настройки уведомлений»."
    )


def rejected_text(application: TeamApplication) -> str:
    return (
        f"❌ Заявка на команду «{application.team_name}» отклонена.\n"
        f"Причина: {application.reject_reason}\n\n"
        "Можно подать новую заявку."
    )


async def notify(application: TeamApplication, text: str) -> bool:
    return await send_to_applicant(application.applicant_telegram_id, text)
