"""Extra channel: Slack-compatible incoming webhook — POST {"text": "..."}.

Works with Slack, Mattermost, Rocket.Chat and Discord (`…/slack` URL). Unlike our signed
webhook, these receivers do not deduplicate, so the Telegram policy applies: no connection →
retry; the request may have reached the receiver (timeout, broken connection) → `unknown`.
"""

import httpx

from app.channels import SendResult
from app.channels.texts import reminder_text
from app.core.config import get_settings
from app.models.notification import Delivery, Notification

TIMEOUT = httpx.Timeout(10.0)


class ExtraChannel:
    name = "extra"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # tests inject httpx.MockTransport

    def handles(self, notification_type: str) -> bool:
        return notification_type == "payment.due_soon"

    async def send(self, notification: Notification, delivery: Delivery) -> SendResult:
        url = get_settings().extra_channel_url
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT) as client:
                response = await client.post(
                    url, json={"text": reminder_text(notification.payload)}
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:  # nothing was sent
            return SendResult.failed(f"extra connect: {type(exc).__name__}")
        except httpx.HTTPError as exc:
            return SendResult.unknown(f"extra no result: {type(exc).__name__}")
        if response.is_success:
            return SendResult.ok(external_id=str(response.status_code))
        retry_after = response.headers.get("retry-after", "")
        return SendResult.failed(
            f"extra HTTP {response.status_code}",
            retry_after=int(retry_after)
            if response.status_code == 429 and retry_after.isdigit()
            else None,
        )
