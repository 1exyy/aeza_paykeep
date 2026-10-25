"""Attachments of a period: list, add (multipart file or JSON link), download, delete."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api.deps import client_ip, clock_dep, current_user
from app.core.clock import Clock, to_local
from app.core.db import get_session
from app.core.errors import AppError, not_found, validation_details
from app.models.attachment import Attachment
from app.models.payment import PaymentOccurrence
from app.models.user import User
from app.schemas.user import UserRef
from app.services import attachments as service

router = APIRouter(tags=["attachments"])

API_PREFIX = "/api/v1"
_MULTIPART_OVERHEAD = 64 * 1024


class LinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    title: str | None = None


class AttachmentOut(BaseModel):
    id: int
    occurrence_id: int
    kind: Literal["file", "link"]
    url: str | None
    title: str | None
    file_name: str | None
    content_type: Literal["image/jpeg", "image/png", "application/pdf"] | None
    size_bytes: int | None
    created_at: datetime
    created_by: UserRef

    @classmethod
    def of(cls, a: Attachment) -> "AttachmentOut":
        return cls(
            id=a.id,
            occurrence_id=a.occurrence_id,
            kind=a.kind,  # type: ignore[arg-type]
            url=a.url if a.kind == "link" else f"{API_PREFIX}/attachments/{a.id}/file",
            title=a.title,
            file_name=a.file_name,
            content_type=a.content_type,  # type: ignore[arg-type]
            size_bytes=a.size_bytes,
            created_at=to_local(a.created_at),
            created_by=UserRef(id=a.created_by_id or 0, login=a.created_by_login),
        )


@router.get("/payment-occurrences/{id}/attachments", response_model=list[AttachmentOut])
async def list_attachments(
    id: int = Path(ge=1),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> list[AttachmentOut]:
    occ = await db.get(PaymentOccurrence, id)
    if occ is None or occ.team_id != user.team_id:
        raise not_found("Платёж не найден")
    rows = await db.scalars(
        select(Attachment).where(Attachment.occurrence_id == id).order_by(Attachment.id)
    )
    return [AttachmentOut.of(a) for a in rows]


async def _read_upload(request: Request) -> tuple[bytes, str | None]:
    declared = request.headers.get("content-length")
    if (
        declared
        and declared.isdigit()
        and int(declared) > service.MAX_FILE_BYTES + _MULTIPART_OVERHEAD
    ):
        raise service.too_large()
    form = await request.form(max_files=1, max_fields=5)
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise AppError.validation("file", "Приложите файл в поле file")
    content = await upload.read(service.MAX_FILE_BYTES + 1)
    await upload.close()
    return content, upload.filename


@router.post("/payment-occurrences/{id}/attachments", response_model=AttachmentOut, status_code=201)
async def add_attachment(
    request: Request,
    id: int = Path(ge=1),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> AttachmentOut:
    content_type = request.headers.get("content-type", "").lower()
    ip = client_ip(request)
    if content_type.startswith("multipart/form-data"):
        content, file_name = await _read_upload(request)
        item = await service.add_file(db, clock, user, id, content, file_name, ip)
        try:
            await db.commit()
        except BaseException:
            await service.discard_file(item.storage_name)
            raise
        return AttachmentOut.of(item)
    if content_type.startswith("application/json"):
        try:
            body = LinkCreate.model_validate_json(await request.body())
        except ValidationError as exc:
            details = validation_details([dict(e) for e in exc.errors()])
            code = (
                "field_not_allowed"
                if any(e["type"] == "extra_forbidden" for e in exc.errors())
                else "validation_error"
            )
            raise AppError(422, code, "Проверьте введённые данные", details) from exc
        item = await service.add_link(db, clock, user, id, body.url, body.title, ip)
        await db.commit()
        return AttachmentOut.of(item)
    raise AppError.validation("body", "Передайте файл (multipart/form-data) или ссылку (JSON)")


@router.get("/attachments/{id}/file")
async def download_file(
    id: int = Path(ge=1),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> FileResponse:
    item = await service.find(db, user.team_id, id)
    if item is None or item.kind != "file" or not item.storage_name:
        raise not_found("Файл не найден")
    path = service.storage_path(item.storage_name)
    if not path.is_file():
        raise not_found("Файл не найден")
    return FileResponse(
        path,
        media_type=item.content_type,
        filename=item.file_name,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.delete("/attachments/{id}", status_code=204)
async def delete_attachment(
    request: Request,
    id: int = Path(ge=1),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> Response:
    storage_name = await service.delete(db, clock, user, id, client_ip(request))
    await db.commit()
    await service.discard_file(storage_name)
    return Response(status_code=204)
