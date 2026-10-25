from datetime import date

import pytest

from app.services.schedule import add_months, due_date, horizon_indices


def test_end_of_month_returns_to_anchor() -> None:
    first = date(2027, 1, 31)
    assert [due_date(first, 31, n) for n in range(5)] == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
        date(2027, 4, 30),
        date(2027, 5, 31),
    ]


def test_leap_year_february() -> None:
    first = date(2028, 1, 31)
    assert due_date(first, 31, 1) == date(2028, 2, 29)
    assert due_date(first, 31, 2) == date(2028, 3, 31)


def test_thirtieth() -> None:
    first = date(2027, 1, 30)
    assert [due_date(first, 30, n) for n in range(3)] == [
        date(2027, 1, 30),
        date(2027, 2, 28),
        date(2027, 3, 30),
    ]


def test_29_february_anchor_in_leap_year() -> None:
    first = date(2028, 2, 29)
    assert due_date(first, 29, 1) == date(2028, 3, 29)
    assert due_date(first, 29, 12) == date(2029, 2, 28)
    assert due_date(first, 29, 48) == date(2032, 2, 29)


def test_year_rollover() -> None:
    first = date(2026, 11, 15)
    assert [due_date(first, 15, n) for n in range(4)] == [
        date(2026, 11, 15),
        date(2026, 12, 15),
        date(2027, 1, 15),
        date(2027, 2, 15),
    ]
    assert add_months(date(2026, 1, 10), -2) == date(2025, 11, 10)


def test_negative_index_rejected() -> None:
    with pytest.raises(ValueError):
        due_date(date(2026, 1, 1), 1, -1)


def test_horizon_two_future_periods() -> None:
    first = date(2026, 10, 24)
    # due today counts as "≤ today", then two more in the future
    assert list(horizon_indices(first, 24, date(2026, 10, 24))) == [0, 1, 2]
    assert list(horizon_indices(first, 24, date(2026, 10, 23))) == [0, 1]
    assert list(horizon_indices(first, 24, date(2027, 1, 2))) == [0, 1, 2, 3, 4]
