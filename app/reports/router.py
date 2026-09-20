import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User
from app.comparison.service import get_comparison_or_404
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import AppError
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.reports import service
from app.reports.schemas import ReportCreateIn, ReportOut
from app.simulation.service import get_run_or_404
from app.workers.tasks_reports import generate

router = APIRouter(tags=["reports"])


@router.post("/api/v1/reports", status_code=202)
async def create_report(
    payload: ReportCreateIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if (payload.run_id is None) == (payload.comparison_id is None):
        raise AppError("REPORT_SUBJECT_REQUIRED", "Exactly one of run_id or comparison_id must be set", 400)

    if payload.run_id is not None:
        run = await get_run_or_404(db, payload.run_id)
        habitation = await get_habitation_or_404(db, run.habitation_id)
    else:
        comparison = await get_comparison_or_404(db, payload.comparison_id)
        habitation = await get_habitation_or_404(db, comparison.habitation_id)
    await ensure_read_access(db, current_user, habitation)

    report = await service.create_report(db, payload, current_user)
    await write_audit_log(db, request.state.request_id, current_user.id, "CREATE", "report", str(report.id))
    await db.commit()

    task = generate.delay(str(report.id))
    out = ReportOut.model_validate(report)
    return {
        "success": True,
        "data": {**out.model_dump(mode="json"), "job_id": task.id, "poll_url": f"/api/v1/reports/{report.id}"},
    }


async def _get_report_with_access(db: AsyncSession, report_id: uuid.UUID, user: User):
    report = await service.get_report_or_404(db, report_id)
    habitation = await get_habitation_or_404(db, report.habitation_id)
    await ensure_read_access(db, user, habitation)
    return report


@router.get("/api/v1/reports/{report_id}")
async def get_report(
    report_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    report = await _get_report_with_access(db, report_id, current_user)
    return {"success": True, "data": ReportOut.model_validate(report).model_dump(mode="json")}


@router.get("/api/v1/reports/{report_id}/download")
async def download_report(
    report_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    report = await _get_report_with_access(db, report_id, current_user)
    url = service.get_download_url(report)
    return {"success": True, "data": {"url": url, "expires_at": report.expires_at.isoformat() if report.expires_at else None}}
