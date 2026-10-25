"""Audit log writer. The event is added to the caller's transaction (same commit as the change)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.models.audit_event import AuditEvent
from app.models.user import User

_SECRET_KEYS = {"password", "token", "init_data", "initdata", "cookie", "secret", "hash"}


def _clean(details: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in details.items() if k.lower() not in _SECRET_KEYS}


def record(
    db: AsyncSession,
    clock: Clock,
    action: str,
    *,
    actor: User | None,
    source: str = "web",
    object_type: str | None = None,
    object_id: int | None = None,
    result: str = "success",
    details: dict[str, Any] | None = None,
    ip: str | None = None,
    team_id: int | None = None,
) -> AuditEvent:
    """`team_id` defaults to the actor's team."""
    event = AuditEvent(
        at=clock.now(),
        team_id=actor.team_id if actor is not None else team_id,
        actor_id=actor.id if actor else None,
        actor_login=actor.login if actor else None,
        source=source,
        action=action,
        object_type=object_type,
        object_id=object_id,
        result=result,
        details=_clean(details or {}),
        ip=ip,
    )
    db.add(event)
    return event
