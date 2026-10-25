"""Receipts (files) and links attached to a period (DOMAIN §10). Callers commit.

- file: JPEG / PNG / PDF detected by the first bytes, ≤ 10 MB; stored as ATTACHMENTS_DIR/<uuid>;
- link: http/https only, ≤ 2048 chars, optional title ≤ 100;
- ≤ 5 attachments per period (the period row is locked while counting);
- view and add — both roles; delete — the author or admin.
"""

import logging
import re
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import get_settings
from app.core.errors import AppError, forbidden, not_found
from app.models.attachment import Attachment
from app.models.payment import PaymentOccurrence
from app.models.user import User
from app.services import audit

logger = logging.getLogger("app.attachments")

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PER_OCCURRENCE = 5
MAX_URL = 2048
MAX_TITLE = 100

_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF-", "application/pdf"),
]
_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}


def too_large() -> AppError:
    return AppError(413, "payload_too_large", "Файл больше 10 МБ")


def sniff_content_type(head: bytes) -> str | None:
    for signature, content_type in _SIGNATURES:
        if head.startswith(signature):
            return content_type
    return None


def safe_file_name(name: str | None, content_type: str) -> str:
    """Original name for download: no path, no control characters, ≤ 255 chars."""
    base = Path((name or "").replace("\\", "/")).name
    base = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip(" .")
    base = re.sub(r"\s+", " ", base)[:200]
    return base or f"receipt{_EXTENSIONS[content_type]}"


def storage_path(storage_name: str) -> Path:
    return Path(get_settings().attachments_dir) / storage_name


def validate_link(url: str, title: str | None) -> tuple[str, str | None]:
    url = url.strip()
    if len(url) > MAX_URL:
        raise AppError.validation("url", "Ссылка длиннее 2048 символов")
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise AppError.validation("url", "Допустимы только ссылки http:// и https://")
    clean_title = title.strip() if title else None
    if clean_title and len(clean_title) > MAX_TITLE:
        raise AppError.validation("title", "Подпись: не больше 100 символов")
    return url, clean_title or None


async def _lock_occurrence(db: AsyncSession, team_id: int, occurrence_id: int) -> PaymentOccurrence:
    occ = await db.scalar(
        select(PaymentOccurrence)
        .where(PaymentOccurrence.id == occurrence_id, PaymentOccurrence.team_id == team_id)
        .with_for_update()
    )
    if occ is None:
        raise not_found("Платёж не найден")
    count = await db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.occurrence_id == occ.id)
    )
    if (count or 0) >= MAX_PER_OCCURRENCE:
        raise AppError(409, "attachments_limit", "К платежу можно приложить не больше 5 вложений")
    return occ


def _audit_add(
    db: AsyncSession, clock: Clock, actor: User, item: Attachment, ip: str | None
) -> None:
    audit.record(
        db,
        clock,
        "attachment.add",
        actor=actor,
        object_type="attachment",
        object_id=item.id,
        details={
            "occurrence_id": item.occurrence_id,
            "kind": item.kind,
            "file_name": item.file_name,
            "content_type": item.content_type,
            "size_bytes": item.size_bytes,
            "url": item.url,
        },
        ip=ip,
    )


async def add_link(
    db: AsyncSession,
    clock: Clock,
    actor: User,
    occurrence_id: int,
    url: str,
    title: str | None,
    ip: str | None,
) -> Attachment:
    url, title = validate_link(url, title)
    occ = await _lock_occurrence(db, actor.team_id, occurrence_id)
    item = Attachment(
        occurrence_id=occ.id,
        kind="link",
        url=url,
        title=title,
        created_by_id=actor.id,
        created_by_login=actor.login,
        created_at=clock.now(),
    )
    db.add(item)
    await db.flush()
    _audit_add(db, clock, actor, item, ip)
    return item


async def add_file(
    db: AsyncSession,
    clock: Clock,
    actor: User,
    occurrence_id: int,
    content: bytes,
    original_name: str | None,
    ip: str | None,
) -> Attachment:
    """Validate and write the file. Returns the row; the file is on disk already.

    The caller must call `discard_file` if the transaction is not committed.
    """
    if len(content) > MAX_FILE_BYTES:
        raise too_large()
    if not content:
        raise AppError.validation("file", "Файл пустой")
    content_type = sniff_content_type(content[:8])
    if content_type is None:
        raise AppError.validation("file", "Допустимы только JPEG, PNG или PDF")
    occ = await _lock_occurrence(db, actor.team_id, occurrence_id)

    storage_name = uuid.uuid4().hex
    path = storage_path(storage_name)
    await anyio.Path(path.parent).mkdir(parents=True, exist_ok=True)
    await anyio.Path(path).write_bytes(content)
    item = Attachment(
        occurrence_id=occ.id,
        kind="file",
        title=None,
        file_name=safe_file_name(original_name, content_type),
        content_type=content_type,
        size_bytes=len(content),
        storage_name=storage_name,
        created_by_id=actor.id,
        created_by_login=actor.login,
        created_at=clock.now(),
    )
    db.add(item)
    await db.flush()
    _audit_add(db, clock, actor, item, ip)
    return item


async def discard_file(storage_name: str | None) -> None:
    if storage_name:
        try:
            await anyio.Path(storage_path(storage_name)).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove attachment file %s", storage_name)


async def delete(
    db: AsyncSession, clock: Clock, actor: User, attachment_id: int, ip: str | None
) -> str | None:
    """Delete the row; returns the storage name to unlink AFTER the commit."""
    item = await find(db, actor.team_id, attachment_id)
    if item is None:
        raise not_found("Вложение не найдено")
    if actor.role != "admin" and item.created_by_id != actor.id:
        raise forbidden()
    storage_name = item.storage_name
    audit.record(
        db,
        clock,
        "attachment.delete",
        actor=actor,
        object_type="attachment",
        object_id=item.id,
        details={
            "occurrence_id": item.occurrence_id,
            "kind": item.kind,
            "file_name": item.file_name,
        },
        ip=ip,
    )
    await db.delete(item)
    return storage_name


async def find(db: AsyncSession, team_id: int, attachment_id: int) -> Attachment | None:
    """Attachment of a period of the team."""
    return await db.scalar(
        select(Attachment)
        .join(PaymentOccurrence, PaymentOccurrence.id == Attachment.occurrence_id)
        .where(Attachment.id == attachment_id, PaymentOccurrence.team_id == team_id)
    )


async def counts(db: AsyncSession, occurrence_ids: list[int]) -> dict[int, int]:
    if not occurrence_ids:
        return {}
    rows = await db.execute(
        select(Attachment.occurrence_id, func.count())
        .where(Attachment.occurrence_id.in_(occurrence_ids))
        .group_by(Attachment.occurrence_id)
    )
    return {occ_id: n for occ_id, n in rows.all()}
