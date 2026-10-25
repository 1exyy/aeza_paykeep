from datetime import date

from pydantic import BaseModel, Field

from app.core.money import format_money
from app.services.summary import CurrencyTotals


class CurrencyTotalsOut(BaseModel):
    currency: str
    total: str
    paid: str
    unpaid: str
    overdue: str
    count: int

    @classmethod
    def of(cls, t: CurrencyTotals) -> "CurrencyTotalsOut":
        return cls(
            currency=t.currency,
            total=format_money(t.total),
            paid=format_money(t.paid),
            unpaid=format_money(t.unpaid),
            overdue=format_money(t.overdue),
            count=t.count,
        )


class SummaryOut(BaseModel):
    from_: date = Field(serialization_alias="from")
    to: date
    today: date
    currencies: list[CurrencyTotalsOut]


class ChannelsOut(BaseModel):
    telegram: bool
    email: bool
    webhook: bool
    extra: bool


class TeamRef(BaseModel):
    id: int
    name: str


class AppConfigOut(BaseModel):
    team: TeamRef
    timezone_offset: str
    timezone_label: str
    today: date
    reminder_days_before: int
    currencies: list[str]
    periodicities: list[str]
    telegram_bot_username: str | None
    miniapp_url: str | None
    channels: ChannelsOut
    dev_mode: bool
