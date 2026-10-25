"""Payment schedules (DOMAIN §5). Pure functions.

- monthly: due(n) = date(year, month of first due + n, min(anchor_day, days_in_month)),
  the day returns to the anchor: 31.01 → 28.02 (29.02) → 31.03 → 30.04;
- daily / weekly / every_n_days: due(n) = first due + n × 1 / 7 / interval_days days;
- once: a single period, due(0).
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

PERIODICITIES = ("once", "daily", "weekly", "monthly", "every_n_days")
_STEP_DAYS = {"daily": 1, "weekly": 7}


def add_months(base: date, months: int, anchor_day: int | None = None) -> date:
    day = anchor_day if anchor_day is not None else base.day
    month_index = base.year * 12 + (base.month - 1) + months
    year, month = divmod(month_index, 12)
    month += 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Schedule:
    first_due: date
    anchor_day: int
    periodicity: str = "monthly"
    interval_days: int | None = None

    @property
    def step_days(self) -> int | None:
        """Fixed step in days, None for monthly and once."""
        if self.periodicity == "every_n_days":
            return self.interval_days
        return _STEP_DAYS.get(self.periodicity)

    @property
    def max_periods(self) -> int | None:
        return 1 if self.periodicity == "once" else None

    def has(self, n: int) -> bool:
        return self.max_periods is None or n < self.max_periods

    def due(self, n: int) -> date:
        """Due date of period n (0-based) of this schedule."""
        if n < 0:
            raise ValueError("period index must be >= 0")
        if not self.has(n):
            raise ValueError("a one-time payment has a single period")
        step = self.step_days
        if step is not None:
            return self.first_due + timedelta(days=step * n)
        return add_months(self.first_due, n, self.anchor_day)

    def horizon(self, today: date, future: int = 2) -> range:
        """Periods to exist: all with due ≤ today plus `future` more with due > today."""
        n = 0
        while self.has(n) and self.due(n) <= today:
            n += 1
        end = n + future
        if self.max_periods is not None:
            end = min(end, self.max_periods)
        return range(0, end)

    def reminder_lead(self, days_before: int) -> int:
        """Days before the due date to remind: never earlier than the previous due date.

        daily → 0 (the due day), every 2 days → 1, weekly and rarer → days_before (3).
        """
        step = self.step_days
        if step is None:
            return days_before
        return max(0, min(days_before, step - 1))


def schedule_of(recurring: object) -> Schedule:
    """Schedule of a RecurringPayment row (duck-typed to keep this module pure)."""
    return Schedule(
        first_due=recurring.first_due_date,  # type: ignore[attr-defined]
        anchor_day=recurring.anchor_day,  # type: ignore[attr-defined]
        periodicity=recurring.periodicity,  # type: ignore[attr-defined]
        interval_days=recurring.interval_days,  # type: ignore[attr-defined]
    )


def due_date(first_due: date, anchor_day: int, n: int) -> date:
    """Due date of period n (0-based) for a monthly payment."""
    return Schedule(first_due, anchor_day).due(n)


def horizon_indices(first_due: date, anchor_day: int, today: date, future: int = 2) -> range:
    """Monthly horizon: all due ≤ today plus `future` more with due > today."""
    return Schedule(first_due, anchor_day).horizon(today, future)
