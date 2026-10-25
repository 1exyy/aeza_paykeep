"""Aggregates all API routers (mounted under /api/v1 in main.py)."""

from fastapi import APIRouter

from app.api import (
    attachments,
    audit,
    auth,
    calendar,
    dev,
    notifications,
    occurrences,
    recurring,
    settings,
    summary,
    supervisor,
    telegram,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(recurring.router)
api_router.include_router(occurrences.router)
api_router.include_router(attachments.router)
api_router.include_router(summary.router)
api_router.include_router(calendar.router)
api_router.include_router(telegram.router)
api_router.include_router(notifications.router)
api_router.include_router(audit.router)
api_router.include_router(settings.router)
api_router.include_router(supervisor.router)
api_router.include_router(dev.router)
