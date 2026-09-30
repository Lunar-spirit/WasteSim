import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import decode_token
from app.habitation.models import AccessLevel, HabitationMember

# Login is a plain JSON endpoint (not OAuth2 form-based), so a simple bearer
# scheme is used instead of OAuth2PasswordBearer: Swagger's "Authorize"
# button just takes a pasted access token, no client_id/username dance.
bearer_scheme = HTTPBearer(auto_error=False)

_ACCESS_RANK = {AccessLevel.VIEWER: 0, AccessLevel.EDITOR: 1, AccessLevel.OWNER: 2}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise AppError("UNAUTHENTICATED", "Missing bearer token", 401)
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise AppError("UNAUTHENTICATED", "Invalid or expired token", 401) from exc
    if payload.get("type") != "access":
        raise AppError("UNAUTHENTICATED", "Not an access token", 401)

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or user.deleted_at is not None or not user.is_active:
        raise AppError("UNAUTHENTICATED", "User not found or disabled", 401)
    return user


def require_role(*roles: UserRole):
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise AppError(
                "FORBIDDEN_ROLE",
                f"Requires one of roles: {', '.join(r.value for r in roles)}",
                403,
            )
        return current_user

    return dependency


# RESEARCHER and POLICY_VIEWER (the design's "VIEWER" role — see
# app/auth/models.py) are read-only across *every* habitation regardless of
# status or membership, per the access-control invariants. Gated strictly to
# read-style checks (min_level == VIEWER) in check_habitation_access below,
# so this can never let either role satisfy an EDITOR/OWNER (write) check.
_READ_ANYTHING_ROLES = {UserRole.RESEARCHER, UserRole.POLICY_VIEWER}


async def check_habitation_access(
    db: AsyncSession, user: User, habitation_id: uuid.UUID, min_level: AccessLevel
) -> None:
    """ADMIN bypasses membership entirely. RESEARCHER/VIEWER bypass only a
    read check (min_level VIEWER) the same way. Everyone else needs a
    habitation_members row at >= min_level for this habitation."""
    if user.role == UserRole.ADMIN:
        return
    if min_level == AccessLevel.VIEWER and user.role in _READ_ANYTHING_ROLES:
        return

    member = await db.scalar(
        select(HabitationMember).where(
            HabitationMember.habitation_id == habitation_id,
            HabitationMember.user_id == user.id,
        )
    )
    if member is None or _ACCESS_RANK[member.access_level] < _ACCESS_RANK[min_level]:
        raise AppError(
            "FORBIDDEN_RESOURCE",
            f"Requires {min_level.value} access on this habitation",
            403,
        )


def require_habitation_access(min_level: AccessLevel):
    """Dependency for routes keyed directly by the {habitation_id} path param."""

    async def dependency(
        habitation_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await check_habitation_access(db, current_user, habitation_id, min_level)
        return current_user

    return dependency


async def check_editable_by_owner_or_role(
    db: AsyncSession, user: User, habitation_id: uuid.UUID, resource_owner_id: uuid.UUID
) -> None:
    """For a resource that tracks who created it (a parameter_set's
    created_by): a RESEARCHER may write to one they personally created —
    their "private draft" for cloning/what-if exploration, per the
    access-control invariants — even with no EDITOR habitation access.
    Anyone else (and a RESEARCHER touching someone else's resource) still
    needs the normal EDITOR check, so this can never be used to reach
    another user's draft or the habitation's official state."""
    if user.role == UserRole.RESEARCHER and user.id == resource_owner_id:
        return
    await check_habitation_access(db, user, habitation_id, AccessLevel.EDITOR)


def verify_habitation_access(required_mode: str = "read"):
    """Named per the access-control spec: `required_mode` is "read" or
    "write". A thin wrapper over check_habitation_access mapping those onto
    the existing VIEWER/EDITOR access levels — "write" also rejects any
    non-PLANNER/ADMIN role outright, so a RESEARCHER can never pass a write
    check even though they're never given an EDITOR row in the first place.
    Every /api/v1/habitations/{habitation_id}/* route already enforces the
    equivalent rule via require_habitation_access(...); this is the same
    single check_habitation_access() choke point, offered under the
    requested name for new routes to depend on directly.
    """
    if required_mode not in ("read", "write"):
        raise ValueError(f"required_mode must be 'read' or 'write', got {required_mode!r}")

    async def dependency(
        habitation_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if required_mode == "write" and current_user.role not in (UserRole.ADMIN, UserRole.PLANNER):
            raise AppError(
                "FORBIDDEN_ROLE", "Only an assigned PLANNER (or ADMIN) can modify this habitation", 403
            )
        min_level = AccessLevel.EDITOR if required_mode == "write" else AccessLevel.VIEWER
        await check_habitation_access(db, current_user, habitation_id, min_level)
        return current_user

    return dependency
