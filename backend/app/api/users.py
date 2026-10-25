"""GET/POST /users, PATCH/DELETE /users/{id} — administrator only."""

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, clock_dep, require_admin
from app.api.pagination import Page, page_params
from app.core.clock import Clock
from app.core.db import get_session
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserPage, UserPatch
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])


async def _commit(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:  # concurrent creation of the same login
        await db.rollback()
        raise users_service.login_taken() from exc


@router.get("", response_model=UserPage)
async def list_users(
    page: Page = Depends(page_params),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> UserPage:
    where = (
        User.team_id == admin.team_id,
        User.deleted_at.is_(None),
        User.is_protected.is_(False),
    )
    total = await db.scalar(select(func.count()).select_from(User).where(*where)) or 0
    rows = await db.scalars(
        select(User).where(*where).order_by(User.id).limit(page.limit).offset(page.offset)
    )
    return UserPage(
        items=[UserOut.of(u) for u in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> UserOut:
    user = await users_service.create_user(db, clock, admin, body, client_ip(request))
    await _commit(db)
    return UserOut.of(user)


@router.patch("/{id}", response_model=UserOut)
async def update_user(
    body: UserPatch,
    request: Request,
    id: int = Path(ge=1),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> UserOut:
    user = await users_service.update_user(db, clock, admin, id, body, client_ip(request))
    await _commit(db)
    return UserOut.of(user)


@router.delete("/{id}", status_code=204)
async def delete_user(
    request: Request,
    id: int = Path(ge=1),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    clock: Clock = Depends(clock_dep),
) -> Response:
    await users_service.delete_user(db, clock, admin, id, client_ip(request))
    await db.commit()
    return Response(status_code=204)
