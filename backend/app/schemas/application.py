"""Team applications: what the bot collects and what the supervisor sees."""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.clock import to_local
from app.models.application import TeamApplication
from app.schemas.settings import NotificationSettingsPatch, SmtpSecurity
from app.schemas.user import _normalize_login

_TEAM_RE = re.compile(r"^[\w .\-]{2,64}$")
_CHAT_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")
TEAM_MESSAGE = "Название команды: 2–64 символа — буквы, цифры, пробел, точка, дефис, подчёркивание"


def clean_team_name(value: str) -> str:
    name = " ".join(value.split())
    if not _TEAM_RE.match(name):
        raise ValueError(TEAM_MESSAGE)
    return name


class SmtpInput(BaseModel):
    """Optional mail settings of a new team, checked like the admin's settings tab."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    host: str
    port: int = Field(587, ge=1, le=65535)
    security: SmtpSecurity = "starttls"
    user: str = ""
    password: str = ""
    from_address: str = Field("", alias="from")
    recipients: list[str] = Field(min_length=1, max_length=50)

    def as_settings(self) -> dict[str, Any]:
        """Validated values in Settings field names (the team's app_settings)."""
        checked = NotificationSettingsPatch.model_validate(
            {
                "smtp_host": self.host,
                "smtp_port": self.port,
                "smtp_user": self.user,
                "smtp_from": self.from_address,
                "email_recipients": self.recipients,
            }
        )
        if not checked.smtp_host:
            raise ValueError("Укажите SMTP-сервер")
        return {
            "smtp_host": checked.smtp_host,
            "smtp_port": checked.smtp_port,
            "smtp_user": checked.smtp_user or "",
            "smtp_password": self.password,
            "smtp_from": checked.smtp_from or "",
            "smtp_ssl": self.security == "ssl",
            "smtp_starttls": self.security == "starttls",
            "email_recipients": ", ".join(checked.email_recipients or []),
        }


class ApplicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_name: str
    admin_login: str
    telegram_chat_id: str
    smtp: SmtpInput | None = None

    @field_validator("team_name")
    @classmethod
    def _v_team(cls, v: str) -> str:
        return clean_team_name(v)

    @field_validator("admin_login")
    @classmethod
    def _v_login(cls, v: str) -> str:
        return _normalize_login(v)

    @field_validator("telegram_chat_id")
    @classmethod
    def _v_chat(cls, v: str) -> str:
        v = v.strip()
        if not _CHAT_RE.match(v):
            raise ValueError("ID чата: число (у групп и каналов начинается с -100) или @имя_канала")
        return v


class ApplicantOut(BaseModel):
    telegram_id: int
    username: str | None
    name: str | None


class SmtpOut(BaseModel):
    host: str
    port: int
    security: SmtpSecurity
    user: str
    password_set: bool
    from_address: str = Field(serialization_alias="from")
    recipients: list[str]


class ApplicationOut(BaseModel):
    id: int
    status: Literal["pending", "approved", "rejected"]
    team_name: str
    admin_login: str
    applicant: ApplicantOut
    telegram_chat_id: str
    smtp: SmtpOut | None
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    reject_reason: str | None
    team_id: int | None

    @classmethod
    def of(cls, a: TeamApplication) -> "ApplicationOut":
        smtp = None
        if a.smtp:
            s = a.smtp
            smtp = SmtpOut(
                host=s.get("smtp_host", ""),
                port=int(s.get("smtp_port", 587)),
                security="ssl"
                if s.get("smtp_ssl")
                else "starttls"
                if s.get("smtp_starttls")
                else "none",
                user=s.get("smtp_user", ""),
                password_set=bool(s.get("smtp_password")),
                from_address=s.get("smtp_from", ""),
                recipients=[
                    r.strip() for r in s.get("email_recipients", "").split(",") if r.strip()
                ],
            )
        return cls(
            id=a.id,
            status=a.status,  # type: ignore[arg-type]
            team_name=a.team_name,
            admin_login=a.admin_login,
            applicant=ApplicantOut(
                telegram_id=a.applicant_telegram_id,
                username=a.applicant_username,
                name=a.applicant_name,
            ),
            telegram_chat_id=a.telegram_chat_id,
            smtp=smtp,
            created_at=to_local(a.created_at),
            decided_at=to_local(a.decided_at) if a.decided_at else None,
            decided_by=a.decided_by_login,
            reject_reason=a.reject_reason,
            team_id=a.team_id,
        )


class ApplicationPage(BaseModel):
    items: list[ApplicationOut]
    total: int
    limit: int
    offset: int


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _v_reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Укажите причину отказа")
        return v


class DecisionOut(BaseModel):
    application: ApplicationOut
    notified: bool = Field(description="The applicant got the message from the application bot")
    temp_password: str | None = Field(
        None, description="Only when the bot could not deliver it: pass it on yourself"
    )
