"""Dev webhook receiver: logs incoming events and checks the HMAC signature."""

import hashlib
import hmac
import logging

from fastapi import FastAPI, Request

from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging(get_settings().log_level)
logger = logging.getLogger("webhook-sink")
app = FastAPI(title="webhook-sink", docs_url=None, redoc_url=None, openapi_url=None)


@app.post("/{path:path}")
async def receive(path: str, request: Request) -> dict[str, bool]:
    body = await request.body()
    secret = get_settings().webhook_secret.get_secret_value().encode()
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    signature = request.headers.get("X-InvoiceKeeper-Signature", "")
    valid = hmac.compare_digest(expected, signature)
    logger.info(
        "event_id=%s path=/%s signature_valid=%s body=%s",
        request.headers.get("X-InvoiceKeeper-Event-Id"),
        path,
        valid,
        body.decode("utf-8", "replace"),
    )
    return {"ok": valid}
