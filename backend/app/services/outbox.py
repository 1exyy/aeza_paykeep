"""Outbox: notifications × channels → deliveries, at-most-once sending (DOMAIN §6).

- a delivery is claimed with SELECT … FOR UPDATE SKIP LOCKED and committed as `sending`
  BEFORE the network call, so two dispatchers never send the same delivery;
- explicit channel error → retry with backoff (≤ 5 attempts, 429 waits `retry_after`);
- no answer → `unknown`, never retried; a dispatcher that died in `sending` for > 5 min → `unknown`.

Delivery mechanics (next attempt, stale check) use real time; `sent_at` is business time.
"""

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import ChannelRegistry, SendResult
from app.core.clock import Clock, get_clock, real_now
from app.core.config import use_settings
from app.models.notification import Delivery, Notification
from app.models.payment import PaymentOccurrence, RecurringPayment
from app.services import audit

logger = logging.getLogger("app.outbox")

MAX_ATTEMPTS = 5
BASE_BACKOFF = timedelta(seconds=30)
STALE_SENDING = timedelta(minutes=5)
CANCELLED = "cancelled"


async def enqueue(
    db: AsyncSession,
    clock: Clock,
    channels: ChannelRegistry,
    *,
    type: str,
    team_id: int,
    payload: dict[str, Any],
    occurrence_id: int | None = None,
    recurring_payment_id: int | None = None,
) -> Notification | None:
    """Create the notification and one pending delivery per channel handling the type.

    For `payment.due_soon` the partial unique index makes this idempotent: a second call for the
    same period returns None and creates nothing.
    """
    targets = [name for name, ch in channels.items() if ch.handles(type)]
    if not targets:
        return None
    now = clock.now()
    stmt = insert(Notification).values(
        type=type,
        team_id=team_id,
        payload=payload,
        occurrence_id=occurrence_id,
        recurring_payment_id=recurring_payment_id,
        created_at=now,
    )
    if type == "payment.due_soon":
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["occurrence_id", "type"],
            index_where=Notification.type == "payment.due_soon",
        )
    notification_id = await db.scalar(stmt.returning(Notification.id))
    if notification_id is None:
        return None
    real = real_now()
    for channel in targets:
        db.add(
            Delivery(
                notification_id=notification_id,
                channel=channel,
                status="pending",
                attempts=0,
                next_attempt_at=real,
                created_at=now,
                updated_at=now,
            )
        )
    await db.flush()
    return await db.get(Notification, notification_id)


async def cancel_pending(
    db: AsyncSession, *, occurrence_id: int | None = None, recurring_payment_id: int | None = None
) -> int:
    """Cancel not-yet-sent reminders of a paid period or a stopped payment (same transaction)."""
    notifications = select(Notification.id).where(Notification.type == "payment.due_soon")
    if occurrence_id is not None:
        notifications = notifications.where(Notification.occurrence_id == occurrence_id)
    if recurring_payment_id is not None:
        notifications = notifications.where(
            Notification.recurring_payment_id == recurring_payment_id
        )
    result = await db.execute(
        update(Delivery)
        .where(Delivery.status == "pending", Delivery.notification_id.in_(notifications))
        .values(status="failed", last_error=CANCELLED, updated_at=real_now())
        .returning(Delivery.id)
    )
    return len(result.all())


async def mark_stale(db: AsyncSession) -> int:
    """Deliveries stuck in `sending` (the worker died mid-send) become `unknown`."""
    result = await db.execute(
        update(Delivery)
        .where(
            Delivery.status == "sending", Delivery.sending_started_at < real_now() - STALE_SENDING
        )
        .values(status="unknown", last_error="no result: worker stopped while sending")
        .returning(Delivery.id)
    )
    return len(result.all())


async def claim(db: AsyncSession, limit: int = 20) -> list[int]:
    """Take due pending deliveries; other dispatchers skip the locked rows. Commits."""
    now = real_now()
    ids = list(
        await db.scalars(
            select(Delivery.id)
            .where(Delivery.status == "pending", Delivery.next_attempt_at <= now)
            .order_by(Delivery.next_attempt_at, Delivery.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if ids:
        await db.execute(
            update(Delivery)
            .where(Delivery.id.in_(ids))
            .values(status="sending", attempts=Delivery.attempts + 1, sending_started_at=now)
        )
    await db.commit()
    return ids


async def _still_wanted(db: AsyncSession, notification: Notification) -> bool:
    if notification.type != "payment.due_soon":
        return True
    if notification.occurrence_id is None:
        return False
    row = (
        await db.execute(
            select(PaymentOccurrence.status, RecurringPayment.status)
            .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
            .where(PaymentOccurrence.id == notification.occurrence_id)
        )
    ).first()
    return row is not None and row[0] == "unpaid" and row[1] == "active"


def _backoff(attempts: int, result: SendResult) -> timedelta:
    if result.retry_after:
        return timedelta(seconds=result.retry_after)
    return BASE_BACKOFF * (2 ** max(0, attempts - 1))


async def deliver(
    db: AsyncSession, delivery_id: int, channels: ChannelRegistry | None = None
) -> str:
    """Send one claimed delivery and record the outcome. Commits. Returns the final status.

    Without `channels` the delivery goes out with its team's channels and settings.
    """
    from app.channels import get_channels
    from app.services.notification_settings import team_settings

    delivery = await db.get(Delivery, delivery_id)
    if delivery is None or delivery.status != "sending":
        return "skipped"
    notification = await db.get(Notification, delivery.notification_id)
    assert notification is not None
    settings, _row = await team_settings(db, notification.team_id)
    with use_settings(settings):
        return await _deliver(db, delivery, notification, channels or get_channels())


async def _deliver(
    db: AsyncSession, delivery: Delivery, notification: Notification, channels: ChannelRegistry
) -> str:
    clock = await get_clock(db)
    channel = channels.get(delivery.channel)

    if channel is None:
        delivery.status, delivery.last_error = "failed", "channel is disabled"
    elif not await _still_wanted(db, notification):
        delivery.status, delivery.last_error = "failed", CANCELLED
    else:
        try:
            result = await channel.send(notification, delivery)
        except Exception as exc:  # a bug in a channel must not leave the row in `sending`
            logger.exception("Channel %s crashed", delivery.channel)
            result = SendResult.unknown(f"channel crashed: {type(exc).__name__}")
        _apply(db, clock, notification, delivery, result)
        if result.outcome == "sent" and delivery.channel == "telegram":
            await _mark_reminded(db, notification, clock)
    delivery.updated_at = clock.now()
    await db.commit()
    return delivery.status


def _apply(
    db: AsyncSession,
    clock: Clock,
    notification: Notification,
    delivery: Delivery,
    result: SendResult,
) -> None:
    delivery.last_error = result.error
    final_failure = False
    if result.outcome == "sent":
        delivery.status, delivery.sent_at = "sent", clock.now()
        delivery.external_id = result.external_id
    elif result.outcome == "failed" and delivery.attempts < MAX_ATTEMPTS:
        delivery.status = "pending"
        delivery.next_attempt_at = real_now() + _backoff(delivery.attempts, result)
    else:
        delivery.status = "failed" if result.outcome == "failed" else "unknown"
        final_failure = True
    if result.outcome == "sent" or final_failure:
        audit.record(
            db,
            clock,
            "notification.sent" if result.outcome == "sent" else "notification.failed",
            actor=None,
            team_id=notification.team_id,
            source="system",
            object_type="notification",
            object_id=notification.id,
            result="success" if result.outcome == "sent" else "failure",
            details={
                "channel": delivery.channel,
                "delivery_id": delivery.id,
                "occurrence_id": notification.occurrence_id,
                "status": delivery.status,
                "attempts": delivery.attempts,
                "error": result.error,
            },
        )


async def _mark_reminded(db: AsyncSession, notification: Notification, clock: Clock) -> None:
    if notification.type == "payment.due_soon" and notification.occurrence_id:
        await db.execute(
            update(PaymentOccurrence)
            .where(
                PaymentOccurrence.id == notification.occurrence_id,
                PaymentOccurrence.reminder_sent_at.is_(None),
            )
            .values(reminder_sent_at=clock.now())
        )


async def dispatch(
    db: AsyncSession, channels: ChannelRegistry | None = None, limit: int = 20
) -> int:
    """One dispatcher pass: stale → unknown, claim, send. Returns the number of claimed rows."""
    await mark_stale(db)
    ids = await claim(db, limit)
    for delivery_id in ids:
        await deliver(db, delivery_id, channels)
    return len(ids)
