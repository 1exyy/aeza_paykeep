from decimal import Decimal

import pytest

from app.core.errors import AppError
from app.core.money import format_money, parse_money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1500", "1500.00"), ("1500.5", "1500.50"), ("1500.50", "1500.50"), ("0.01", "0.01")],
)
def test_parse_and_format(raw: str, expected: str) -> None:
    assert format_money(parse_money(raw)) == expected


@pytest.mark.parametrize(
    "raw", ["0", "0.00", "-1", "1.234", "1,5", "abc", "", "1e3", "9999999999999", 1500, 15.5]
)
def test_invalid_amounts(raw: object) -> None:
    with pytest.raises(AppError) as exc:
        parse_money(raw)
    assert exc.value.code == "validation_error"
    assert exc.value.details and exc.value.details[0]["field"] == "amount"


def test_max_amount() -> None:
    assert format_money(parse_money("999999999999.99")) == "999999999999.99"


def test_format_none_and_decimal() -> None:
    assert format_money(None) == "0.00"
    assert format_money(Decimal("10")) == "10.00"
