"""Email channel (SMTP, aiosmtplib): the same reminder to EMAIL_RECIPIENTS.

Delivered = the SMTP server accepted the message. A refusal or a failed connection (nothing was
sent) is retried; a broken connection or a timeout after connecting is `unknown` (never retried).
"""

from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import aiosmtplib
from aiosmtplib import (
    SMTPConnectError,
    SMTPException,
    SMTPNotSupported,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPServerDisconnected,
    SMTPTimeoutError,
)

from app.channels import SendResult
from app.channels.texts import reminder_text, ru_date
from app.core.config import get_settings
from app.models.notification import Delivery, Notification

SMTP_TIMEOUT = 20


def recipients() -> list[str]:
    return [r.strip() for r in get_settings().email_recipients.split(",") if r.strip()]


def build_message(notification: Notification) -> EmailMessage:
    settings = get_settings()
    payload = notification.payload
    message = EmailMessage()
    sender = settings.smtp_from or settings.smtp_user
    message["From"] = formataddr(("Invoice Keeper", sender))
    message["To"] = ", ".join(recipients())
    message["Subject"] = (
        f"Напоминание об оплате: {payload['title']} — {payload['amount']} {payload['currency']}"
        f" до {ru_date(payload['due_date'])}"
    )
    message["Message-ID"] = make_msgid(idstring=str(notification.event_id), domain="invoice-keeper")
    message.set_content(
        reminder_text(payload) + "\n\nОтметить оплату можно в приложении Invoice Keeper."
    )
    return message


class EmailChannel:
    name = "email"

    def handles(self, notification_type: str) -> bool:
        return notification_type == "payment.due_soon"

    async def send(self, notification: Notification, delivery: Delivery) -> SendResult:
        to = recipients()
        if not to:
            return SendResult.failed("EMAIL_RECIPIENTS is empty")
        return await deliver(build_message(notification), to)


async def deliver(message: EmailMessage, to: list[str]) -> SendResult:
    """Send one message with the current SMTP settings."""
    settings = get_settings()
    try:
        errors, _response = await aiosmtplib.send(
            message,
            sender=settings.smtp_from or settings.smtp_user,
            recipients=to,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password.get_secret_value() or None,
            use_tls=settings.smtp_ssl,
            start_tls=settings.smtp_starttls if not settings.smtp_ssl else False,
            timeout=SMTP_TIMEOUT,
        )
    except SMTPConnectError as exc:  # nothing was sent: safe to retry
        return SendResult.failed(f"SMTP connect: {type(exc).__name__}")
    except SMTPRecipientsRefused:
        return SendResult.failed("SMTP: all recipients refused")
    except SMTPResponseException as exc:
        return SendResult.failed(f"SMTP {exc.code}: {exc.message}"[:500])
    except SMTPNotSupported as exc:
        return SendResult.failed(f"SMTP not supported: {exc}"[:500])
    except (SMTPTimeoutError, SMTPServerDisconnected, TimeoutError) as exc:
        return SendResult.unknown(f"SMTP no result: {type(exc).__name__}")
    except (SMTPException, OSError) as exc:
        return SendResult.unknown(f"SMTP error: {type(exc).__name__}")
    error = f"refused: {', '.join(sorted(errors))}" if errors else None
    result = SendResult.ok(external_id=str(message["Message-ID"])[:64])
    result.error = error
    return result
