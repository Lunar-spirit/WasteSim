import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit_log
from app.auth.models import User
from app.core.db import get_db
from app.core.deps import check_habitation_access, get_current_user
from app.gis.models import LayerType
from app.habitation.models import AccessLevel
from app.ingestion import service
from app.ingestion.models import UploadTarget
from app.ingestion.schemas import UploadCreateOut, UploadStatusOut
from app.validation.schemas import ValidationIssueOut
from app.workers.tasks_gis import ingest_gis_layer
from app.workers.tasks_ingest import ingest_tabular_upload

router = APIRouter(prefix="/api/v1", tags=["ingestion"])

_TASK_BY_TARGET = {
    UploadTarget.PARAMETERS: ingest_tabular_upload,
    UploadTarget.GIS_LAYER: ingest_gis_layer,
}


@router.post("/habitations/{habitation_id}/uploads", status_code=202)
async def upload_dataset(
    habitation_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    target: UploadTarget = Form(...),
    parameter_set_id: uuid.UUID | None = Form(default=None),
    layer_name: str | None = Form(default=None),
    layer_type: LayerType | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.EDITOR)
    data = await file.read()

    upload, duplicate_of = await service.create_upload(
        db,
        habitation_id,
        filename=file.filename or "upload",
        data=data,
        target=target,
        parameter_set_id=parameter_set_id,
        layer_name=layer_name,
        layer_type=layer_type,
        user=current_user,
    )

    if duplicate_of is not None:
        # BR-11: identical file within 24h -> 200 (not the route's default
        # 202), no second job. JSONResponse needed here specifically because
        # the route decorator's status_code otherwise applies to every
        # return value.
        await db.commit()
        out = UploadCreateOut(
            upload_id=upload.id,
            status=upload.status.value,
            job_id=upload.job_id,
            file_format=upload.file_format.value,
            size_bytes=upload.size_bytes,
            poll_url=f"/api/v1/uploads/{upload.id}",
            duplicate_of=duplicate_of,
        )
        return JSONResponse(status_code=200, content={"success": True, "data": out.model_dump(mode="json")})

    await write_audit_log(
        db, request.state.request_id, current_user.id, "CREATE", "dataset_upload", str(upload.id)
    )
    await db.commit()

    task = _TASK_BY_TARGET[target].delay(str(upload.id))
    upload.job_id = task.id
    await db.commit()

    out = UploadCreateOut(
        upload_id=upload.id,
        status=upload.status.value,
        job_id=upload.job_id,
        file_format=upload.file_format.value,
        size_bytes=upload.size_bytes,
        poll_url=f"/api/v1/uploads/{upload.id}",
        duplicate_of=None,
    )
    return {"success": True, "data": out.model_dump()}


@router.get("/uploads/{upload_id}")
async def get_upload_status(
    upload_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    upload = await service.get_upload_or_404(db, upload_id)
    if upload.habitation_id is not None:
        await check_habitation_access(db, current_user, upload.habitation_id, AccessLevel.VIEWER)
    out = UploadStatusOut.model_validate(upload)
    return {"success": True, "data": out.model_dump()}


@router.get("/uploads/{upload_id}/issues")
async def get_upload_issues(
    upload_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    upload = await service.get_upload_or_404(db, upload_id)
    if upload.habitation_id is not None:
        await check_habitation_access(db, current_user, upload.habitation_id, AccessLevel.VIEWER)
    issues = await service.list_upload_issues(db, upload_id)
    return {
        "success": True,
        "data": [ValidationIssueOut.model_validate(i).model_dump() for i in issues],
    }


@router.post("/uploads/{upload_id}/ingest")
async def ingest_upload(
    upload_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    upload = await service.get_upload_or_404(db, upload_id)
    if upload.habitation_id is not None:
        await check_habitation_access(db, current_user, upload.habitation_id, AccessLevel.EDITOR)
    ps = await service.ingest_accepted_rows(db, upload)
    await write_audit_log(
        db, request.state.request_id, current_user.id, "INGEST", "dataset_upload", str(upload.id)
    )
    await db.commit()
    return {"success": True, "data": {"parameter_set_id": str(ps.id), "status": upload.status.value}}


@router.post("/uploads/{upload_id}/retry")
async def retry_upload(
    upload_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    upload = await service.get_upload_or_404(db, upload_id)
    if upload.habitation_id is not None:
        await check_habitation_access(db, current_user, upload.habitation_id, AccessLevel.EDITOR)
    upload = await service.retry_upload(db, upload)
    await db.commit()

    task = _TASK_BY_TARGET[upload.target].delay(str(upload.id))
    upload.job_id = task.id
    await db.commit()

    return {"success": True, "data": {"upload_id": str(upload.id), "status": upload.status.value, "job_id": task.id}}
