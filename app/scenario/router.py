import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User
from app.core.db import get_db
from app.core.deps import get_current_user
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.scenario import service
from app.scenario.schemas import ImpactPreviewIn, ScenarioCreateIn, ScenarioEventOut
from app.simulation.schemas import SimulationRunOut
from app.simulation.service import get_run_or_404
from app.workers.tasks_simulate import simulate

router = APIRouter(tags=["scenario"])


@router.get("/api/v1/event-types")
async def get_event_catalogue(current_user: User = Depends(get_current_user)):
    return {"success": True, "data": service.list_event_catalogue()}


async def _get_run_with_access(db: AsyncSession, run_id: uuid.UUID, user: User):
    run = await get_run_or_404(db, run_id)
    habitation = await get_habitation_or_404(db, run.habitation_id)
    await ensure_read_access(db, user, habitation)
    return run


@router.post("/api/v1/simulations/{run_id}/scenarios", status_code=202)
async def create_scenario(
    run_id: uuid.UUID,
    payload: ScenarioCreateIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_run_with_access(db, run_id, current_user)
    scenario_run = await service.create_scenario_run(db, run_id, payload, current_user)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "CREATE", "simulation_run", str(scenario_run.id)
    )
    await db.commit()

    task = simulate.delay(str(scenario_run.id))
    scenario_run.job_id = task.id
    await db.commit()

    out = SimulationRunOut.model_validate(scenario_run)
    return {
        "success": True,
        "data": {**out.model_dump(mode="json"), "poll_url": f"/api/v1/simulations/{scenario_run.id}"},
    }


@router.get("/api/v1/simulations/{run_id}/events")
async def list_events(
    run_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _get_run_with_access(db, run_id, current_user)
    events = await service.get_events_for_run(db, run_id)
    return {"success": True, "data": [ScenarioEventOut.model_validate(e).model_dump(mode="json") for e in events]}


@router.post("/api/v1/simulations/{run_id}/events/preview")
async def preview_event_impact(
    run_id: uuid.UUID,
    payload: ImpactPreviewIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _get_run_with_access(db, run_id, current_user)
    result = await service.preview_impact(db, run.habitation_id, payload.event_type, payload.affected_area)
    return {"success": True, "data": result}
