import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User, UserRole
from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.habitation import service
from app.habitation.schemas import (
    GrantAccessIn,
    HabitationCreate,
    HabitationDetailOut,
    HabitationMemberAdminOut,
    HabitationMemberOut,
    HabitationOut,
)
from app.parameters.service import get_parameter_set_summary

router = APIRouter(prefix="/api/v1/habitations", tags=["habitations"])


@router.post("", status_code=201)
async def create_habitation(
    payload: HabitationCreate,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.PLANNER)),
    db: AsyncSession = Depends(get_db),
):
    habitation = await service.create_habitation(db, payload, current_user)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "CREATE", "habitation", str(habitation.id)
    )
    await db.commit()
    return {"success": True, "data": HabitationOut.model_validate(habitation)}


@router.get("")
async def list_habitations(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    habitations = await service.list_habitations(db, current_user)
    return {"success": True, "data": [HabitationOut.model_validate(h) for h in habitations]}


@router.get("/{habitation_id}")
async def get_habitation(
    habitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    habitation = await service.get_habitation(db, habitation_id, current_user)
    summary = None
    if habitation.active_parameter_set_id is not None:
        summary = await get_parameter_set_summary(db, habitation.active_parameter_set_id)
    data = HabitationDetailOut.model_validate(habitation)
    data.active_parameter_set_summary = summary
    return {"success": True, "data": data}


# --- Habitation access control (ADMIN only) ---------------------------------
# habitation_members / AccessLevel (VIEWER/EDITOR/OWNER) already drove every
# check_habitation_access() call in the app — there was just no endpoint to
# actually create one of these rows. An ADMIN bypasses check_habitation_access
# entirely (see app/core/deps.py), so these are how an ADMIN grants a
# PLANNER/RESEARCHER/VIEWER user OWNER/EDITOR/VIEWER-level access to a
# specific habitation.


@router.get("/{habitation_id}/members")
async def list_habitation_members(
    habitation_id: uuid.UUID,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await service.get_habitation_or_404(db, habitation_id)
    rows = await service.list_members(db, habitation_id)
    data = [
        HabitationMemberAdminOut(
            **HabitationMemberOut.model_validate(member).model_dump(),
            user_email=user.email,
            user_full_name=user.full_name,
        )
        for member, user in rows
    ]
    return {"success": True, "data": data}


@router.post("/{habitation_id}/members", status_code=201)
async def grant_habitation_access(
    habitation_id: uuid.UUID,
    payload: GrantAccessIn,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await service.get_habitation_or_404(db, habitation_id)
    member = await service.grant_access(db, habitation_id, payload.email, payload.access_level)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "GRANT_ACCESS", "habitation_member", str(member.id)
    )
    await db.commit()
    return {"success": True, "data": HabitationMemberOut.model_validate(member)}


@router.delete("/{habitation_id}/members/{member_id}", status_code=204)
async def revoke_habitation_access(
    habitation_id: uuid.UUID,
    member_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    member = await service.get_member_or_404(db, habitation_id, member_id)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "REVOKE_ACCESS", "habitation_member", str(member.id)
    )
    await service.revoke_access(db, member)
    await db.commit()
    return Response(status_code=204)
