"""Webhook channel: POST JSON to WEBHOOK_URL, signed with WEBHOOK_SECRET.

Body: {"event_id", "type", "occurred_at", "data"}; headers X-InvoiceKeeper-Event-Id and
X-InvoiceKeeper-Signature: sha256=<hex HMAC-SHA256 of the body>. 2xx = delivered; otherwise, and
on network errors, the outbox retries (≤ 5). The receiver deduplicates by event_id, which stays
the same across retries, so here even a timeout is retried.
"""

import hashlib
import hmac
import json
import logging
from urllib.parse import urlsplit

import httpx

from app.channels import SendResult
from app.core.clock import to_local
from app.core.config import get_settings
from app.models.notification import Delivery, Notification

logger = logging.getLogger("app.channels.webhook")

EVENTS = {
    "payment.due_soon",
    "occurrence.paid",
    "occurrence.unpaid",
    "recurring.created",
    "recurring.stopped",
}
TIMEOUT = httpx.Timeout(10.0)


def url_allowed(url: str, dev_mode: bool) -> bool:
    """https only; http is allowed in DEV_MODE (local webhook-sink)."""
    parts = urlsplit(url)
    return bool(parts.netloc) and (parts.scheme == "https" or (dev_mode and parts.scheme == "http"))


def body_of(notification: Notification) -> bytes:
    """Deterministic body: the same bytes (and signature) on every retry."""
    document = {
        "event_id": str(notification.event_id),
        "type": notification.type,
        "occurred_at": to_local(notification.created_at).isoformat(),
        "data": notification.payload,
    }
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookChannel:
    name = "webhook"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # tests inject httpx.MockTransport

    def handles(self, notification_type: str) -> bool:
        return notification_type in EVENTS

    async def send(self, notification: Notification, delivery: Delivery) -> SendResult:
        settings = get_settings()
        body = body_of(notification)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "InvoiceKeeper-Webhook/1",
            "X-InvoiceKeeper-Event-Id": str(notification.event_id),
            "X-InvoiceKeeper-Signature": signature(
                body, settings.webhook_secret.get_secret_value()
            ),
        }
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT) as client:
                response = await client.post(settings.webhook_url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            return SendResult.failed(f"webhook network: {type(exc).__name__}")
        if response.is_success:
            return SendResult.ok(external_id=str(response.status_code))
        retry_after = response.headers.get("retry-after", "")
        return SendResult.failed(
            f"webhook HTTP {response.status_code}",
            retry_after=int(retry_after)
            if response.status_code == 429 and retry_after.isdigit()
            else None,
        )
