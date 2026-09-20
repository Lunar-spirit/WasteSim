"""Module M13 (comparison, design section 4.4 / API-76-78). Reads only —
every number already exists in simulation_yearly; this module just aligns
it by year_index across several runs and, for deltas, subtracts the first
run's own series from the rest.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.comparison.models import RunComparison
from app.core.errors import AppError
from app.simulation.models import SimulationRun, SimulationYearly


async def create_comparison(db: AsyncSession, habitation_id: uuid.UUID, payload: Any, user: User) -> RunComparison:
    runs = []
    for run_id in payload.run_ids:
        run = await db.get(SimulationRun, run_id)
        if run is None:
            raise AppError("RUN_NOT_FOUND", f"Run {run_id} not found", 404)
        if run.habitation_id != habitation_id:
            raise AppError(
                "RUNS_NOT_COMPARABLE", "All compared runs must belong to the same habitation (BR-27)", 400
            )
        runs.append(run)

    comparison = RunComparison(
        habitation_id=habitation_id,
        run_ids=[str(r.id) for r in runs],
        indicators=payload.indicators,
        title=payload.title,
        created_by=user.id,
    )
    db.add(comparison)
    await db.flush()
    return comparison


async def get_comparison_or_404(db: AsyncSession, comparison_id: uuid.UUID) -> RunComparison:
    comparison = await db.get(RunComparison, comparison_id)
    if comparison is None:
        raise AppError("COMPARISON_NOT_FOUND", "Comparison not found", 404)
    return comparison


async def _yearly_by_run(db: AsyncSession, run_id: str) -> dict[int, SimulationYearly]:
    stmt = select(SimulationYearly).where(SimulationYearly.run_id == uuid.UUID(run_id))
    rows = await db.scalars(stmt)
    return {row.year_index: row for row in rows}


async def get_aligned_series(db: AsyncSession, comparison: RunComparison) -> dict[str, Any]:
    per_run = {run_id: await _yearly_by_run(db, run_id) for run_id in comparison.run_ids}
    all_years = sorted({year for yearly in per_run.values() for year in yearly})

    series: dict[str, list[dict[str, Any]]] = {}
    for indicator in comparison.indicators:
        rows = []
        for year_index in all_years:
            values = {}
            for run_id, yearly in per_run.items():
                row = yearly.get(year_index)
                value = getattr(row, indicator, None) if row is not None else None
                values[run_id] = float(value) if value is not None else None
            rows.append({"year_index": year_index, "values": values})
        series[indicator] = rows

    return {"run_ids": comparison.run_ids, "indicators": comparison.indicators, "series": series}


async def get_deltas(db: AsyncSession, comparison: RunComparison) -> dict[str, Any]:
    """Per-year differences against the first run (API-78)."""
    base_run_id = comparison.run_ids[0]
    per_run = {run_id: await _yearly_by_run(db, run_id) for run_id in comparison.run_ids}
    base_yearly = per_run[base_run_id]
    all_years = sorted({year for yearly in per_run.values() for year in yearly})

    deltas: dict[str, list[dict[str, Any]]] = {}
    for indicator in comparison.indicators:
        rows = []
        for year_index in all_years:
            base_row = base_yearly.get(year_index)
            base_value = getattr(base_row, indicator, None) if base_row is not None else None
            entry: dict[str, Any] = {"year_index": year_index}
            for run_id in comparison.run_ids[1:]:
                row = per_run[run_id].get(year_index)
                value = getattr(row, indicator, None) if row is not None else None
                if base_value is None or value is None:
                    entry[run_id] = None
                else:
                    entry[run_id] = float(value) - float(base_value)
            rows.append(entry)
        deltas[indicator] = rows

    return {"base_run_id": base_run_id, "deltas": deltas}
