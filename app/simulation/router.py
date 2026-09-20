import csv
import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User, UserRole
from app.core.db import get_db
from app.core.deps import check_habitation_access, get_current_user, require_role
from app.habitation.models import AccessLevel
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.simulation import service
from app.simulation.models import RunType
from app.simulation.schemas import RunFindingOut, SimulationCreateIn, SimulationRunOut
from app.workers.tasks_simulate import simulate

router = APIRouter(tags=["simulation"])


@router.post("/api/v1/habitations/{habitation_id}/simulations", status_code=202)
async def create_simulation(
    habitation_id: uuid.UUID,
    payload: SimulationCreateIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # BR-19 checks READY + VALIDATED, not membership — ADMIN, PLANNER or
    # RESEARCHER with at least VIEWER access may all run a simulation
    # (design API-51), so this checks read access, not EDITOR.
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, current_user, habitation)

    run, reused = await service.create_run(db, habitation_id, payload, current_user)
    if reused:
        await db.commit()
        out = SimulationRunOut.model_validate(run)
        return {
            "success": True,
            "data": {**out.model_dump(mode="json"), "poll_url": f"/api/v1/simulations/{run.id}", "reused": True},
        }

    await write_audit_log(
        db, request.state.request_id, current_user.id, "CREATE", "simulation_run", str(run.id)
    )
    await db.commit()

    task = simulate.delay(str(run.id))
    run.job_id = task.id
    await db.commit()

    out = SimulationRunOut.model_validate(run)
    return {
        "success": True,
        "data": {**out.model_dump(mode="json"), "poll_url": f"/api/v1/simulations/{run.id}", "reused": False},
    }


@router.get("/api/v1/habitations/{habitation_id}/simulations")
async def list_simulations(
    habitation_id: uuid.UUID,
    run_type: RunType | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, current_user, habitation)
    runs = await service.list_runs(db, habitation_id, run_type)
    return {"success": True, "data": [SimulationRunOut.model_validate(r).model_dump(mode="json") for r in runs]}


async def _get_run_with_access(db: AsyncSession, run_id: uuid.UUID, user: User):
    run = await service.get_run_or_404(db, run_id)
    habitation = await get_habitation_or_404(db, run.habitation_id)
    await ensure_read_access(db, user, habitation)
    return run


@router.get("/api/v1/simulations/{run_id}")
async def get_simulation(
    run_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    run = await _get_run_with_access(db, run_id, current_user)
    return {"success": True, "data": SimulationRunOut.model_validate(run).model_dump(mode="json")}


@router.post("/api/v1/simulations/{run_id}/cancel")
async def cancel_simulation(
    run_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    run = await service.get_run_or_404(db, run_id)
    await check_habitation_access(db, current_user, run.habitation_id, AccessLevel.EDITOR)
    run = await service.cancel_run(db, run)
    await db.commit()
    return {"success": True, "data": {"id": str(run.id), "status": run.status.value}}


@router.get("/api/v1/simulations/{run_id}/results")
async def get_simulation_results(
    run_id: uuid.UUID,
    aggregate: str = Query(default="yearly", pattern="^(yearly|monthly)$"),
    from_year: int | None = Query(default=None),
    to_year: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_run_with_access(db, run_id, current_user)
    rows: list[Any]
    if aggregate == "yearly":
        rows = await service.get_yearly_results(db, run_id, from_year, to_year)
    else:
        rows = await service.get_monthly_results(db, run_id, from_year, to_year)
    return {
        "success": True,
        "data": {"aggregate": aggregate, "series": [_row_to_dict(r) for r in rows]},
    }


@router.get("/api/v1/simulations/{run_id}/findings")
async def get_simulation_findings(
    run_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _get_run_with_access(db, run_id, current_user)
    findings = await service.get_findings(db, run_id)
    return {"success": True, "data": [RunFindingOut.model_validate(f).model_dump(mode="json") for f in findings]}


@router.get("/api/v1/simulations/{run_id}/export.csv")
async def export_simulation_csv(
    run_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _get_run_with_access(db, run_id, current_user)
    rows = await service.get_yearly_results(db, run_id)
    buffer = io.StringIO()
    if rows:
        fieldnames = list(_row_to_dict(rows[0]).keys())
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_row_to_dict(row))
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=run-{run_id}-yearly.csv"},
    )


@router.delete("/api/v1/simulations/{run_id}")
async def delete_simulation(
    run_id: uuid.UUID,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    run = await service.get_run_or_404(db, run_id)
    await service.delete_run(db, run)
    await db.commit()
    return {"success": True, "data": {"id": str(run_id), "deleted": True}}


def _row_to_dict(row) -> dict:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in ("id", "run_id")
    }
