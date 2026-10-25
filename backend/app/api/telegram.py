"""POST/DELETE /telegram/link — link the current user's Telegram account (both roles)."""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, clock_dep, current_user
from app.core.clock import Clock
from app.core.db import get_session
from app.models.user import User
from app.schemas.user import UserOut
from app.services import telegram_link

router = APIRouter(prefix="/telegram", tags=["telegram"])


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    init_data: str = Field(min_length=1, max_length=4096)


@router.post("/link", response_model=UserOut)
async def link(
    body: LinkRequest,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> UserOut:
    await telegram_link.link(db, clock, user, body.init_data, client_ip(request))
    try:
        await db.commit()
    except IntegrityError as exc:  # the same Telegram linked concurrently by someone else
        await db.rollback()
        raise telegram_link.already_linked() from exc
    return UserOut.of(user)


@router.delete("/link", status_code=204)
async def unlink(
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> Response:
    await telegram_link.unlink(db, clock, user, client_ip(request))
    await db.commit()
    return Response(status_code=204)
