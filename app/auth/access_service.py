import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.access_schemas import UserAccessOut
from app.auth.models import User, UserRole
from app.core.errors import AppError
from app.habitation.models import AccessLevel, HabitationMember
from app.habitation.service import get_habitation_or_404


async def _get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AppError("USER_NOT_FOUND", "User not found", 404)
    return user


async def assign_planner(
    db: AsyncSession, admin: User, habitation_id: uuid.UUID, user_id: uuid.UUID
) -> HabitationMember:
    """Grants EDITOR access on habitation_id to user_id — the same
    habitation_members row every write-access check in the app already
    consults, so this is the one place that actually turns a PLANNER's
    access on, not a separate table nothing else looks at."""
    await get_habitation_or_404(db, habitation_id)
    target = await _get_user_or_404(db, user_id)
    if target.role != UserRole.PLANNER:
        raise AppError(
            "USER_NOT_PLANNER", "Only a PLANNER can be assigned write access to a habitation", 422
        )

    existing = await db.scalar(
        select(HabitationMember).where(
            HabitationMember.habitation_id == habitation_id,
            HabitationMember.user_id == user_id,
        )
    )
    if existing is not None:
        existing.access_level = AccessLevel.EDITOR
        existing.assigned_by = admin.id
        await db.flush()
        return existing

    member = HabitationMember(
        habitation_id=habitation_id,
        user_id=user_id,
        access_level=AccessLevel.EDITOR,
        assigned_by=admin.id,
    )
    db.add(member)
    await db.flush()
    return member


async def unassign_planner(db: AsyncSession, habitation_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await get_habitation_or_404(db, habitation_id)
    member = await db.scalar(
        select(HabitationMember).where(
            HabitationMember.habitation_id == habitation_id,
            HabitationMember.user_id == user_id,
        )
    )
    if member is None:
        raise AppError("ASSIGNMENT_NOT_FOUND", "This user has no access assigned on this habitation", 404)
    if member.access_level == AccessLevel.OWNER:
        raise AppError(
            "CANNOT_UNASSIGN_OWNER",
            "The habitation's owner cannot be unassigned this way",
            422,
        )
    await db.delete(member)
    await db.flush()


async def list_users_with_access(db: AsyncSession) -> list[UserAccessOut]:
    users = list(await db.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.email)))
    memberships = await db.scalars(select(HabitationMember))
    by_user: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for m in memberships:
        by_user[m.user_id].append(m.habitation_id)

    return [
        UserAccessOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            is_active=u.is_active,
            habitation_ids=by_user.get(u.id, []),
        )
        for u in users
    ]


async def change_user_role(db: AsyncSession, user_id: uuid.UUID, new_role: UserRole) -> User:
    user = await _get_user_or_404(db, user_id)
    user.role = new_role
    await db.flush()
    return user
