import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User, UserRole
from app.core.db import get_db
from app.core.deps import check_habitation_access, get_current_user, require_role
from app.daily_logs import service
from app.daily_logs.schemas import BulkImportResult, DailyLogIn, DailyLogOut, DailyLogPage
from app.habitation.models import AccessLevel

router = APIRouter(tags=["daily-logs"])


@router.post("/api/v1/habitations/{habitation_id}/daily-logs")
async def upsert_daily_log(
    habitation_id: uuid.UUID,
    payload: DailyLogIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.EDITOR)
    log, created = await service.upsert_daily_log(db, habitation_id, payload, current_user)
    await write_audit_log(
        db,
        request.state.request_id,
        current_user.id,
        "CREATE" if created else "UPDATE",
        "daily_waste_log",
        str(log.id),
    )
    await db.commit()
    data = DailyLogOut.model_validate(log).model_dump(mode="json")
    return {"success": True, "data": {**data, "created": created}}


@router.post("/api/v1/habitations/{habitation_id}/daily-logs/bulk-csv")
async def bulk_import_daily_logs(
    habitation_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.EDITOR)
    data = await file.read()
    result: BulkImportResult = await service.bulk_import_csv(db, habitation_id, data, current_user)
    await write_audit_log(
        db,
        request.state.request_id,
        current_user.id,
        "BULK_IMPORT",
        "daily_waste_log",
        str(habitation_id),
        {"created": result.created_count, "updated": result.updated_count, "errors": result.error_count},
    )
    await db.commit()
    return {"success": True, "data": result.model_dump()}


@router.get("/api/v1/habitations/{habitation_id}/daily-logs")
async def list_daily_logs(
    habitation_id: uuid.UUID,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.VIEWER)
    items, total = await service.list_daily_logs(db, habitation_id, from_date, to_date, page, page_size)
    page_out = DailyLogPage(
        items=[DailyLogOut.model_validate(i) for i in items], total=total, page=page, page_size=page_size
    )
    return {"success": True, "data": page_out.model_dump(mode="json")}


@router.get("/api/v1/habitations/{habitation_id}/daily-logs/export")
async def export_daily_logs(
    habitation_id: uuid.UUID,
    request: Request,
    period_type: Literal["monthly", "yearly", "custom"] = Query(...),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None, ge=1, le=12),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    export_format: Literal["csv", "xlsx"] = Query(default="csv", alias="format"),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    file_bytes, media_type, filename, content_disposition = await service.export_daily_logs(
        db, habitation_id, period_type, year, month, start_date, end_date, export_format
    )
    await write_audit_log(
        db,
        request.state.request_id,
        current_user.id,
        "EXPORT",
        "daily_waste_log",
        str(habitation_id),
        {"period_type": period_type, "year": year, "month": month, "format": export_format},
    )
    await db.commit()
    return StreamingResponse(
        iter([file_bytes]),
        media_type=media_type,
        headers={"Content-Disposition": content_disposition},
    )
