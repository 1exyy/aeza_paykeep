from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user', 'supervisor')", name="role"),
        # The supervisor is the only account outside the teams, one per service
        CheckConstraint("(role = 'supervisor') = (team_id IS NULL)", name="supervisor_no_team"),
        Index(
            "uq_users_single_supervisor",
            "role",
            unique=True,
            postgresql_where=text("role = 'supervisor'"),
        ),
        # Logins and Telegram accounts are unique within a team
        Index(
            "uq_users_login_active",
            "team_id",
            func.lower(text("login")),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_users_telegram_active",
            "team_id",
            "telegram_user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND telegram_user_id IS NOT NULL"),
        ),
        Index(
            "uq_users_single_protected",
            "team_id",
            unique=True,
            postgresql_where=text("is_protected"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL only for the supervisor, who never reaches team code: current_user refuses them, so
    # everywhere else it is typed as a plain int
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    login: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # .env accounts (team admin, supervisor): hash of the .env password last applied. The
    # .env password wins only when it changes, so a password changed in the app survives
    # a restart.
    env_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_protected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # a temporary password (new team administrator): only /auth/me, /auth/password, logout
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_dm_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def telegram_linked(self) -> bool:
        return self.telegram_user_id is not None


class UserSession(Base):
    """Server-side login session. Only the SHA-256 of the token is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginAttempt(Base):
    """Failed login attempts for the rate limit (kept in the DB to survive restarts)."""

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_login_at", "team", "login", "attempted_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    team: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    login: Mapped[str] = mapped_column(String(64), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
