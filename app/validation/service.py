import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.errors import AppError
from app.habitation.models import Habitation, HabitationStatus
from app.parameters.models import ParameterSet, ParameterSetStatus
from app.parameters.service import get_parameter_set_or_404
from app.validation.models import ValidationIssue, ValidationReport, ValidationResult, ValidationScope
from app.validation.pipeline import PipelineResult, run_pipeline


def _result_from_counts(pipeline_result: PipelineResult) -> ValidationResult:
    """PASS_WITH_WARNINGS sits between the two: zero ERRORs (so it never
    blocks commit, BR-01) but at least one WARNING, so the response still
    tells the planner something is worth a second look."""
    if pipeline_result.error_count > 0:
        return ValidationResult.FAIL
    if pipeline_result.warning_count > 0:
        return ValidationResult.PASS_WITH_WARNINGS
    return ValidationResult.PASS


async def _write_report(
    db: AsyncSession,
    *,
    habitation_id: uuid.UUID,
    parameter_set_id: uuid.UUID,
    pipeline_result: PipelineResult,
    triggered_by: uuid.UUID,
) -> ValidationReport:
    result = _result_from_counts(pipeline_result)
    now = datetime.now(timezone.utc)
    report = ValidationReport(
        habitation_id=habitation_id,
        parameter_set_id=parameter_set_id,
        scope=ValidationScope.PARAMETER_SET,
        result=result,
        error_count=pipeline_result.error_count,
        warning_count=pipeline_result.warning_count,
        completeness_pct=pipeline_result.completeness_pct,
        completeness_by_category=pipeline_result.completeness_by_category,
        triggered_by=triggered_by,
        completed_at=now,
    )
    db.add(report)
    await db.flush()

    for issue in pipeline_result.issues:
        db.add(
            ValidationIssue(
                report_id=report.id,
                severity=issue.severity,
                code=issue.code,
                category=issue.category,
                field_path=issue.field_path,
                message=issue.message,
                observed_value=issue.observed_value,
                expected_range=issue.expected_range,
                suggested_fix=issue.suggested_fix,
                row_number=issue.row_number,
            )
        )
    await db.flush()
    report.issues = list(await db.scalars(select(ValidationIssue).where(ValidationIssue.report_id == report.id)))
    return report


async def validate_parameter_set(db: AsyncSession, psid: uuid.UUID, user: User) -> ValidationReport:
    ps = await get_parameter_set_or_404(db, psid)
    if ps.status in (ParameterSetStatus.VALIDATED, ParameterSetStatus.ARCHIVED):
        raise AppError(
            "PARAMETER_SET_IMMUTABLE",
            f"Parameter set is {ps.status.value} and cannot be re-validated",
            409,
        )

    pipeline_result = await run_pipeline(db, psid)
    report = await _write_report(
        db,
        habitation_id=ps.habitation_id,
        parameter_set_id=psid,
        pipeline_result=pipeline_result,
        triggered_by=user.id,
    )

    ps.status = (
        ParameterSetStatus.DRAFT if report.result != ValidationResult.FAIL else ParameterSetStatus.INVALID
    )
    await db.flush()
    return report


async def commit_parameter_set(db: AsyncSession, psid: uuid.UUID) -> ParameterSet:
    ps = await get_parameter_set_or_404(db, psid)
    if ps.status in (ParameterSetStatus.VALIDATED, ParameterSetStatus.ARCHIVED):
        raise AppError(
            "PARAMETER_SET_IMMUTABLE", f"Parameter set is already {ps.status.value}", 409
        )

    # Re-run the pipeline fresh rather than trusting a possibly-stale prior
    # report, so the commit gate always reflects the data as it is right now.
    pipeline_result = await run_pipeline(db, psid)
    if pipeline_result.error_count > 0 or pipeline_result.completeness_pct < 100:
        raise AppError(
            "PARAMETER_SET_NOT_READY",
            "Parameter set must have zero errors and 100% completeness before commit",
            409,
            details={
                "error_count": pipeline_result.error_count,
                "completeness_pct": pipeline_result.completeness_pct,
            },
        )

    previous_validated = await db.scalar(
        select(ParameterSet).where(
            ParameterSet.habitation_id == ps.habitation_id,
            ParameterSet.status == ParameterSetStatus.VALIDATED,
        )
    )
    if previous_validated is not None:
        previous_validated.status = ParameterSetStatus.ARCHIVED

    ps.status = ParameterSetStatus.VALIDATED

    habitation = await db.get(Habitation, ps.habitation_id)
    habitation.active_parameter_set_id = ps.id
    habitation.status = HabitationStatus.READY

    await db.flush()
    return ps


async def get_validation_report_or_404(db: AsyncSession, report_id: uuid.UUID) -> ValidationReport:
    report = await db.get(ValidationReport, report_id)
    if report is None:
        raise AppError("REPORT_NOT_FOUND", "Validation report not found", 404)
    # Eagerly load issues
    report.issues = list(await db.scalars(select(ValidationIssue).where(ValidationIssue.report_id == report.id)))
    return report


async def list_validation_issues(
    db: AsyncSession,
    report_id: uuid.UUID,
    severity: str | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ValidationIssue]:
    await get_validation_report_or_404(db, report_id)
    stmt = select(ValidationIssue).where(ValidationIssue.report_id == report_id)
    if severity:
        stmt = stmt.where(ValidationIssue.severity == severity.upper())
    if category:
        stmt = stmt.where(ValidationIssue.category == category)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.scalars(stmt)
    return list(result)


async def get_habitation_readiness(db: AsyncSession, habitation_id: uuid.UUID) -> dict[str, Any]:
    from app.habitation.models import Habitation
    habitation = await db.get(Habitation, habitation_id)
    if habitation is None or habitation.deleted_at is not None:
        raise AppError("HABITATION_NOT_FOUND", "Habitation not found", 404)

    is_ready = habitation.status == HabitationStatus.READY
    active_ps = habitation.active_parameter_set_id

    missing_items = []
    if not active_ps:
        missing_items.append("No active validated parameter set committed")
    if habitation.boundary is None:
        missing_items.append("Habitation boundary geometry is missing")

    latest_report = None
    if active_ps:
        report = await db.scalar(
            select(ValidationReport)
            .where(ValidationReport.parameter_set_id == active_ps)
            .order_by(ValidationReport.created_at.desc())
            .limit(1)
        )
        if report:
            latest_report = {
                "id": report.id,
                "result": report.result.value,
                "error_count": report.error_count,
                "warning_count": report.warning_count,
                "completeness_pct": report.completeness_pct,
            }
            if report.error_count > 0:
                missing_items.append(f"{report.error_count} validation errors remaining")
            if report.completeness_pct < 100:
                missing_items.append(f"Completeness is only {report.completeness_pct}% (100% required)")

    return {
        "habitation_id": habitation.id,
        "is_ready": is_ready,
        "can_simulate": is_ready and len(missing_items) == 0,
        "active_parameter_set_id": active_ps,
        "latest_validation_report": latest_report,
        "blocking_issues": missing_items,
    }

