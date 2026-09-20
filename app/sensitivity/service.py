"""Module M10 (sensitivity/elasticity, design section 5.6's sibling — the
design gives sensitivity no dedicated numbered subsection, only the table
schemas, BR-28 and the API table, so the sweep-and-elasticity mechanics
below are this session's own design, built the same way every other
under-specified corner of this project has been: the simplest option
consistent with the ten CLAUDE.md rules, documented here rather than
guessed at silently.

BG-06 in the design is "one child simulation per swept value as a Celery
group [chord]". This session simplifies that to sequential child runs
inside one Celery task — the same simplification module M11's search
already made for its own candidate evaluations — because a real chord needs
a chord-capable result backend and is materially harder to test
deterministically, for no behavioural difference the API contract exposes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.errors import AppError
from app.optimization.models import AnalysisStatus
from app.parameters.models import ParameterDefinition
from app.parameters.service import get_parameter_set_full
from app.sensitivity.models import SensitivityAnalysis, SensitivityPoint
from app.simulation.models import RunFinding, RunStatus, RunType, SimulationRun, SimulationYearly
from app.workers.tasks_simulate import run_simulation

MAX_SWEEP_POINTS = 25  # design's own Security Controls section: "sweeps at 25 points"

DEFAULT_INDICATORS = ["NPV_TOTAL_COST", "LANDFILL_EXHAUSTION_YEAR", "RECOVERY_RATE_Y20"]

# A subset of run_findings.code — resolved from that table; anything else is
# read from the LAST simulation_yearly row's own column by that name.
_FINDING_CODES = {
    "LANDFILL_EXHAUSTION_YEAR",
    "FIRST_VEHICLE_SHORTFALL_YEAR",
    "TREATMENT_SATURATION_YEAR",
    "NPV_TOTAL_COST",
    "PEAK_UNCOLLECTED_TPD",
    "RECOVERY_RATE_Y20",
    "BUDGET_BREACH_YEAR",
}


def _split_param_path(param_path: str) -> tuple[str, str]:
    category, _, field = param_path.partition(".")
    if not category or not field:
        raise AppError("PARAM_NOT_SWEEPABLE", f"'{param_path}' is not category.field shaped", 400)
    return category, field


async def create_sweep(db: AsyncSession, habitation_id: uuid.UUID, payload: Any, user: User) -> SensitivityAnalysis:
    base_run = await db.get(SimulationRun, payload.base_run_id)
    if base_run is None or base_run.habitation_id != habitation_id:
        raise AppError("BASE_RUN_NOT_FOUND", "Base run not found for this habitation", 404)
    if base_run.status != RunStatus.COMPLETED:
        raise AppError("BASE_RUN_NOT_COMPLETED", "base_run_id must reference a COMPLETED run", 409)

    if len(payload.values) > MAX_SWEEP_POINTS:
        raise AppError(
            "TOO_MANY_SWEEP_POINTS", f"A sweep may test at most {MAX_SWEEP_POINTS} values", 400
        )

    category, field = _split_param_path(payload.param_path)
    definition = await db.scalar(
        select(ParameterDefinition).where(
            ParameterDefinition.category == category, ParameterDefinition.param_key == field
        )
    )
    if definition is None or not definition.is_sweepable:
        raise AppError(
            "PARAM_NOT_SWEEPABLE", f"'{payload.param_path}' is not marked sweepable in the catalogue (BR-28)", 400
        )
    for value in payload.values:
        if definition.min_value is not None and value < float(definition.min_value):
            raise AppError(
                "VALUE_OUT_OF_RANGE",
                f"{value} is below the catalogue minimum {definition.min_value} for '{payload.param_path}'",
                400,
            )
        if definition.max_value is not None and value > float(definition.max_value):
            raise AppError(
                "VALUE_OUT_OF_RANGE",
                f"{value} is above the catalogue maximum {definition.max_value} for '{payload.param_path}'",
                400,
            )

    analysis = SensitivityAnalysis(
        habitation_id=habitation_id,
        base_run_id=base_run.id,
        param_path=payload.param_path,
        swept_values=payload.values,
        indicators=payload.indicators or DEFAULT_INDICATORS,
        status=AnalysisStatus.QUEUED,
        created_by=user.id,
    )
    db.add(analysis)
    await db.flush()
    return analysis


async def _resolve_indicator(db: AsyncSession, run_id: uuid.UUID, indicator: str) -> float | None:
    if indicator in _FINDING_CODES:
        finding = await db.scalar(
            select(RunFinding).where(RunFinding.run_id == run_id, RunFinding.code == indicator)
        )
        if finding is None or finding.numeric_value is None:
            return None
        return float(finding.numeric_value)

    last_year = await db.scalar(
        select(SimulationYearly).where(SimulationYearly.run_id == run_id).order_by(SimulationYearly.year_index.desc())
    )
    if last_year is None or not hasattr(last_year, indicator):
        return None
    value = getattr(last_year, indicator)
    return float(value) if value is not None else None


def _elasticity(base_value: float | None, indicator_value: float | None, base_param: float, swept_param: float) -> float | None:
    """Point elasticity: (% change in the indicator) / (% change in the
    parameter), evaluated against the base run. None when either side of
    the ratio is undefined (a finding that never fired, or the parameter's
    base value is 0 so "% change" has no meaning)."""
    if base_value is None or indicator_value is None or base_param == 0 or base_value == 0:
        return None
    pct_indicator = (indicator_value - base_value) / abs(base_value)
    pct_param = (swept_param - base_param) / abs(base_param)
    if pct_param == 0:
        return None
    return round(pct_indicator / pct_param, 4)


async def run_sweep(db: AsyncSession, analysis: SensitivityAnalysis, session_factory) -> None:
    analysis.status = AnalysisStatus.RUNNING
    await db.flush()

    base_run = await db.get(SimulationRun, analysis.base_run_id)
    category, field = _split_param_path(analysis.param_path)
    full = await get_parameter_set_full(db, base_run.parameter_set_id)
    base_param_value = full["categories"].get(category, {}).get(field)
    base_param_value = float(base_param_value) if base_param_value is not None else 0.0

    base_indicator_values = {
        indicator: await _resolve_indicator(db, base_run.id, indicator) for indicator in analysis.indicators
    }

    any_failed = False
    for swept_value in analysis.swept_values:
        child = SimulationRun(
            habitation_id=analysis.habitation_id,
            parameter_set_id=base_run.parameter_set_id,
            coefficient_set_id=base_run.coefficient_set_id,
            engine_version=base_run.engine_version,
            run_type=RunType.SENSITIVITY,
            parent_run_id=base_run.id,
            label=f"Sensitivity: {analysis.param_path}={swept_value}",
            horizon_years=base_run.horizon_years,
            param_overrides={analysis.param_path: swept_value},
            config=base_run.config,
            status=RunStatus.QUEUED,
            created_by=analysis.created_by,
        )
        db.add(child)
        await db.flush()
        await db.commit()  # visible to run_simulation's own separate session

        error: str | None = None
        try:
            await run_simulation(str(child.id), session_factory=session_factory)
        except Exception as exc:  # noqa: BLE001 - a failed point must not abort the sweep (BG-06)
            error = f"{type(exc).__name__}: {exc}"
            any_failed = True

        await db.refresh(child)  # pick up the other session's commit

        indicator_values: dict[str, float] = {}
        elasticity: dict[str, float] | None = None
        if child.status == RunStatus.COMPLETED:
            indicator_values = {
                indicator: value
                for indicator, value in {
                    indicator: await _resolve_indicator(db, child.id, indicator) for indicator in analysis.indicators
                }.items()
                if value is not None
            }
            elasticity = {
                indicator: e
                for indicator in analysis.indicators
                if (
                    e := _elasticity(
                        base_indicator_values.get(indicator), indicator_values.get(indicator), base_param_value, swept_value
                    )
                )
                is not None
            }
        else:
            any_failed = True
            error = error or (child.error_detail or "child run failed")

        db.add(
            SensitivityPoint(
                analysis_id=analysis.id,
                swept_value=swept_value,
                child_run_id=child.id if child.status == RunStatus.COMPLETED else None,
                indicator_values=indicator_values,
                elasticity=elasticity,
                error=error,
            )
        )
        await db.commit()

    analysis.status = AnalysisStatus.PARTIAL if any_failed else AnalysisStatus.COMPLETED
    analysis.completed_at = datetime.now(timezone.utc)
    await db.commit()


async def get_analysis_or_404(db: AsyncSession, analysis_id: uuid.UUID) -> SensitivityAnalysis:
    analysis = await db.get(SensitivityAnalysis, analysis_id)
    if analysis is None:
        raise AppError("ANALYSIS_NOT_FOUND", "Sensitivity analysis not found", 404)
    return analysis


async def get_points(db: AsyncSession, analysis_id: uuid.UUID) -> list[SensitivityPoint]:
    stmt = select(SensitivityPoint).where(SensitivityPoint.analysis_id == analysis_id).order_by(SensitivityPoint.id)
    return list(await db.scalars(stmt))


async def get_tornado(db: AsyncSession, analysis: SensitivityAnalysis) -> list[dict[str, Any]]:
    """Ranked impact data (API-65): for each indicator this sweep tracked,
    the range of outcomes it produced and the largest elasticity seen —
    sorted so the indicator this one parameter moves the most comes first."""
    points = await get_points(db, analysis.id)
    rows = []
    for indicator in analysis.indicators:
        values = [p.indicator_values.get(indicator) for p in points if indicator in p.indicator_values]
        elasticities = [
            p.elasticity.get(indicator) for p in points if p.elasticity and indicator in p.elasticity
        ]
        if not values:
            continue
        rows.append(
            {
                "indicator": indicator,
                "min_value": min(values),
                "max_value": max(values),
                "range": max(values) - min(values),
                "max_abs_elasticity": max((abs(e) for e in elasticities), default=None),
            }
        )
    rows.sort(key=lambda r: (r["max_abs_elasticity"] is not None, r["max_abs_elasticity"] or r["range"]), reverse=True)
    return rows


async def list_analyses(db: AsyncSession, habitation_id: uuid.UUID) -> list[SensitivityAnalysis]:
    stmt = (
        select(SensitivityAnalysis)
        .where(SensitivityAnalysis.habitation_id == habitation_id)
        .order_by(SensitivityAnalysis.created_at.desc())
    )
    return list(await db.scalars(stmt))
