from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.clock import to_local
from app.models.notification import Delivery, Notification


class DeliveryOut(BaseModel):
    id: int
    notification_type: str
    occurrence_id: int | None
    channel: str
    status: str
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, delivery: Delivery, notification: Notification) -> "DeliveryOut":
        return cls(
            id=delivery.id,
            notification_type=notification.type,
            occurrence_id=notification.occurrence_id,
            channel=delivery.channel,
            status=delivery.status,
            attempts=delivery.attempts,
            last_error=delivery.last_error,
            sent_at=to_local(delivery.sent_at) if delivery.sent_at else None,
            created_at=to_local(delivery.created_at),
        )


class DeliveryPage(BaseModel):
    items: list[DeliveryOut]
    total: int
    limit: int
    offset: int


class DevClockOut(BaseModel):
    today: date
    real_today: date
    offset_days: int


class DevClockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset_days: int = Field(ge=-400, le=400)
