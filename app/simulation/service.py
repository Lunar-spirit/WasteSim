import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.budget.service import build_budget_lines, persist_budget_lines
from app.core.errors import AppError
from app.engine.coefficients import default_values as default_coefficient_values
from app.engine.coefficients import load as load_coefficients
from app.engine.run import ENGINE_VERSION
from app.engine.run import run as engine_run
from app.habitation.models import Habitation, HabitationStatus
from app.parameters.models import ParameterDefinition, ParameterSet, ParameterSetStatus
from app.parameters.service import get_parameter_set_full
from app.simulation.models import CoefficientSet, RunFinding, RunStatus, RunType, SimulationResult, SimulationRun, SimulationYearly

DEFAULT_COEFFICIENT_SET_NAME = "india-coastal-v1"


async def get_or_create_default_coefficient_set(db: AsyncSession, user: User) -> CoefficientSet:
    existing = await db.scalar(select(CoefficientSet).where(CoefficientSet.is_default.is_(True)))
    if existing is not None:
        return existing

    # Seeded lazily on first use, not via an Alembic data migration:
    # coefficient_sets.created_by is a NOT NULL FK to users, and a migration
    # runs before any user exists. Self-healing, and the values are exactly
    # app.engine.coefficients' own built-in defaults, so "no coefficient_set
    # yet" and "the default coefficient_set" behave identically.
    coeff_set = CoefficientSet(
        name=DEFAULT_COEFFICIENT_SET_NAME,
        description="Default calibration, seeded on first use from app.engine.coefficients' own defaults.",
        coefficients=default_coefficient_values(),
        is_default=True,
        created_by=user.id,
    )
    db.add(coeff_set)
    await db.flush()
    return coeff_set


async def _validate_overrides(db: AsyncSession, overrides: dict[str, Any]) -> None:
    if not overrides:
        return
    definitions = {f"{d.category}.{d.param_key}": d for d in await db.scalars(select(ParameterDefinition))}
    for key, value in overrides.items():
        definition = definitions.get(key)
        if definition is None:
            raise AppError("INVALID_OVERRIDE", f"'{key}' is not a known parameter", 400)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if definition.min_value is not None and numeric < float(definition.min_value):
            raise AppError(
                "INVALID_OVERRIDE", f"'{key}' must be >= {definition.min_value}, got {value}", 400
            )
        if definition.max_value is not None and numeric > float(definition.max_value):
            raise AppError(
                "INVALID_OVERRIDE", f"'{key}' must be <= {definition.max_value}, got {value}", 400
            )


async def create_run(
    db: AsyncSession, habitation_id: uuid.UUID, payload: Any, user: User
) -> tuple[SimulationRun, bool]:
    """Returns (run, reused) — `reused=True` when an identical QUEUED/
    RUNNING/COMPLETED run already existed and was returned instead of
    duplicating the work."""
    habitation = await db.get(Habitation, habitation_id)
    if habitation is None or habitation.deleted_at is not None:
        raise AppError("HABITATION_NOT_FOUND", "Habitation not found", 404)
    if habitation.status != HabitationStatus.READY or habitation.active_parameter_set_id is None:
        raise AppError(
            "HABITATION_NOT_READY",
            "Habitation must be READY with an active VALIDATED parameter set (BR-19)",
            409,
        )

    parameter_set_id = payload.parameter_set_id or habitation.active_parameter_set_id
    ps = await db.get(ParameterSet, parameter_set_id)
    if ps is None or ps.status != ParameterSetStatus.VALIDATED:
        raise AppError("NO_VALIDATED_PARAMETER_SET", "The chosen parameter set is not VALIDATED", 422)

    if payload.coefficient_set_id is not None:
        coeff_set = await db.get(CoefficientSet, payload.coefficient_set_id)
        if coeff_set is None:
            raise AppError("COEFFICIENT_SET_NOT_FOUND", "Coefficient set not found", 404)
    else:
        coeff_set = await get_or_create_default_coefficient_set(db, user)

    await _validate_overrides(db, payload.param_overrides)

    if payload.run_type == RunType.BASE:
        existing = await db.scalar(
            select(SimulationRun).where(
                SimulationRun.habitation_id == habitation_id,
                SimulationRun.parameter_set_id == ps.id,
                SimulationRun.coefficient_set_id == coeff_set.id,
                SimulationRun.run_type == RunType.BASE,
                SimulationRun.horizon_years == payload.horizon_years,
                SimulationRun.param_overrides == payload.param_overrides,
                SimulationRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.COMPLETED]),
            )
            .order_by(SimulationRun.created_at.desc())
        )
        if existing is not None:
            return existing, True

    run = SimulationRun(
        habitation_id=habitation_id,
        parameter_set_id=ps.id,
        coefficient_set_id=coeff_set.id,
        engine_version=ENGINE_VERSION,
        run_type=payload.run_type,
        label=payload.label,
        horizon_years=payload.horizon_years,
        param_overrides=payload.param_overrides,
        config=payload.config,
        status=RunStatus.QUEUED,
        created_by=user.id,
    )
    db.add(run)
    await db.flush()
    return run, False


async def materialize_params(
    db: AsyncSession, parameter_set_id: uuid.UUID, habitation_type: str, overrides: dict[str, Any]
) -> dict[str, Any]:
    """BR-21: everything the engine sees is a plain dict — no ORM object
    crosses this boundary."""
    full = await get_parameter_set_full(db, parameter_set_id)
    params: dict[str, Any] = {k: dict(v) for k, v in full["categories"].items()}
    params["waste_baseline"] = dict(full["waste_baseline"]) if full["waste_baseline"] else {}
    params["habitation_type"] = habitation_type

    for key, value in overrides.items():
        category, _, param_key = key.partition(".")
        if category in params:
            params[category][param_key] = value
    return params


def _result_row(run_id: uuid.UUID, snapshot: dict[str, Any]) -> SimulationResult:
    composition = snapshot["composition"]
    return SimulationResult(
        run_id=run_id,
        month_index=snapshot["month_index"],
        year_index=snapshot["year_index"],
        calendar_month=snapshot["calendar_month"],
        population=snapshot["population"],
        population_effective=snapshot["population_effective"],
        per_capita_kg_day=snapshot["per_capita_kg_day"],
        waste_domestic_tpd=snapshot["waste_domestic_tpd"],
        waste_bulk_tpd=snapshot["waste_bulk_tpd"],
        waste_industrial_tpd=snapshot["waste_industrial_tpd"],
        waste_total_tpd=snapshot["waste_total_tpd"],
        organic_pct=composition["organic"],
        plastic_pct=composition["plastic"],
        paper_pct=composition["paper"],
        metal_pct=composition["metal"],
        glass_pct=composition["glass"],
        textile_pct=composition["textile"],
        inert_pct=composition["inert"],
        ewaste_pct=composition["ewaste"],
        other_pct=composition["other"],
        collection_coverage_pct=snapshot["collection_coverage_pct"],
        accessibility_index=snapshot["accessibility_index"],
        waste_collected_tpd=snapshot["waste_collected_tpd"],
        waste_uncollected_tpd=snapshot["waste_uncollected_tpd"],
        segregation_pct=snapshot["segregation_pct"],
        organic_treated_tpd=snapshot["organic_treated_tpd"],
        recyclables_recovered_tpd=snapshot["recyclables_recovered_tpd"],
        compost_output_tpd=snapshot["compost_output_tpd"],
        treatment_capacity_tpd=snapshot["treatment_capacity_tpd"],
        treatment_utilization_pct=snapshot["treatment_utilization_pct"],
        to_landfill_tpd=snapshot["to_landfill_tpd"],
        landfill_cumulative_tonnes=snapshot["landfill_cumulative_tonnes"],
        landfill_remaining_tonnes=snapshot["landfill_remaining_tonnes"],
        vehicles_required=snapshot["vehicles_required"],
        vehicle_shortfall=snapshot["vehicle_shortfall"],
        opex_inr=snapshot["opex_inr"],
        capex_inr=snapshot["capex_inr"],
        ghg_tco2e=snapshot["ghg_tco2e"],
        active_event_codes=snapshot["active_event_codes"],
    )


async def execute_run(db: AsyncSession, run: SimulationRun) -> None:
    """BG-04's core: materialize inputs, call the pure engine, and — only if
    the whole 240-step loop succeeds — insert everything in this one
    transaction. If engine_run() raises (MassBalanceError or anything else),
    none of the db.add() calls below ever happen, so a failed run leaves
    ZERO result rows by construction (ERR-10/ERR-11), no explicit rollback
    bookkeeping required.
    """
    habitation = await db.get(Habitation, run.habitation_id)
    coeff_set = await db.get(CoefficientSet, run.coefficient_set_id)
    params = await materialize_params(
        db, run.parameter_set_id, habitation.habitation_type.value, run.param_overrides
    )

    # A SCENARIO run's events live in scenario_events, keyed by this run's
    # own id (module M9) — a BASE/OPTIMIZED run simply has none, so this is
    # always safe to call. Imported here rather than at module level only to
    # keep the direction of the dependency obvious: simulation calls into
    # scenario, never the reverse.
    from app.scenario.service import events_to_engine_format, get_events_for_run

    scenario_events = await get_events_for_run(db, run.id)
    events = events_to_engine_format(scenario_events)

    months = run.horizon_years * 12
    result = engine_run(params, events=events, coeffs_raw=coeff_set.coefficients, months=months, config=run.config)

    for snapshot in result["monthly"]:
        db.add(_result_row(run.id, snapshot))
    for year in result["yearly"]:
        db.add(SimulationYearly(run_id=run.id, **year))
    for finding in result["findings"]:
        db.add(
            RunFinding(
                run_id=run.id,
                code=finding["code"],
                severity=finding["severity"],
                numeric_value=finding["numeric_value"],
                year_index=finding["year_index"],
                message=finding["message"],
            )
        )

    coeffs = load_coefficients(coeff_set.coefficients)
    discount_rate = float(run.config.get("discount_rate", coeffs["discount_rate"]))
    budget_lines = build_budget_lines(result["monthly"], coeffs, discount_rate)
    await persist_budget_lines(db, run.id, budget_lines)

    run.status = RunStatus.COMPLETED
    run.completed_at = datetime.now(timezone.utc)
    run.progress_pct = 100
    await db.flush()


async def get_run_or_404(db: AsyncSession, run_id: uuid.UUID) -> SimulationRun:
    run = await db.get(SimulationRun, run_id)
    if run is None:
        raise AppError("RUN_NOT_FOUND", "Simulation run not found", 404)
    return run


async def list_runs(db: AsyncSession, habitation_id: uuid.UUID, run_type: RunType | None = None) -> list[SimulationRun]:
    stmt = select(SimulationRun).where(SimulationRun.habitation_id == habitation_id)
    if run_type is not None:
        stmt = stmt.where(SimulationRun.run_type == run_type)
    return list(await db.scalars(stmt.order_by(SimulationRun.created_at.desc())))


async def cancel_run(db: AsyncSession, run: SimulationRun) -> SimulationRun:
    if run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        raise AppError("RUN_NOT_CANCELLABLE", f"Run is {run.status.value}, cannot cancel", 409)
    run.status = RunStatus.CANCELLED
    run.completed_at = datetime.now(timezone.utc)
    await db.flush()
    return run


async def get_yearly_results(
    db: AsyncSession, run_id: uuid.UUID, from_year: int | None = None, to_year: int | None = None
) -> list[SimulationYearly]:
    stmt = select(SimulationYearly).where(SimulationYearly.run_id == run_id)
    if from_year is not None:
        stmt = stmt.where(SimulationYearly.year_index >= from_year)
    if to_year is not None:
        stmt = stmt.where(SimulationYearly.year_index <= to_year)
    return list(await db.scalars(stmt.order_by(SimulationYearly.year_index)))


async def get_monthly_results(
    db: AsyncSession, run_id: uuid.UUID, from_year: int | None = None, to_year: int | None = None
) -> list[SimulationResult]:
    stmt = select(SimulationResult).where(SimulationResult.run_id == run_id)
    if from_year is not None:
        stmt = stmt.where(SimulationResult.year_index >= from_year)
    if to_year is not None:
        stmt = stmt.where(SimulationResult.year_index <= to_year)
    return list(await db.scalars(stmt.order_by(SimulationResult.month_index)))


async def get_findings(db: AsyncSession, run_id: uuid.UUID) -> list[RunFinding]:
    return list(await db.scalars(select(RunFinding).where(RunFinding.run_id == run_id)))


async def delete_run(db: AsyncSession, run: SimulationRun) -> None:
    is_parent = await db.scalar(
        select(SimulationRun.id).where(SimulationRun.parent_run_id == run.id).limit(1)
    )
    if is_parent is not None:
        raise AppError("RUN_IS_PARENT", "Another run references this one as its parent; cannot delete", 409)
    await db.delete(run)
    await db.flush()
