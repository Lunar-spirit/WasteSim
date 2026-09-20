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
    return {"success": True, "data": out}
