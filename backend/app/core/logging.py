"""Logging setup. Request bodies and auth headers are never logged."""

import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"(ik_session=)[^;\s]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-.]+", re.IGNORECASE),
    re.compile(r"(bot)\d+:[A-Za-z0-9_-]+"),
    re.compile(r"((?:password|token|secret|init_data)\"?\s*[:=]\s*\"?)[^\"&\s,}]+", re.IGNORECASE),
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    redacting = RedactingFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(redacting)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "aiogram", "httpx"):
        logging.getLogger(name).addFilter(redacting)
