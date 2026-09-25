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
        # Flushed separately, before promoting `ps` below: SQLAlchemy's unit
        # of work batches same-table UPDATEs from one flush into a single
        # executemany, and found live, this ends up sending the "set ps to
        # VALIDATED" row before the "archive previous_validated" row within
        # that batch — a transient state with two VALIDATED rows for the
        # same habitation that trips uq_one_validated_parameter_set_per_habitation
        # even though the end state (one VALIDATED, one ARCHIVED) is valid.
        # A dedicated flush here forces the archive to commit first.
        await db.flush()

    ps.status = ParameterSetStatus.VALIDATED

    habitation = await db.get(Habitation, ps.habitation_id)
    habitation.active_parameter_set_id = ps.id
    habitation.status = HabitationStatus.READY

    await db.flush()
    return ps
