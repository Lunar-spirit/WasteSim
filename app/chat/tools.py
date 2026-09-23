"""The fixed tool set (design 5.8) — the only way the chat layer can touch
data. Every tool is a thin wrapper around an existing service (BR-29:
"ChatService calls services, never repositories"); none of them contains
its own SQL or its own permission logic — each reuses the exact same
dependency-shaped checks (`ensure_read_access`, `check_habitation_access`,
role membership) the equivalent REST endpoint already uses, so a chat
session can never do more than the asking user could do directly through
the API.

Every tool function raises AppError on a permission or not-found problem —
app/chat/service.py catches that and records it in chat_tool_calls rather
than letting it escape as an HTTP error, because a refused tool call is a
normal conversational outcome (design: "the answer explains the
restriction"), not a broken request.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.automation.schemas import AutoPopulateIn
from app.automation.service import auto_populate
from app.budget.service import get_budget_summary
from app.comparison.schemas import DEFAULT_COMPARISON_INDICATORS
from app.core.deps import check_habitation_access
from app.core.errors import AppError
from app.gis.service import list_layers
from app.habitation.models import AccessLevel
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.optimization.schemas import OptimizationCreateIn
from app.optimization.service import create_optimization
from app.parameters.models import ParameterSet
from app.scenario.schemas import ScenarioCreateIn
from app.scenario.service import create_scenario_run
from app.sensitivity.schemas import SensitivitySweepIn
from app.sensitivity.service import create_sweep
from app.simulation.models import RunType, SimulationResult, SimulationRun, SimulationYearly
from app.simulation.service import get_findings, get_run_or_404, list_runs
from app.workers.tasks_optimize import optimize as optimize_task
from app.workers.tasks_sensitivity import sweep as sweep_task
from app.workers.tasks_simulate import simulate as simulate_task

_EXPLAIN_DIFFERENCE_INDICATORS = [
    "waste_collected_tpd",
    "waste_uncollected_tpd",
    "to_landfill_tpd",
    "opex_inr",
    "ghg_tco2e",
    "collection_coverage_pct",
    "treatment_utilization_pct",
    "vehicle_shortfall",
]


async def _run_with_habitation_access(db: AsyncSession, user: User, run_id: uuid.UUID) -> SimulationRun:
    run = await get_run_or_404(db, run_id)
    habitation = await get_habitation_or_404(db, run.habitation_id)
    await ensure_read_access(db, user, habitation)
    return run


async def get_habitation_summary(db: AsyncSession, user: User, habitation_id: uuid.UUID, **_: Any) -> dict[str, Any]:
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, user, habitation)
    active_version = None
    if habitation.active_parameter_set_id is not None:
        ps = await db.get(ParameterSet, habitation.active_parameter_set_id)
        active_version = ps.version_no if ps else None
    layers = await list_layers(db, habitation_id)
    return {
        "habitation_id": str(habitation_id),
        "name": habitation.name,
        "habitation_type": habitation.habitation_type.value,
        "status": habitation.status.value,
        "active_parameter_set_version": active_version,
        "layers": [{"layer_name": layer.layer_name, "layer_type": layer.layer_type.value} for layer in layers],
    }


async def tool_list_runs(db: AsyncSession, user: User, habitation_id: uuid.UUID, run_type: str | None = None, **_: Any) -> dict[str, Any]:
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, user, habitation)
    runs = await list_runs(db, habitation_id, RunType(run_type) if run_type else None)
    result = []
    for run in runs:
        findings = await get_findings(db, run.id)
        result.append(
            {
                "run_id": str(run.id),
                "label": run.label,
                "run_type": run.run_type.value,
                "status": run.status.value,
                "findings": [{"code": f.code, "numeric_value": float(f.numeric_value) if f.numeric_value is not None else None} for f in findings],
            }
        )
    return {"runs": result}


async def tool_get_run_result(
    db: AsyncSession, user: User, habitation_id: uuid.UUID, run_id: str, year_index: int | None = None, indicators: list[str] | None = None, **_: Any
) -> dict[str, Any]:
    run = await _run_with_habitation_access(db, user, uuid.UUID(run_id))
    if run.status.value != "COMPLETED":
        return {"run_id": run_id, "status": run.status.value, "message": "that simulation is still running"}

    from sqlalchemy import select

    stmt = select(SimulationYearly).where(SimulationYearly.run_id == run.id)
    if year_index is not None:
        stmt = stmt.where(SimulationYearly.year_index == year_index)
    rows = list(await db.scalars(stmt.order_by(SimulationYearly.year_index)))
    indicators = indicators or DEFAULT_COMPARISON_INDICATORS
    return {
        "run_id": run_id,
        "years": [
            {"year_index": r.year_index, **{i: (float(getattr(r, i)) if hasattr(r, i) and getattr(r, i) is not None else None) for i in indicators}}
            for r in rows
        ],
    }


async def tool_get_run_findings(db: AsyncSession, user: User, habitation_id: uuid.UUID, run_id: str, **_: Any) -> dict[str, Any]:
    run = await _run_with_habitation_access(db, user, uuid.UUID(run_id))
    findings = await get_findings(db, run.id)
    return {
        "run_id": run_id,
        "findings": [
            {"code": f.code, "severity": f.severity.value, "numeric_value": float(f.numeric_value) if f.numeric_value is not None else None, "message": f.message}
            for f in findings
        ],
    }


async def tool_compare_runs(db: AsyncSession, user: User, habitation_id: uuid.UUID, run_ids: list[str], indicators: list[str] | None = None, **_: Any) -> dict[str, Any]:
    from app.comparison.schemas import ComparisonCreateIn
    from app.comparison.service import create_comparison, get_aligned_series

    payload = ComparisonCreateIn(run_ids=[uuid.UUID(r) for r in run_ids], indicators=indicators or DEFAULT_COMPARISON_INDICATORS)
    first_run = await _run_with_habitation_access(db, user, payload.run_ids[0])
    comparison = await create_comparison(db, first_run.habitation_id, payload, user)
    return await get_aligned_series(db, comparison)


async def tool_get_budget(db: AsyncSession, user: User, habitation_id: uuid.UUID, run_id: str, **_: Any) -> dict[str, Any]:
    run = await _run_with_habitation_access(db, user, uuid.UUID(run_id))
    summary = await get_budget_summary(db, run.id)
    summary.pop("lines", None)  # ORM rows aren't JSON-serialisable citation payloads
    return summary


async def tool_explain_difference(db: AsyncSession, user: User, habitation_id: uuid.UUID, run_a: str, run_b: str, **_: Any) -> dict[str, Any]:
    from sqlalchemy import select

    ra = await _run_with_habitation_access(db, user, uuid.UUID(run_a))
    rb = await _run_with_habitation_access(db, user, uuid.UUID(run_b))
    rows_a = {r.month_index: r for r in await db.scalars(select(SimulationResult).where(SimulationResult.run_id == ra.id))}
    rows_b = {r.month_index: r for r in await db.scalars(select(SimulationResult).where(SimulationResult.run_id == rb.id))}
    common_months = sorted(set(rows_a) & set(rows_b))

    diverging = []
    for indicator in _EXPLAIN_DIFFERENCE_INDICATORS:
        best_month, best_diff = None, 0.0
        for month in common_months:
            va, vb = getattr(rows_a[month], indicator), getattr(rows_b[month], indicator)
            if va is None or vb is None:
                continue
            diff = abs(float(va) - float(vb))
            if diff > best_diff:
                best_diff, best_month = diff, month
        if best_month is not None:
            diverging.append({"indicator": indicator, "month_index": best_month, "abs_difference": best_diff})
    diverging.sort(key=lambda d: d["abs_difference"], reverse=True)
    return {"run_a": run_a, "run_b": run_b, "largest_divergences": diverging[:5]}


async def tool_create_scenario_run(db: AsyncSession, user: User, habitation_id: uuid.UUID, base_run_id: str, events: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
    base_run = await _run_with_habitation_access(db, user, uuid.UUID(base_run_id))
    await check_habitation_access(db, user, base_run.habitation_id, AccessLevel.EDITOR)
    payload = ScenarioCreateIn(events=events)
    scenario_run = await create_scenario_run(db, base_run.id, payload, user)
    await db.commit()
    task = simulate_task.delay(str(scenario_run.id))
    scenario_run.job_id = task.id
    await db.commit()
    return {"run_id": str(scenario_run.id), "status": scenario_run.status.value, "job_id": task.id}


async def tool_run_sensitivity(db: AsyncSession, user: User, habitation_id: uuid.UUID, param: str, values: list[float], **_: Any) -> dict[str, Any]:
    if user.role not in (UserRole.ADMIN, UserRole.PLANNER, UserRole.RESEARCHER):
        raise AppError("FORBIDDEN_ROLE", "Only ADMIN, PLANNER or RESEARCHER may run a sensitivity sweep", 403)
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, user, habitation)
    runs = await list_runs(db, habitation_id, RunType.BASE)
    completed = next((r for r in runs if r.status.value == "COMPLETED"), None)
    if completed is None:
        raise AppError("BASE_RUN_NOT_FOUND", "No COMPLETED base run to sweep against", 404)
    payload = SensitivitySweepIn(base_run_id=completed.id, param_path=param, values=values)
    analysis = await create_sweep(db, habitation_id, payload, user)
    await db.commit()
    task = sweep_task.delay(str(analysis.id))
    return {"analysis_id": str(analysis.id), "job_id": task.id}


async def tool_create_optimization(db: AsyncSession, user: User, habitation_id: uuid.UUID, objectives: dict[str, float], constraints: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    await check_habitation_access(db, user, habitation_id, AccessLevel.EDITOR)
    runs = await list_runs(db, habitation_id, RunType.BASE)
    completed = next((r for r in runs if r.status.value == "COMPLETED"), None)
    if completed is None:
        raise AppError("BASE_RUN_NOT_FOUND", "No COMPLETED base run to optimize against", 404)
    payload = OptimizationCreateIn(base_run_id=completed.id, objectives=objectives, constraints=constraints or {})
    run, notes = await create_optimization(db, habitation_id, payload, user)
    await db.commit()
    task = optimize_task.delay(str(run.id))
    return {"optimization_id": str(run.id), "job_id": task.id, "notes": notes}


async def tool_auto_populate_habitation(
    db: AsyncSession, user: User, habitation_id: uuid.UUID, parameter_set_id: str | None = None, **_: Any
) -> dict[str, Any]:
    """Wraps POST /habitations/{id}/auto-populate (the automation module) so
    a user can ask the chatbot to fill in missing roads/rainfall/terrain
    instead of calling the endpoint directly. Same EDITOR-level permission
    check as every other write tool here — enforced inside
    app.automation.service.auto_populate itself, not re-implemented here."""
    payload = AutoPopulateIn(parameter_set_id=uuid.UUID(parameter_set_id) if parameter_set_id else None)
    result = await auto_populate(db, habitation_id, payload, user)
    await db.commit()
    return result


# Registry: tool_name -> (callable, is_write). A write tool commits its own
# side effects internally (they're all 202-shaped background jobs); a read
# tool only ever selects.
TOOL_REGISTRY: dict[str, tuple[Callable[..., Any], bool]] = {
    "get_habitation_summary": (get_habitation_summary, False),
    "list_runs": (tool_list_runs, False),
    "get_run_result": (tool_get_run_result, False),
    "get_run_findings": (tool_get_run_findings, False),
    "compare_runs": (tool_compare_runs, False),
    "get_budget": (tool_get_budget, False),
    "explain_difference": (tool_explain_difference, False),
    "create_scenario_run": (tool_create_scenario_run, True),
    "run_sensitivity": (tool_run_sensitivity, True),
    "create_optimization": (tool_create_optimization, True),
    "auto_populate_habitation": (tool_auto_populate_habitation, True),
}
