"""Money: Decimal only, NUMERIC(14,2) in the DB, string "1500.00" in JSON. Never float."""

import re
from decimal import Decimal
from typing import Any

from app.core.errors import AppError

MAX_AMOUNT = Decimal("999999999999.99")
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
_INPUT_RE = re.compile(r"^\d{1,12}(\.\d{1,2})?$")


def parse_money(value: Any, field: str = "amount") -> Decimal:
    """Parse MoneyInput ("1500", "1500.5", "1500.50"); must be > 0 and ≤ 999999999999.99."""
    if not isinstance(value, str):
        raise AppError.validation(field, 'Сумма передаётся строкой, например "1500.00"')
    text = value.strip()
    if not _INPUT_RE.match(text):
        raise AppError.validation(
            field, "Сумма — число с точкой и не больше двух знаков после неё, например 1500.50"
        )
    amount = Decimal(text).quantize(CENT)
    if amount <= 0:
        raise AppError.validation(field, "Сумма должна быть больше нуля")
    if amount > MAX_AMOUNT:
        raise AppError.validation(field, "Сумма слишком большая")
    return amount


def format_money(amount: Decimal | None) -> str:
    return f"{(amount or ZERO).quantize(CENT):f}"
