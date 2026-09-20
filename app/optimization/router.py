import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User
from app.core.db import get_db
from app.core.deps import check_habitation_access, get_current_user
from app.habitation.models import AccessLevel
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.optimization import service
from app.optimization.schemas import OptimizationCandidateOut, OptimizationCreateIn, OptimizationRunOut, PromoteIn
from app.simulation.schemas import SimulationRunOut
from app.workers.tasks_optimize import optimize
from app.workers.tasks_simulate import simulate

router = APIRouter(tags=["optimization"])


async def _get_optimization_with_access(db: AsyncSession, optimization_id: uuid.UUID, user: User):
    run = await service.get_optimization_or_404(db, optimization_id)
    habitation = await get_habitation_or_404(db, run.habitation_id)
    await ensure_read_access(db, user, habitation)
    return run


@router.post("/api/v1/habitations/{habitation_id}/optimizations", status_code=202)
async def create_optimization(
    habitation_id: uuid.UUID,
    payload: OptimizationCreateIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # API-67: "ADMIN, or PLANNER with OWNER/EDITOR" — same EDITOR-level
    # membership check used for every other write against a habitation's
    # runs (e.g. simulation/router.py's cancel_simulation).
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.EDITOR)

    run, notes = await service.create_optimization(db, habitation_id, payload, current_user)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "CREATE", "optimization_run", str(run.id)
    )
    await db.commit()

    task = optimize.delay(str(run.id))
    out = OptimizationRunOut.model_validate(run)
    return {
        "success": True,
        "data": {
            "optimization_id": str(run.id),
            "status": out.status.value,
            "job_id": task.id,
            "decision_space": out.decision_space,
            "notes": notes,
            "poll_url": f"/api/v1/optimizations/{run.id}",
        },
    }


@router.get("/api/v1/optimizations/{optimization_id}")
async def get_optimization(
    optimization_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    run = await _get_optimization_with_access(db, optimization_id, current_user)
    return {"success": True, "data": OptimizationRunOut.model_validate(run).model_dump(mode="json")}


@router.get("/api/v1/optimizations/{optimization_id}/candidates")
async def list_optimization_candidates(
    optimization_id: uuid.UUID,
    feasible: bool | None = Query(default=None),
    sort: str | None = Query(default=None, pattern="^(score)?$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_optimization_with_access(db, optimization_id, current_user)
    candidates = await service.list_candidates(
        db, optimization_id, feasible_only=bool(feasible), sort_by_score=(sort == "score")
    )
    return {
        "success": True,
        "data": [OptimizationCandidateOut.model_validate(c).model_dump(mode="json") for c in candidates],
    }


@router.get("/api/v1/optimizations/{optimization_id}/pareto")
async def get_pareto_front(
    optimization_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _get_optimization_with_access(db, optimization_id, current_user)
    front = await service.get_pareto_front(db, optimization_id)
    return {"success": True, "data": [OptimizationCandidateOut.model_validate(c).model_dump(mode="json") for c in front]}


@router.post("/api/v1/optimizations/{optimization_id}/promote", status_code=202)
async def promote_optimization_candidate(
    optimization_id: uuid.UUID,
    payload: PromoteIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await service.get_optimization_or_404(db, optimization_id)
    await check_habitation_access(db, current_user, run.habitation_id, AccessLevel.EDITOR)

    new_run = await service.promote_candidate(db, run, payload.candidate_id, current_user)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "CREATE", "simulation_run", str(new_run.id)
    )
    await db.commit()

    task = simulate.delay(str(new_run.id))
    new_run.job_id = task.id
    await db.commit()

    out = SimulationRunOut.model_validate(new_run)
    return {
        "success": True,
        "data": {**out.model_dump(mode="json"), "poll_url": f"/api/v1/simulations/{new_run.id}"},
    }


@router.get("/api/v1/optimizations/{optimization_id}/explanation")
async def get_optimization_explanation(
    optimization_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    run = await _get_optimization_with_access(db, optimization_id, current_user)
    explanation = await service.build_explanation(db, run)
    return {"success": True, "data": explanation}
