from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.clock import to_local
from app.core.errors import AppError
from app.core.money import format_money, parse_money
from app.models.payment import RecurringPayment
from app.schemas.user import UserRef
from app.services.assignees import Assignment

Currency = Literal["RUB", "USD", "EUR"]
Periodicity = Literal["once", "daily", "weekly", "monthly", "every_n_days"]
INTERVAL_MESSAGE = "Укажите интервал от 1 до 365 дней для «каждые N дней»"


def _clean_title(value: str) -> str:
    title = value.strip()
    if not 1 <= len(title) <= 100:
        raise ValueError("Название: от 1 до 100 символов")
    return title


def _money(value: Any) -> Decimal:
    try:
        return parse_money(value)
    except AppError as exc:
        raise ValueError(exc.details[0]["message"] if exc.details else exc.message) from exc


def check_interval(periodicity: str, interval_days: int | None) -> None:
    """interval_days is required for every_n_days and forbidden otherwise."""
    if periodicity == "every_n_days":
        if interval_days is None or not 1 <= interval_days <= 365:
            raise AppError.validation("interval_days", INTERVAL_MESSAGE)
    elif interval_days is not None:
        raise AppError.validation(
            "interval_days", "Интервал задаётся только для периодичности «каждые N дней»"
        )


class RecurringPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    amount: Decimal
    currency: Currency
    next_due_date: date
    periodicity: Periodicity
    interval_days: int | None = None
    assignee_ids: list[int] = Field(default_factory=list)
    assign_all: bool = False

    @field_validator("title")
    @classmethod
    def _v_title(cls, v: str) -> str:
        return _clean_title(v)

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount(cls, v: Any) -> Decimal:
        return _money(v)

    @model_validator(mode="after")
    def _v_interval(self) -> "RecurringPaymentCreate":
        check_interval(self.periodicity, self.interval_days)
        return self


class RecurringPaymentPatch(BaseModel):
    """Only the fields to change; unknown fields → 422 field_not_allowed."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    amount: Decimal | None = None
    currency: Currency | None = None
    next_due_date: date | None = None
    periodicity: Periodicity | None = None
    interval_days: int | None = None
    assignee_ids: list[int] | None = None
    assign_all: bool | None = None
    expected_version: int | None = None

    @field_validator("title")
    @classmethod
    def _v_title(cls, v: str | None) -> str | None:
        return None if v is None else _clean_title(v)

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount(cls, v: Any) -> Decimal | None:
        return None if v is None else _money(v)


class RecurringPaymentOut(BaseModel):
    id: int
    title: str
    amount: str
    currency: str
    periodicity: str
    interval_days: int | None
    anchor_day: int
    first_due_date: date
    next_due_date: date | None
    status: str
    completed: bool
    created_at: datetime
    stopped_at: datetime | None
    created_by: UserRef
    assign_all: bool
    assignees: list[UserRef]
    version: int

    @classmethod
    def of(
        cls, rp: RecurringPayment, next_due: date | None, assignment: Assignment
    ) -> "RecurringPaymentOut":
        return cls(
            id=rp.id,
            title=rp.title,
            amount=format_money(rp.amount),
            currency=rp.currency,
            periodicity=rp.periodicity,
            interval_days=rp.interval_days,
            anchor_day=rp.anchor_day,
            first_due_date=rp.first_due_date,
            next_due_date=next_due if rp.status == "active" else None,
            status=rp.status,
            completed=rp.completed,
            created_at=to_local(rp.created_at),
            stopped_at=to_local(rp.stopped_at) if rp.stopped_at else None,
            created_by=UserRef(id=rp.created_by_id or 0, login=rp.created_by_login),
            assign_all=assignment.assign_all,
            assignees=[UserRef(id=u.id, login=u.login) for u in assignment.users],
            version=rp.version,
        )


class RecurringPaymentPage(BaseModel):
    items: list[RecurringPaymentOut]
    total: int
    limit: int
    offset: int
