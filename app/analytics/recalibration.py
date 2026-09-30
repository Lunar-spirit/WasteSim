"""Statistical Aggregation Service: turns app/daily_logs/models.py's raw
field entries into moving averages, empirical-vs-theoretical variance, and
(for DATA_DRIVEN_HYBRID runs) concrete overrides for app/simulation/
service.py's execute_run() to merge into params/coeffs before calling the
still-pure engine. No table of its own — every function here reads
daily_waste_logs plus whatever parameter_set/coefficient data the caller
already has.

Every average below requires a minimum number of logged days before it's
trusted; short of that it's None, and callers (the report endpoint, hybrid
mode) fall back to the theoretical value rather than swinging on 1-2 data
points.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daily_logs.models import DailyWasteLog
from app.engine.coefficients import Coefficients

MIN_DAYS_FOR_AVERAGE = 5
MIN_DAYS_PER_FESTIVAL_BUCKET = 3


@dataclass
class MovingAverages:
    window_days: int
    sample_days: int
    avg_total_collected_tpd: float | None
    avg_organic_tpd: float | None
    avg_dry_recyclable_tpd: float | None
    avg_vehicles_deployed: float | None
    avg_coverage_pct_observed: float | None


@dataclass
class VarianceMetric:
    label: str
    theoretical: float | None
    empirical: float | None
    variance_pct: float | None  # (empirical - theoretical) / theoretical * 100


@dataclass
class RecalibrationReport:
    habitation_id: uuid.UUID
    as_of: date
    logged_day_count_90d: int
    moving_average_30d: MovingAverages
    moving_average_90d: MovingAverages
    moving_average_annual: MovingAverages
    # Total tonnes/day, not per-person — the "your baseline assumes 5.78
    # t/day but the last 30 days averaged 6.42 t/day" framing a planner
    # reads directly, vs. per_capita_variance's abstract kg/person/day.
    # theoretical = population * baseline per-capita / 1000; empirical =
    # the 30-day moving average, the freshest trustworthy window.
    total_generation_variance: VarianceMetric
    per_capita_variance: VarianceMetric
    segregation_variance: VarianceMetric
    fleet_efficiency_variance: VarianceMetric
    derived_festival_multiplier: float | None
    notes: list[str]


async def _moving_average(db: AsyncSession, habitation_id: uuid.UUID, as_of: date, window_days: int) -> MovingAverages:
    start = as_of - timedelta(days=window_days)
    row = (
        await db.execute(
            select(
                func.count(DailyWasteLog.id),
                func.avg(DailyWasteLog.total_collected_tonnes),
                func.avg(DailyWasteLog.organic_tonnes),
                func.avg(DailyWasteLog.dry_recyclable_tonnes),
                func.avg(DailyWasteLog.vehicles_deployed),
                func.avg(DailyWasteLog.collection_coverage_pct_observed),
            ).where(
                DailyWasteLog.habitation_id == habitation_id,
                DailyWasteLog.log_date > start,
                DailyWasteLog.log_date <= as_of,
            )
        )
    ).one()
    count, avg_total, avg_organic, avg_dry, avg_vehicles, avg_coverage = row

    if count < MIN_DAYS_FOR_AVERAGE:
        return MovingAverages(window_days, count, None, None, None, None, None)

    return MovingAverages(
        window_days=window_days,
        sample_days=count,
        avg_total_collected_tpd=float(avg_total) if avg_total is not None else None,
        avg_organic_tpd=float(avg_organic) if avg_organic is not None else None,
        avg_dry_recyclable_tpd=float(avg_dry) if avg_dry is not None else None,
        avg_vehicles_deployed=float(avg_vehicles) if avg_vehicles is not None else None,
        avg_coverage_pct_observed=float(avg_coverage) if avg_coverage is not None else None,
    )


async def _derived_festival_multiplier(
    db: AsyncSession, habitation_id: uuid.UUID, festival_months: list[int]
) -> float | None:
    """Empirical festival_waste_multiplier: logged tonnage on festival-month
    days vs non-festival-month days, ratio'd the same way the static
    coefficient default is used in app/engine/step.py's Part 3. None (not a
    guess) when either bucket doesn't have enough real days behind it."""
    if not festival_months:
        return None

    # Two plain queries, not one GROUP BY on a computed boolean: SQLAlchemy
    # compiles the same Python expression into two textually-different
    # parameterized clauses when it appears in both the SELECT list and
    # GROUP BY, and Postgres then refuses to recognize them as the same
    # expression ("column must appear in GROUP BY") even though they're
    # semantically identical — simplest fix is to sidestep it entirely.
    is_festival_month = func.extract("month", DailyWasteLog.log_date).in_(festival_months)

    async def _bucket(condition) -> tuple[int, float | None]:
        row = (
            await db.execute(
                select(func.count(DailyWasteLog.id), func.avg(DailyWasteLog.total_collected_tonnes)).where(
                    DailyWasteLog.habitation_id == habitation_id, condition
                )
            )
        ).one()
        return row[0], (float(row[1]) if row[1] is not None else None)

    festival_count, festival_avg = await _bucket(is_festival_month)
    normal_count, normal_avg = await _bucket(~is_festival_month)
    if (
        festival_count < MIN_DAYS_PER_FESTIVAL_BUCKET
        or normal_count < MIN_DAYS_PER_FESTIVAL_BUCKET
        or not normal_avg
    ):
        return None
    return float(festival_avg) / float(normal_avg)


def _variance(label: str, theoretical: float | None, empirical: float | None) -> VarianceMetric:
    variance_pct = None
    if theoretical is not None and empirical is not None and theoretical != 0:
        variance_pct = (empirical - theoretical) / theoretical * 100.0
    return VarianceMetric(label=label, theoretical=theoretical, empirical=empirical, variance_pct=variance_pct)


async def compute_recalibration_report(
    db: AsyncSession,
    habitation_id: uuid.UUID,
    params: dict[str, Any],
    coeffs: Coefficients,
    as_of: date | None = None,
) -> RecalibrationReport:
    as_of = as_of or date.today()

    ma_30 = await _moving_average(db, habitation_id, as_of, 30)
    ma_90 = await _moving_average(db, habitation_id, as_of, 90)
    ma_annual = await _moving_average(db, habitation_id, as_of, 365)

    population = float(params.get("demography", {}).get("population") or 0)
    baseline_per_capita = params.get("waste_baseline", {}).get("per_capita_generation_kg_day")

    theoretical_total_tpd = (
        float(baseline_per_capita) * population / 1000.0
        if baseline_per_capita is not None and population > 0
        else None
    )
    total_generation_variance = _variance(
        "Total waste generation (tonnes/day)", theoretical_total_tpd, ma_30.avg_total_collected_tpd
    )

    empirical_per_capita = None
    if ma_90.avg_total_collected_tpd is not None and population > 0:
        empirical_per_capita = ma_90.avg_total_collected_tpd * 1000.0 / population
    per_capita_variance = _variance(
        "Per-capita generation (kg/day)",
        float(baseline_per_capita) if baseline_per_capita is not None else None,
        empirical_per_capita,
    )

    stated_segregation = params.get("cultural_context", {}).get("segregation_practice_pct")
    realized_segregation = None
    if ma_90.avg_total_collected_tpd and ma_90.avg_organic_tpd is not None and ma_90.avg_dry_recyclable_tpd is not None:
        realized_segregation = (ma_90.avg_organic_tpd + ma_90.avg_dry_recyclable_tpd) / ma_90.avg_total_collected_tpd * 100.0
    segregation_variance = _variance(
        "Segregation / diversion (%)",
        float(stated_segregation) if stated_segregation is not None else None,
        realized_segregation,
    )

    theoretical_fleet_efficiency = (
        coeffs["avg_vehicle_capacity_tonnes"] * coeffs["trips_per_vehicle_day"] * coeffs["fleet_availability"]
    )
    empirical_fleet_efficiency = None
    if ma_90.avg_total_collected_tpd and ma_90.avg_vehicles_deployed:
        empirical_fleet_efficiency = ma_90.avg_total_collected_tpd / ma_90.avg_vehicles_deployed
    fleet_efficiency_variance = _variance(
        "Fleet turnaround (tonnes/vehicle/day)",
        theoretical_fleet_efficiency,
        empirical_fleet_efficiency,
    )

    derived_festival_multiplier = await _derived_festival_multiplier(db, habitation_id, coeffs["festival_months"])

    notes: list[str] = []
    if ma_90.sample_days < MIN_DAYS_FOR_AVERAGE:
        notes.append(
            f"Only {ma_90.sample_days} day(s) logged in the last 90 — need at least "
            f"{MIN_DAYS_FOR_AVERAGE} before empirical figures are shown instead of theoretical ones."
        )
    if derived_festival_multiplier is None:
        notes.append(
            "Not enough logged days inside and outside festival months yet to derive a real "
            "festival surge multiplier — the static coefficient default is still in use."
        )

    return RecalibrationReport(
        habitation_id=habitation_id,
        as_of=as_of,
        logged_day_count_90d=ma_90.sample_days,
        moving_average_30d=ma_30,
        moving_average_90d=ma_90,
        moving_average_annual=ma_annual,
        total_generation_variance=total_generation_variance,
        per_capita_variance=per_capita_variance,
        segregation_variance=segregation_variance,
        fleet_efficiency_variance=fleet_efficiency_variance,
        derived_festival_multiplier=derived_festival_multiplier,
        notes=notes,
    )


async def hybrid_mode_overrides(
    db: AsyncSession,
    habitation_id: uuid.UUID,
    params: dict[str, Any],
    coeffs: Coefficients,
    as_of: date | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """For execute_run() when simulation_runs.config.engine_mode ==
    DATA_DRIVEN_HYBRID: returns (config_overrides, coeffs_overrides, notes)
    to merge into the run's own config/coefficients dict copies before
    calling the engine. Both override dicts are empty (a no-op — the run
    behaves exactly like THEORETICAL) when there isn't enough logged
    history yet; notes explains why, for a RunFinding."""
    report = await compute_recalibration_report(db, habitation_id, params, coeffs, as_of)

    config_overrides: dict[str, Any] = {}
    coeffs_overrides: dict[str, Any] = {}
    notes: list[str] = list(report.notes)

    if report.moving_average_90d.avg_total_collected_tpd is not None:
        population = float(params.get("demography", {}).get("population") or 0)
        if population > 0:
            override = report.moving_average_90d.avg_total_collected_tpd * 1000.0 / population
            config_overrides["override_starting_per_capita_kg_day"] = override
            notes.append(
                f"20-year projection starts from the empirical 90-day average "
                f"({override:.3f} kg/day/person) instead of the declared baseline "
                f"({report.per_capita_variance.theoretical})."
            )

    if report.derived_festival_multiplier is not None:
        coeffs_overrides["festival_waste_multiplier"] = report.derived_festival_multiplier
        notes.append(
            f"Festival waste multiplier derived from logged history: "
            f"{report.derived_festival_multiplier:.3f}x (static default replaced)."
        )

    return config_overrides, coeffs_overrides, notes
