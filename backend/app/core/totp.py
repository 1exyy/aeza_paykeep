"""TOTP for administrator password changes (RFC 6238, SHA-1, 30-second steps)."""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.errors import AppError

STEP = 30


def _cipher() -> Fernet:
    key = get_settings().totp_encryption_key.get_secret_value()
    if not key:
        raise AppError(503, "totp_not_configured", "Ключ двухфакторной защиты не настроен")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise AppError(
            503, "totp_not_configured", "Некорректный ключ двухфакторной защиты"
        ) from exc


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def encrypt(secret: str) -> str:
    return _cipher().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt(value: str) -> str:
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise AppError(
            503, "totp_unavailable", "Не удалось прочитать ключ двухфакторной защиты"
        ) from exc


def provisioning_uri(secret: str, team: str, login: str) -> str:
    issuer = "Aeza PayKeep"
    label = f"{team}:{login}"
    return (
        "otpauth://totp/"
        + quote(f"{issuer}:{label}", safe="")
        + "?"
        + urlencode(
            {"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": 6, "period": STEP}
        )
    )


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def matching_counter(secret: str, code: str, now: datetime, after: int | None = None) -> int | None:
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    current = int(now.timestamp()) // STEP
    for counter in (current, current - 1, current + 1):
        if (
            counter >= 0
            and (after is None or counter > after)
            and hmac.compare_digest(_code(secret, counter), code)
        ):
            return counter
    return None
