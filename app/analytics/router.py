import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.recalibration import compute_recalibration_report
from app.analytics.schemas import RecalibrationReportOut
from app.auth.models import User
from app.core.db import get_db
from app.core.deps import check_habitation_access, get_current_user
from app.core.errors import AppError
from app.engine.coefficients import load as load_coefficients
from app.habitation.models import AccessLevel, HabitationStatus
from app.habitation.service import get_habitation_or_404
from app.simulation.service import get_or_create_default_coefficient_set, materialize_params

router = APIRouter(tags=["analytics"])


@router.get("/api/v1/habitations/{habitation_id}/recalibration-report")
async def get_recalibration_report(
    habitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.VIEWER)
    habitation = await get_habitation_or_404(db, habitation_id)
    if habitation.status != HabitationStatus.READY or habitation.active_parameter_set_id is None:
        raise AppError(
            "HABITATION_NOT_READY",
            "Habitation must be READY with an active VALIDATED parameter set to compute a recalibration report",
            409,
        )

    params = await materialize_params(db, habitation.active_parameter_set_id, habitation.habitation_type.value, {})
    coeff_set = await get_or_create_default_coefficient_set(db, current_user)
    await db.commit()  # get_or_create_default_coefficient_set may have inserted a seed row
    coeffs = load_coefficients(coeff_set.coefficients)

    report = await compute_recalibration_report(db, habitation_id, params, coeffs)
    out = RecalibrationReportOut(
        habitation_id=str(report.habitation_id),
        as_of=report.as_of,
        logged_day_count_90d=report.logged_day_count_90d,
        moving_average_30d=report.moving_average_30d.__dict__,
        moving_average_90d=report.moving_average_90d.__dict__,
        moving_average_annual=report.moving_average_annual.__dict__,
        total_generation_variance=report.total_generation_variance.__dict__,
        per_capita_variance=report.per_capita_variance.__dict__,
        segregation_variance=report.segregation_variance.__dict__,
        fleet_efficiency_variance=report.fleet_efficiency_variance.__dict__,
        derived_festival_multiplier=report.derived_festival_multiplier,
        notes=report.notes,
    )
    return {"success": True, "data": out.model_dump(mode="json")}
