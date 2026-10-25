import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.clock import to_local
from app.models.user import User


class UserRef(BaseModel):
    id: int
    login: str


class UserOut(BaseModel):
    id: int
    login: str
    role: str
    is_protected: bool
    must_change_password: bool
    totp_enabled: bool
    telegram_linked: bool
    telegram_dm_enabled: bool
    telegram_dm_days_before: int
    telegram_username: str | None
    telegram_user_id: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            login=user.login,
            role=user.role,
            is_protected=user.is_protected,
            must_change_password=user.must_change_password,
            totp_enabled=user.totp_enabled,
            telegram_linked=user.telegram_linked,
            telegram_dm_enabled=user.telegram_dm_enabled,
            telegram_dm_days_before=user.telegram_dm_days_before,
            telegram_username=user.telegram_username,
            telegram_user_id=user.telegram_user_id,
            created_at=to_local(user.created_at),
            updated_at=to_local(user.updated_at),
        )


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    limit: int
    offset: int


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    team: str = Field(default="", max_length=64)
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str
    totp_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")

    @field_validator("new_password")
    @classmethod
    def _v_new(cls, v: str) -> str:
        return _check_password(v)


class TotpBegin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)


class TotpConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[0-9]{6}$")


class TotpSetup(BaseModel):
    secret: str
    otpauth_uri: str
    expires_at: datetime


class DmNotificationPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_dm_enabled: bool


class DmReminderDays(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_dm_days_before: int = Field(strict=True, ge=0, le=30)


class SessionOut(BaseModel):
    token: str
    expires_at: datetime


class LoginResponse(BaseModel):
    user: UserOut
    session: SessionOut


_LOGIN_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
_LOGIN_MESSAGE = "Логин: 3–32 символа — латинские буквы, цифры, точка, дефис, подчёркивание"


def _normalize_login(value: str) -> str:
    login = value.strip().lower()
    if not _LOGIN_RE.match(login):
        raise ValueError(_LOGIN_MESSAGE)
    return login


_TG_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{4,31}$")
_TG_MESSAGE = "Telegram: @username (5–32 символа: латиница, цифры, _) или числовой ID"


def normalize_telegram(value: str | None) -> str | None:
    """'' → unlink; digits → numeric id; otherwise '@username' in lower case."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return ""
    if text.isdigit():
        if not 0 < int(text) < 2**63:
            raise ValueError(_TG_MESSAGE)
        return str(int(text))
    name = text.removeprefix("@").lower()
    if text.startswith("https://t.me/"):
        name = text.removeprefix("https://t.me/").strip("/").lower()
    if not _TG_USERNAME_RE.match(name):
        raise ValueError(_TG_MESSAGE)
    return "@" + name


def _check_password(value: str) -> str:
    if not 8 <= len(value) <= 128:
        raise ValueError("Пароль: от 8 до 128 символов")
    return value


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str
    password: str
    telegram: str | None = None

    @field_validator("telegram")
    @classmethod
    def _v_telegram(cls, v: str | None) -> str | None:
        return normalize_telegram(v)

    @field_validator("login")
    @classmethod
    def _v_login(cls, v: str) -> str:
        return _normalize_login(v)

    @field_validator("password")
    @classmethod
    def _v_password(cls, v: str) -> str:
        return _check_password(v)


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str | None = None
    password: str | None = None
    telegram: str | None = None
    expected_version: int | None = None

    @field_validator("telegram")
    @classmethod
    def _v_telegram(cls, v: str | None) -> str | None:
        return normalize_telegram(v)

    @field_validator("login")
    @classmethod
    def _v_login(cls, v: str | None) -> str | None:
        return None if v is None else _normalize_login(v)

    @field_validator("password")
    @classmethod
    def _v_password(cls, v: str | None) -> str | None:
        return None if v is None else _check_password(v)
