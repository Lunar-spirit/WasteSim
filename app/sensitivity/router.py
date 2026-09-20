import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User, UserRole
from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.sensitivity import service
from app.sensitivity.schemas import SensitivityAnalysisOut, SensitivityPointOut, SensitivitySweepIn
from app.workers.tasks_sensitivity import sweep

router = APIRouter(tags=["sensitivity"])


async def _get_analysis_with_access(db: AsyncSession, analysis_id: uuid.UUID, user: User):
    analysis = await service.get_analysis_or_404(db, analysis_id)
    habitation = await get_habitation_or_404(db, analysis.habitation_id)
    await ensure_read_access(db, user, habitation)
    return analysis


@router.post("/api/v1/habitations/{habitation_id}/sensitivity", status_code=202)
async def create_sensitivity_sweep(
    habitation_id: uuid.UUID,
    payload: SensitivitySweepIn,
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.PLANNER, UserRole.RESEARCHER)),
    db: AsyncSession = Depends(get_db),
):
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, current_user, habitation)

    analysis = await service.create_sweep(db, habitation_id, payload, current_user)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "CREATE", "sensitivity_analysis", str(analysis.id)
    )
    await db.commit()

    task = sweep.delay(str(analysis.id))
    out = SensitivityAnalysisOut.model_validate(analysis)
    return {
        "success": True,
        "data": {
            **out.model_dump(mode="json"),
            "job_id": task.id,
            "poll_url": f"/api/v1/sensitivity/{analysis.id}",
        },
    }


@router.get("/api/v1/sensitivity/{analysis_id}")
async def get_sensitivity_analysis(
    analysis_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    analysis = await _get_analysis_with_access(db, analysis_id, current_user)
    points = await service.get_points(db, analysis_id)
    return {
        "success": True,
        "data": {
            **SensitivityAnalysisOut.model_validate(analysis).model_dump(mode="json"),
            "points": [SensitivityPointOut.model_validate(p).model_dump(mode="json") for p in points],
        },
    }


@router.get("/api/v1/sensitivity/{analysis_id}/tornado")
async def get_sensitivity_tornado(
    analysis_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    analysis = await _get_analysis_with_access(db, analysis_id, current_user)
    tornado = await service.get_tornado(db, analysis)
    return {"success": True, "data": tornado}


@router.get("/api/v1/habitations/{habitation_id}/sensitivity")
async def list_sensitivity_analyses(
    habitation_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, current_user, habitation)
    analyses = await service.list_analyses(db, habitation_id)
    return {"success": True, "data": [SensitivityAnalysisOut.model_validate(a).model_dump(mode="json") for a in analyses]}
