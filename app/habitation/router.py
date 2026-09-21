import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User, UserRole
from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.habitation import service
from app.habitation.schemas import HabitationCreate, HabitationDetailOut, HabitationOut
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


@router.get("/nearby")
async def get_nearby_habitations(
    lat: float,
    lon: float,
    radius_km: float = 10.0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    habitations = await service.find_nearby_habitations(db, lat, lon, radius_km, current_user)
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


@router.patch("/{habitation_id}")
async def update_habitation_endpoint(
    habitation_id: uuid.UUID,
    payload: HabitationUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    habitation = await service.update_habitation(db, habitation_id, payload, current_user)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "UPDATE", "habitation", str(habitation_id)
    )
    await db.commit()
    return {"success": True, "data": HabitationOut.model_validate(habitation)}


@router.delete("/{habitation_id}")
async def delete_habitation_endpoint(
    habitation_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_habitation(db, habitation_id, current_user)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "DELETE", "habitation", str(habitation_id)
    )
    await db.commit()
    return {"success": True, "data": {"status": "deleted"}}


@router.post("/{habitation_id}/members")
async def add_member_endpoint(
    habitation_id: uuid.UUID,
    payload: MemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    member = await service.add_member(db, habitation_id, payload.user_id, payload.access_level, current_user)
    await db.commit()
    return {
        "success": True,
        "data": {
            "habitation_id": member.habitation_id,
            "user_id": member.user_id,
            "access_level": member.access_level.value,
        },
    }


@router.delete("/{habitation_id}/members/{user_id}")
async def remove_member_endpoint(
    habitation_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.remove_member(db, habitation_id, user_id, current_user)
    await db.commit()
    return {"success": True, "data": {"status": "member_removed"}}


@router.get("/{habitation_id}/summary")
async def get_habitation_summary_endpoint(
    habitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    summary = await service.get_habitation_summary(db, habitation_id, current_user)
    return {"success": True, "data": summary}

