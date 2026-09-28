import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth import access_service
from app.auth.access_schemas import AssignPlannerIn, RoleChangeIn, UnassignPlannerIn, UserAccessOut
from app.auth.models import User, UserRole
from app.auth.schemas import UserOut
from app.core.db import get_db
from app.core.deps import require_role

router = APIRouter(prefix="/api/v1/admin/access", tags=["admin-access"])


@router.post("/assign", status_code=201)
async def assign(
    payload: AssignPlannerIn,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    member = await access_service.assign_planner(db, current_user, payload.habitation_id, payload.user_id)
    await write_audit_log(
        db,
        request.state.request_id,
        current_user.id,
        "ASSIGN",
        "habitation_member",
        str(member.id),
        {"user_id": str(payload.user_id), "habitation_id": str(payload.habitation_id)},
    )
    await db.commit()
    return {"success": True, "data": {"user_id": payload.user_id, "habitation_id": payload.habitation_id}}


@router.delete("/unassign")
async def unassign(
    payload: UnassignPlannerIn,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await access_service.unassign_planner(db, payload.habitation_id, payload.user_id)
    await write_audit_log(
        db,
        request.state.request_id,
        current_user.id,
        "UNASSIGN",
        "habitation_member",
        str(payload.habitation_id),
        {"user_id": str(payload.user_id)},
    )
    await db.commit()
    return {"success": True, "data": None}


@router.get("/users")
async def list_users(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    users = await access_service.list_users_with_access(db)
    return {"success": True, "data": [UserAccessOut.model_validate(u) for u in users]}


@router.patch("/users/{user_id}/role")
async def change_role(
    user_id: uuid.UUID,
    payload: RoleChangeIn,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    user = await access_service.change_user_role(db, user_id, payload.role)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "ROLE_CHANGE", "user", str(user.id), {"role": payload.role.value}
    )
    await db.commit()
    return {"success": True, "data": UserOut.model_validate(user)}
