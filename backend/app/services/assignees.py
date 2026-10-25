"""Responsible users of a recurring payment.

- `assign_all` — every active user with role `user`, including users added later;
- otherwise the explicitly chosen users (`recurring_payment_assignees`), deleted users drop out;
- no assignees at all — the old behaviour: anyone linked may press «Оплачено».
"""

from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.payment import RecurringPayment, RecurringPaymentAssignee
from app.models.user import User


@dataclass
class Assignment:
    assign_all: bool = False
    users: list[User] = field(default_factory=list)  # explicit choice, active users only

    @property
    def logins(self) -> list[str]:
        return [u.login for u in self.users]

    @property
    def has_assignees(self) -> bool:
        return self.assign_all or bool(self.users)


async def validate_ids(db: AsyncSession, team_id: int, ids: list[int]) -> list[User]:
    """Active users with role `user` of the team (the GET /users list); unknown ids → 422."""
    unique = list(dict.fromkeys(ids))
    if not unique:
        return []
    found = {
        u.id: u
        for u in await db.scalars(
            select(User).where(
                User.id.in_(unique),
                User.team_id == team_id,
                User.deleted_at.is_(None),
                User.role == "user",
            )
        )
    }
    missing = [str(i) for i in unique if i not in found]
    if missing:
        raise AppError.validation("assignee_ids", f"Пользователи не найдены: {', '.join(missing)}")
    return [found[i] for i in unique]


def check_choice(assignee_ids: list[int], assign_all: bool) -> None:
    if assign_all and assignee_ids:
        raise AppError.validation("assign_all", "Выберите либо всех, либо конкретных ответственных")


async def replace(
    db: AsyncSession, recurring: RecurringPayment, users: list[User], assign_all: bool
) -> None:
    recurring.assign_all = assign_all
    await db.execute(
        delete(RecurringPaymentAssignee).where(
            RecurringPaymentAssignee.recurring_payment_id == recurring.id
        )
    )
    for user in [] if assign_all else users:
        db.add(RecurringPaymentAssignee(recurring_payment_id=recurring.id, user_id=user.id))
    await db.flush()


async def assignments(db: AsyncSession, recurring_ids: list[int]) -> dict[int, Assignment]:
    """Assignment per payment for API responses (one query for the explicit users)."""
    if not recurring_ids:
        return {}
    result = {
        rp_id: Assignment(assign_all=bool(flag))
        for rp_id, flag in (
            await db.execute(
                select(RecurringPayment.id, RecurringPayment.assign_all).where(
                    RecurringPayment.id.in_(recurring_ids)
                )
            )
        ).all()
    }
    rows = await db.execute(
        select(RecurringPaymentAssignee.recurring_payment_id, User)
        .join(User, User.id == RecurringPaymentAssignee.user_id)
        .where(
            RecurringPaymentAssignee.recurring_payment_id.in_(recurring_ids),
            User.deleted_at.is_(None),
        )
        .order_by(User.login)
    )
    for rp_id, user in rows.all():
        result[rp_id].users.append(user)
    return result


async def assignment(db: AsyncSession, recurring_id: int) -> Assignment:
    return (await assignments(db, [recurring_id])).get(recurring_id, Assignment())


async def responsible_users(db: AsyncSession, recurring_id: int) -> tuple[bool, list[User]]:
    """(has_assignees, users who are responsible right now)."""
    current = await assignment(db, recurring_id)
    if current.assign_all:
        team_id = select(RecurringPayment.team_id).where(RecurringPayment.id == recurring_id)
        users = list(
            await db.scalars(
                select(User)
                .where(
                    User.team_id == team_id.scalar_subquery(),
                    User.deleted_at.is_(None),
                    User.role == "user",
                )
                .order_by(User.login)
            )
        )
        return True, users
    return bool(current.users), current.users


async def forget_user(db: AsyncSession, user_id: int) -> None:
    """A deleted user stops being responsible for anything."""
    await db.execute(
        delete(RecurringPaymentAssignee).where(RecurringPaymentAssignee.user_id == user_id)
    )
