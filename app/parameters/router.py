import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.db import get_db
from app.core.deps import check_habitation_access, get_current_user
from app.habitation.models import AccessLevel
from app.parameters import service
from app.parameters.schemas import (
    ParameterSetCreate,
    ParameterSetDetailOut,
    ParameterSetOut,
    WasteBaselineIn,
)

router = APIRouter(prefix="/api/v1", tags=["parameters"])


@router.post("/habitations/{habitation_id}/parameter-sets", status_code=201)
async def create_parameter_set(
    habitation_id: uuid.UUID,
    payload: ParameterSetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.EDITOR)
    ps = await service.create_parameter_set(db, habitation_id, payload, current_user)
    await db.commit()
    return {"success": True, "data": ParameterSetOut.model_validate(ps)}


@router.put("/parameter-sets/{psid}/categories/{category}")
async def upsert_category(
    psid: uuid.UUID,
    category: str,
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ps = await service.get_parameter_set_or_404(db, psid)
    await check_habitation_access(db, current_user, ps.habitation_id, AccessLevel.EDITOR)
    row = await service.upsert_category(db, psid, category, payload)
    await db.commit()
    data = {c: getattr(row, c) for c in row.__table__.columns.keys() if c != "parameter_set_id"}
    return {"success": True, "data": data}


@router.put("/parameter-sets/{psid}/waste-baseline")
async def upsert_waste_baseline(
    psid: uuid.UUID,
    payload: WasteBaselineIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ps = await service.get_parameter_set_or_404(db, psid)
    await check_habitation_access(db, current_user, ps.habitation_id, AccessLevel.EDITOR)
    row = await service.upsert_waste_baseline(db, psid, payload.model_dump(exclude_unset=True))
    await db.commit()
    return {
        "success": True,
        "data": {
            "per_capita_generation_kg_day": row.per_capita_generation_kg_day,
            "total_generation_tpd": row.total_generation_tpd,
            "composition": row.composition,
        },
    }


@router.get("/parameter-sets/{psid}")
async def get_parameter_set(
    psid: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ps = await service.get_parameter_set_or_404(db, psid)
    await check_habitation_access(db, current_user, ps.habitation_id, AccessLevel.VIEWER)
    full = await service.get_parameter_set_full(db, psid)
    out = ParameterSetDetailOut.model_validate(
        full["parameter_set"], from_attributes=True
    )
    out.categories = full["categories"]
    out.waste_baseline = full["waste_baseline"]
@router.get("/habitations/{habitation_id}/parameter-sets")
async def list_parameter_sets_endpoint(
    habitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.VIEWER)
    p_sets = await service.list_parameter_sets(db, habitation_id)
    return {"success": True, "data": [ParameterSetOut.model_validate(ps) for ps in p_sets]}


@router.get("/parameter-sets/{psid}/categories/{category}")
async def get_category_endpoint(
    psid: uuid.UUID,
    category: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ps = await service.get_parameter_set_or_404(db, psid)
    await check_habitation_access(db, current_user, ps.habitation_id, AccessLevel.VIEWER)
    data = await service.get_category_data(db, psid, category)
    return {"success": True, "data": data}


@router.get("/parameter-sets/{psid}/waste-baseline")
async def get_waste_baseline_endpoint(
    psid: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ps = await service.get_parameter_set_or_404(db, psid)
    await check_habitation_access(db, current_user, ps.habitation_id, AccessLevel.VIEWER)
    data = await service.get_waste_baseline_data(db, psid)
    return {"success": True, "data": data}


@router.delete("/parameter-sets/{psid}")
async def delete_parameter_set_endpoint(
    psid: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_parameter_set(db, psid, current_user)
    await db.commit()
    return {"success": True, "data": {"status": "deleted"}}


@router.get("/habitations/{habitation_id}/parameters/history")
async def get_parameter_history_endpoint(
    habitation_id: uuid.UUID,
    param: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.VIEWER)
    history = await service.get_parameter_history(db, habitation_id, param)
    return {"success": True, "data": history}

