"""ORM models. Import every model here so Alembic sees the full metadata."""

from app.models.app_settings import AppSettings
from app.models.application import TeamApplication
from app.models.application_draft import ApplicationDraft
from app.models.attachment import Attachment
from app.models.audit_event import AuditEvent
from app.models.base import Base
from app.models.notification import Delivery, Notification, PersonalReminder
from app.models.payment import PaymentOccurrence, RecurringPayment, RecurringPaymentAssignee
from app.models.system_state import SystemState
from app.models.team import Team
from app.models.user import LoginAttempt, User, UserSession

__all__ = [
    "AppSettings",
    "ApplicationDraft",
    "Attachment",
    "AuditEvent",
    "Base",
    "Delivery",
    "LoginAttempt",
    "Notification",
    "PaymentOccurrence",
    "PersonalReminder",
    "RecurringPayment",
    "RecurringPaymentAssignee",
    "SystemState",
    "Team",
    "TeamApplication",
    "User",
    "UserSession",
]
