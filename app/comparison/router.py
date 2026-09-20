import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User
from app.comparison import service
from app.comparison.schemas import ComparisonCreateIn, ComparisonOut
from app.core.db import get_db
from app.core.deps import get_current_user
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.simulation.service import get_run_or_404

router = APIRouter(tags=["comparison"])


@router.post("/api/v1/comparisons", status_code=201)
async def create_comparison(
    payload: ComparisonCreateIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # habitation_id isn't a path param here (API-76 is a bare /comparisons)
    # — it's derived from the first run, then every other run is checked
    # against it inside the service (BR-27).
    first_run = await get_run_or_404(db, payload.run_ids[0])
    habitation = await get_habitation_or_404(db, first_run.habitation_id)
    await ensure_read_access(db, current_user, habitation)

    comparison = await service.create_comparison(db, first_run.habitation_id, payload, current_user)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "CREATE", "run_comparison", str(comparison.id)
    )
    await db.commit()
    return {"success": True, "data": ComparisonOut.model_validate(comparison).model_dump(mode="json")}


async def _get_comparison_with_access(db: AsyncSession, comparison_id: uuid.UUID, user: User):
    comparison = await service.get_comparison_or_404(db, comparison_id)
    habitation = await get_habitation_or_404(db, comparison.habitation_id)
    await ensure_read_access(db, user, habitation)
    return comparison


@router.get("/api/v1/comparisons/{comparison_id}")
async def get_comparison(
    comparison_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    comparison = await _get_comparison_with_access(db, comparison_id, current_user)
    data = await service.get_aligned_series(db, comparison)
    return {"success": True, "data": data}


@router.get("/api/v1/comparisons/{comparison_id}/deltas")
async def get_comparison_deltas(
    comparison_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    comparison = await _get_comparison_with_access(db, comparison_id, current_user)
    data = await service.get_deltas(db, comparison)
    return {"success": True, "data": data}
