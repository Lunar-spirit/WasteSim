import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.db import get_db
from app.core.deps import check_habitation_access, get_current_user
from app.habitation.models import AccessLevel
from app.parameters.models import ParameterDefinition
from app.parameters.service import get_parameter_set_or_404
from app.parameters.schemas import ParameterDefinitionOut
from app.validation import service
from app.validation.schemas import ValidationReportOut

router = APIRouter(prefix="/api/v1", tags=["validation"])


@router.post("/parameter-sets/{psid}/validate")
async def validate(
    psid: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ps = await get_parameter_set_or_404(db, psid)
    await check_habitation_access(db, current_user, ps.habitation_id, AccessLevel.EDITOR)
    report = await service.validate_parameter_set(db, psid, current_user)
    await db.commit()
    out = ValidationReportOut.model_validate(report, from_attributes=True)
    return {
        "success": True,
        "data": {
            "report_id": str(out.id),
            "scope": out.scope,
            "result": out.result,
            "error_count": out.error_count,
            "warning_count": out.warning_count,
            "completeness_pct": out.completeness_pct,
            "completeness_by_category": out.completeness_by_category,
            "rules_version": out.rules_version,
            "issues": [i.model_dump() for i in out.issues],
        },
    }


@router.post("/parameter-sets/{psid}/commit")
async def commit(
    psid: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ps = await get_parameter_set_or_404(db, psid)
    await check_habitation_access(db, current_user, ps.habitation_id, AccessLevel.OWNER)
    committed = await service.commit_parameter_set(db, psid)
    await db.commit()
    return {
        "success": True,
        "data": {"id": str(committed.id), "version_no": committed.version_no, "status": committed.status.value},
    }


@router.get("/parameter-definitions")
async def list_parameter_definitions(db: AsyncSession = Depends(get_db)):
    definitions = await db.scalars(select(ParameterDefinition).order_by(ParameterDefinition.category))
    return {
        "success": True,
        "data": [ParameterDefinitionOut.model_validate(d) for d in definitions],
    }


@router.get("/validation-reports/{report_id}")
async def get_validation_report_endpoint(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await service.get_validation_report_or_404(db, report_id)
    await check_habitation_access(db, current_user, report.habitation_id, AccessLevel.VIEWER)
    out = ValidationReportOut.model_validate(report, from_attributes=True)
    return {
        "success": True,
        "data": {
            "report_id": str(out.id),
            "habitation_id": str(report.habitation_id),
            "parameter_set_id": str(report.parameter_set_id),
            "scope": out.scope,
            "result": out.result,
            "error_count": out.error_count,
            "warning_count": out.warning_count,
            "completeness_pct": out.completeness_pct,
            "completeness_by_category": out.completeness_by_category,
            "rules_version": out.rules_version,
            "issues": [i.model_dump() for i in out.issues],
        },
    }


@router.get("/validation-reports/{report_id}/issues")
async def list_validation_issues_endpoint(
    report_id: uuid.UUID,
    severity: str | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await service.get_validation_report_or_404(db, report_id)
    await check_habitation_access(db, current_user, report.habitation_id, AccessLevel.VIEWER)
    issues = await service.list_validation_issues(
        db, report_id, severity=severity, category=category, limit=limit, offset=offset
    )
    return {
        "success": True,
        "data": [
            {
                "id": i.id,
                "severity": i.severity.value,
                "code": i.code,
                "category": i.category,
                "field_path": i.field_path,
                "message": i.message,
                "observed_value": i.observed_value,
                "expected_range": i.expected_range,
                "suggested_fix": i.suggested_fix,
                "row_number": i.row_number,
            }
            for i in issues
        ],
    }


@router.get("/habitations/{habitation_id}/readiness")
async def get_habitation_readiness_endpoint(
    habitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.VIEWER)
    readiness = await service.get_habitation_readiness(db, habitation_id)
    return {"success": True, "data": readiness}

