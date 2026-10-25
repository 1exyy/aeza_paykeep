"""Passwords (argon2) and session tokens. Secrets never leave this module in logs."""

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
# Used to spend the same time when the login does not exist.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


INIT_DATA_MAX_AGE = timedelta(hours=24)


class InitDataError(ValueError):
    """initData is malformed, forged or too old. The message is safe to log (no data inside)."""


def init_data_hash(data: dict[str, str], bot_token: str) -> str:
    """secret = HMAC_SHA256(key="WebAppData", msg=bot_token); hash = HMAC(secret, check string)."""
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()


def verify_init_data(init_data: str, bot_token: str, now: datetime) -> dict[str, Any]:
    """Validate Telegram.WebApp.initData and return the `user` object (has `id`).

    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not bot_token:
        raise InitDataError("bot token is not configured")
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise InitDataError("not a query string") from exc
    received = data.pop("hash", "")
    if not received or not hmac.compare_digest(init_data_hash(data, bot_token), received):
        raise InitDataError("bad signature")
    try:
        auth_date = datetime.fromtimestamp(int(data["auth_date"]), UTC)
        user = json.loads(data["user"])
        user_id = int(user["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InitDataError("missing auth_date or user") from exc
    if now - auth_date > INIT_DATA_MAX_AGE or auth_date - now > timedelta(minutes=5):
        raise InitDataError("auth_date is too old")
    return {**user, "id": user_id}
