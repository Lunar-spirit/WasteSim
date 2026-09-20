"""Module M11 orchestration: validate an optimization request (BR-24, BR-26),
run the staged search (design 5.6), persist every candidate evaluated
(insert-only, BR-31), and promote a chosen one into a real OPTIMIZED
simulation run (API-71) — reusing app.workers.tasks_simulate.simulate for
that promoted run's own execution, exactly as module M9 reused it for a
SCENARIO run. This module is a caller of app/engine/, not part of it, so
(unlike app/engine/ itself) it is free to import ORM models and other app/
services (rule 8 only restricts app/engine/).
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.errors import AppError
from app.engine.coefficients import Coefficients
from app.engine.coefficients import load as load_coefficients
from app.engine.run import run as engine_run
from app.habitation.models import Habitation
from app.optimization import explain, scoring, search
from app.optimization.models import (
    AnalysisStatus,
    ObjectiveKind,
    OptimizationCandidate,
    OptimizationObjective,
    OptimizationRun,
    OptStage,
    OptStrategy,
)
from app.optimization.space import DECISION_VARIABLES, build_decision_space
from app.simulation.models import CoefficientSet, RunStatus, RunType, SimulationRun
from app.simulation.service import get_yearly_results, materialize_params

WEIGHT_TOLERANCE = 0.001

# The "do-nothing" plan: every lever left exactly where the base run already
# has it. Re-simulating this always reproduces the base run byte-for-byte
# (BR-20) — the sanity anchor T-53 checks the search against, and the
# candidate every objective is normalised relative to (scoring.py).
def _do_nothing_values(current_coverage: float, current_segregation: float) -> dict[str, Any]:
    return {
        "add_vehicles": 0,
        "add_treatment_capacity_tpd": 0.0,
        "target_coverage_pct": current_coverage,
        "target_segregation_pct": current_segregation,
        "landfill_expansion_tonnes": 0.0,
        "transfer_stations": 0,
    }


async def create_optimization(
    db: AsyncSession, habitation_id: uuid.UUID, payload: Any, user: User
) -> tuple[OptimizationRun, list[str]]:
    base_run = await db.get(SimulationRun, payload.base_run_id)
    if base_run is None or base_run.habitation_id != habitation_id:
        raise AppError("BASE_RUN_NOT_FOUND", "Base run not found for this habitation", 404)
    if base_run.status != RunStatus.COMPLETED:
        raise AppError("BASE_RUN_NOT_COMPLETED", "base_run_id must reference a COMPLETED run", 409)

    known = {o.value for o in ObjectiveKind}
    unknown = set(payload.objectives) - known
    if unknown:
        raise AppError("UNKNOWN_OBJECTIVE", f"Unknown objective(s): {', '.join(sorted(unknown))}", 400)
    weight_sum = sum(payload.objectives.values())
    if abs(weight_sum - 1.0) > WEIGHT_TOLERANCE:
        raise AppError(
            "INVALID_OBJECTIVE_WEIGHTS", f"Objective weights must sum to 1.0 +/- 0.001, got {weight_sum}", 400
        )

    habitation = await db.get(Habitation, habitation_id)
    coeff_set = await db.get(CoefficientSet, base_run.coefficient_set_id)
    coeffs = load_coefficients(coeff_set.coefficients)
    params = await materialize_params(db, base_run.parameter_set_id, habitation.habitation_type.value, {})

    decision_space, notes = await build_decision_space(db, habitation_id, params, coeffs, payload.decision_space)

    # max_evaluations has no dedicated column in the design's own
    # optimization_runs schema (section 4.3) — it is a parameter of how the
    # search is run, not a fact about the run's outcome, so it is folded
    # into `constraints` (a scope decision, documented here rather than
    # silently adding an undesigned column).
    constraints = {**payload.constraints, "max_evaluations": payload.max_evaluations}

    run = OptimizationRun(
        habitation_id=habitation_id,
        base_run_id=base_run.id,
        decision_space=decision_space,
        constraints=constraints,
        strategy=payload.strategy,
        status=AnalysisStatus.QUEUED,
        created_by=user.id,
    )
    db.add(run)
    await db.flush()

    for objective, weight in payload.objectives.items():
        db.add(
            OptimizationObjective(
                optimization_id=run.id, objective=ObjectiveKind(objective), weight=weight
            )
        )
    await db.flush()
    return run, notes


def _make_evaluator(
    params: dict[str, Any],
    coeffs: Coefficients,
    coeffs_raw: dict[str, Any],
    months: int,
    discount_rate: float,
    current_coverage: float,
    current_segregation: float,
    weights: dict[str, float],
    basis: dict[str, float],
    constraints: dict[str, Any],
    needs_resilience: bool,
    base_peak_annual_cost: float,
) -> Callable[[dict[str, Any], str], dict[str, Any]]:
    def evaluate(decision_values: dict[str, Any], stage: str) -> dict[str, Any]:
        # discount_rate carried over from the base run so NPV is computed on
        # the same basis as the run being optimized against; capex_policy
        # forced to NONE regardless of what the base run used — a candidate
        # plan's add_vehicles/add_treatment_capacity_tpd already say what
        # gets bought, so the AUTO policy's own reactive buying would double
        # up with it.
        config = {
            "discount_rate": discount_rate,
            "capex_policy": "NONE",
            **scoring.plan_config(decision_values, current_coverage, current_segregation),
        }
        result = engine_run(params, events=[], coeffs_raw=coeffs_raw, months=months, config=config)
        plan_capex = scoring.plan_capex_inr(decision_values, coeffs)

        resilience_raw = None
        if needs_resilience:
            stressed = engine_run(
                params, events=scoring.STANDARD_STRESS_EVENTS, coeffs_raw=coeffs_raw, months=months, config=config
            )
            resilience_raw = scoring.resilience_raw_value(stressed)

        raw_values = scoring.raw_objective_values(result, plan_capex, discount_rate, resilience_raw)
        normalised = {obj: scoring.normalize_objective(obj, raw_values[obj], basis[obj]) for obj in weights}
        score = scoring.weighted_score(normalised, weights)
        violated = scoring.check_constraints(
            decision_values, plan_capex, result, params, constraints, base_peak_annual_cost
        )

        return {
            "decision_values": decision_values,
            "stage": stage,
            "feasible": len(violated) == 0,
            "violated_constraints": violated,
            "objective_values": {k: round(v, 4) for k, v in raw_values.items()},
            "normalised_values": {k: round(v, 6) for k, v in normalised.items()},
            "score": round(score, 6),
            "capex_total_inr": round(plan_capex, 2),
            "_monthly": result["monthly"],
            "_yearly": result["yearly"],
        }

    return evaluate


async def run_search(db: AsyncSession, optimization_run: OptimizationRun) -> None:
    optimization_run.status = AnalysisStatus.RUNNING
    await db.flush()

    base_run = await db.get(SimulationRun, optimization_run.base_run_id)
    habitation = await db.get(Habitation, optimization_run.habitation_id)
    coeff_set = await db.get(CoefficientSet, base_run.coefficient_set_id)
    coeffs = load_coefficients(coeff_set.coefficients)
    params = await materialize_params(db, base_run.parameter_set_id, habitation.habitation_type.value, {})
    months = base_run.horizon_years * 12
    discount_rate = float(base_run.config.get("discount_rate", coeffs["discount_rate"]))

    community = params["community_infrastructure"]
    cultural = params["cultural_context"]
    current_coverage = float(community.get("collection_coverage_pct") or 0.0)
    current_segregation = float(cultural.get("segregation_practice_pct") or 0.0)

    objectives = list(
        await db.scalars(
            select(OptimizationObjective).where(OptimizationObjective.optimization_id == optimization_run.id)
        )
    )
    weights = {obj.objective.value: float(obj.weight) for obj in objectives}
    needs_resilience = "MAX_RESILIENCE" in weights

    base_yearly = await get_yearly_results(db, base_run.id)
    basis = {
        "MIN_COST": sum(float(y.discounted_cost_inr) for y in base_yearly),
        "MIN_LANDFILL": sum(float(y.landfilled_tpy) for y in base_yearly),
        "MAX_COVERAGE": (
            sum(float(y.avg_coverage_pct) for y in base_yearly) / len(base_yearly) if base_yearly else 0.0
        ),
        "MAX_RECOVERY": float(base_yearly[-1].recovery_rate_pct) if base_yearly else 0.0,
        "MIN_GHG": sum(float(y.ghg_tco2e) for y in base_yearly),
    }
    base_peak_annual_cost = max((float(y.total_cost_inr) for y in base_yearly), default=0.0)
    if needs_resilience:
        do_nothing_config = {
            "discount_rate": discount_rate,
            "capex_policy": "NONE",
            **scoring.plan_config(
                _do_nothing_values(current_coverage, current_segregation), current_coverage, current_segregation
            ),
        }
        stressed_base = engine_run(
            params,
            events=scoring.STANDARD_STRESS_EVENTS,
            coeffs_raw=coeff_set.coefficients,
            months=months,
            config=do_nothing_config,
        )
        basis["MAX_RESILIENCE"] = scoring.resilience_raw_value(stressed_base)

    for obj in objectives:
        obj.normalisation_basis = basis[obj.objective.value]
    await db.flush()

    evaluate = _make_evaluator(
        params, coeffs, coeff_set.coefficients, months, discount_rate,
        current_coverage, current_segregation, weights, basis, optimization_run.constraints, needs_resilience,
        base_peak_annual_cost,
    )

    lp_context = None
    if optimization_run.strategy == OptStrategy.STAGED_SEARCH:
        lp_context = {
            "base_capacity": float(community.get("treatment_capacity_tpd") or 0.0),
            "base_landfill_remaining": float(
                community.get("landfill_remaining_tonnes") or community.get("landfill_capacity_tonnes") or 0.0
            ),
            "enforce_no_overflow": bool(optimization_run.constraints.get("no_landfill_overflow")),
            "treatment_capex_per_tpd": float(coeffs["treatment_capex_per_tpd"]),
            "landfill_capex_per_tonne": float(coeffs["landfill_capex_per_tonne"]),
        }

    max_evaluations = int(optimization_run.constraints.get("max_evaluations", 400))
    # Deterministic per optimization_id (BR-20's spirit applied to the
    # search too) so re-running the same request is reproducible.
    seed = optimization_run.id.int % (2**32)

    # Always evaluate the do-nothing plan itself as a guaranteed candidate
    # (T-53: "best candidate scores at least as well as the do-nothing
    # candidate") — not left to chance whether the sampler happens to land
    # near the decision space's own lower-bound corner.
    do_nothing = evaluate(_do_nothing_values(current_coverage, current_segregation), "SAMPLING")
    candidates = [do_nothing] + search.run_staged_search(
        optimization_run.decision_space, max(1, max_evaluations - 1), evaluate, seed, lp_context
    )

    for index, candidate in enumerate(candidates):
        candidate["index"] = index
    pareto_indices = scoring.compute_pareto_front(candidates)

    rows: list[OptimizationCandidate] = []
    for candidate in candidates:
        row = OptimizationCandidate(
            optimization_id=optimization_run.id,
            stage=OptStage(candidate["stage"]),
            decision_values=candidate["decision_values"],
            feasible=candidate["feasible"],
            violated_constraints=candidate["violated_constraints"],
            objective_values=candidate["objective_values"],
            normalised_values=candidate["normalised_values"],
            score=candidate["score"],
            is_pareto=candidate["index"] in pareto_indices,
            capex_total_inr=candidate["capex_total_inr"],
        )
        db.add(row)
        rows.append(row)
    await db.flush()

    optimization_run.candidates_evaluated = len(candidates)

    feasible_rows = [(c, r) for c, r in zip(candidates, rows) if c["feasible"]]
    if feasible_rows:
        best_candidate, best_row = max(feasible_rows, key=lambda pair: pair[0]["score"])
        optimization_run.best_candidate_id = best_row.id
        optimization_run.status = AnalysisStatus.COMPLETED
    else:
        violated_counts = Counter(v for c in candidates for v in c["violated_constraints"])
        binding = violated_counts.most_common(1)[0][0] if violated_counts else "UNKNOWN"
        optimization_run.status = AnalysisStatus.FAILED
        optimization_run.infeasible_reason = (
            f"No candidate satisfied every constraint; the most frequently binding one was {binding} (BR-25)."
        )

    optimization_run.completed_at = datetime.now(timezone.utc)
    await db.flush()


async def get_optimization_or_404(db: AsyncSession, optimization_id: uuid.UUID) -> OptimizationRun:
    run = await db.get(OptimizationRun, optimization_id)
    if run is None:
        raise AppError("OPTIMIZATION_NOT_FOUND", "Optimization run not found", 404)
    return run


async def list_candidates(
    db: AsyncSession, optimization_id: uuid.UUID, feasible_only: bool = False, sort_by_score: bool = False
) -> list[OptimizationCandidate]:
    stmt = select(OptimizationCandidate).where(OptimizationCandidate.optimization_id == optimization_id)
    if feasible_only:
        stmt = stmt.where(OptimizationCandidate.feasible.is_(True))
    if sort_by_score:
        stmt = stmt.order_by(OptimizationCandidate.score.desc())
    else:
        stmt = stmt.order_by(OptimizationCandidate.id)
    return list(await db.scalars(stmt))


async def get_pareto_front(db: AsyncSession, optimization_id: uuid.UUID) -> list[OptimizationCandidate]:
    stmt = (
        select(OptimizationCandidate)
        .where(OptimizationCandidate.optimization_id == optimization_id, OptimizationCandidate.is_pareto.is_(True))
        .order_by(OptimizationCandidate.score.desc())
    )
    return list(await db.scalars(stmt))


async def promote_candidate(
    db: AsyncSession, optimization_run: OptimizationRun, candidate_id: int | None, user: User
) -> SimulationRun:
    if optimization_run.status != AnalysisStatus.COMPLETED:
        raise AppError("OPTIMIZATION_NOT_COMPLETED", "Optimization has no completed search to promote from", 409)

    target_id = candidate_id if candidate_id is not None else optimization_run.best_candidate_id
    if target_id is None:
        raise AppError("CANDIDATE_NOT_FOUND", "No candidate to promote", 404)
    candidate = await db.get(OptimizationCandidate, target_id)
    if candidate is None or candidate.optimization_id != optimization_run.id:
        raise AppError("CANDIDATE_NOT_FOUND", "Candidate not found for this optimization", 404)
    if not candidate.feasible:
        raise AppError("CANDIDATE_NOT_FEASIBLE", "Cannot promote an infeasible candidate", 409)

    base_run = await db.get(SimulationRun, optimization_run.base_run_id)
    habitation = await db.get(Habitation, optimization_run.habitation_id)
    params = await materialize_params(db, base_run.parameter_set_id, habitation.habitation_type.value, {})
    community = params["community_infrastructure"]
    cultural = params["cultural_context"]
    current_coverage = float(community.get("collection_coverage_pct") or 0.0)
    current_segregation = float(cultural.get("segregation_practice_pct") or 0.0)

    config = {
        **base_run.config,
        "capex_policy": "NONE",
        **scoring.plan_config(candidate.decision_values, current_coverage, current_segregation),
    }

    new_run = SimulationRun(
        habitation_id=optimization_run.habitation_id,
        parameter_set_id=base_run.parameter_set_id,
        coefficient_set_id=base_run.coefficient_set_id,
        engine_version=base_run.engine_version,
        run_type=RunType.OPTIMIZED,
        parent_run_id=base_run.id,
        label=f"Optimized plan (candidate {candidate.id})",
        horizon_years=base_run.horizon_years,
        config=config,
        status=RunStatus.QUEUED,
        created_by=user.id,
    )
    db.add(new_run)
    await db.flush()
    optimization_run.promoted_run_id = new_run.id
    await db.flush()
    return new_run


async def build_explanation(db: AsyncSession, optimization_run: OptimizationRun) -> dict[str, Any]:
    if optimization_run.best_candidate_id is None:
        raise AppError("OPTIMIZATION_NOT_COMPLETED", "No best candidate to explain", 409)
    winner = await db.get(OptimizationCandidate, optimization_run.best_candidate_id)

    base_run = await db.get(SimulationRun, optimization_run.base_run_id)
    habitation = await db.get(Habitation, optimization_run.habitation_id)
    coeff_set = await db.get(CoefficientSet, base_run.coefficient_set_id)
    coeffs = load_coefficients(coeff_set.coefficients)
    params = await materialize_params(db, base_run.parameter_set_id, habitation.habitation_type.value, {})
    months = base_run.horizon_years * 12
    discount_rate = float(base_run.config.get("discount_rate", coeffs["discount_rate"]))
    community = params["community_infrastructure"]
    cultural = params["cultural_context"]
    current_coverage = float(community.get("collection_coverage_pct") or 0.0)
    current_segregation = float(cultural.get("segregation_practice_pct") or 0.0)

    objectives = list(
        await db.scalars(
            select(OptimizationObjective).where(OptimizationObjective.optimization_id == optimization_run.id)
        )
    )
    weights = {obj.objective.value: float(obj.weight) for obj in objectives}
    basis = {obj.objective.value: float(obj.normalisation_basis) for obj in objectives}
    needs_resilience = "MAX_RESILIENCE" in weights

    base_yearly = await get_yearly_results(db, base_run.id)
    base_peak_annual_cost = max((float(y.total_cost_inr) for y in base_yearly), default=0.0)

    evaluate = _make_evaluator(
        params, coeffs, coeff_set.coefficients, months, discount_rate,
        current_coverage, current_segregation, weights, basis, optimization_run.constraints, needs_resilience,
        base_peak_annual_cost,
    )

    winner_record = {"decision_values": winner.decision_values, "score": float(winner.score)}
    do_nothing = _do_nothing_values(current_coverage, current_segregation)
    counterfactuals = {}
    for name in DECISION_VARIABLES:
        if winner.decision_values[name] == do_nothing[name]:
            continue  # this lever was never actually used, so "removing" it changes nothing
        reverted = {**winner.decision_values, name: do_nothing[name]}
        counterfactuals[name] = evaluate(reverted, "SAMPLING")
    contributions = explain.variable_contributions(winner_record, counterfactuals)

    all_candidates = await list_candidates(db, optimization_run.id, sort_by_score=True)
    ranked = [c for c in all_candidates if c.id != winner.id and c.feasible]
    near_best_infeasible = [
        {"violated_constraints": c.violated_constraints} for c in all_candidates if not c.feasible
    ][:10]
    binding = explain.binding_constraint(near_best_infeasible)
    next_best = ranked[0] if ranked else None
    marginal = explain.marginal_vs_next_best(
        {"decision_values": winner.decision_values, "score": float(winner.score)},
        {"decision_values": next_best.decision_values, "score": float(next_best.score)} if next_best else None,
    )

    base_yearly = await get_yearly_results(db, base_run.id)
    base_cost = sum(float(y.discounted_cost_inr) for y in base_yearly)
    base_landfill = sum(float(y.landfilled_tpy) for y in base_yearly)
    cost_per_tonne = explain.cost_per_tonne_diverted(
        winner.objective_values["MIN_COST"], base_cost, winner.objective_values["MIN_LANDFILL"], base_landfill
    )

    return {
        "candidate_id": winner.id,
        "decision_values": winner.decision_values,
        "score": float(winner.score),
        "variable_contributions": contributions,
        "binding_constraint": binding,
        "cost_per_tonne_diverted_inr": cost_per_tonne,
        "marginal_vs_next_best": marginal,
        "disclaimer": "Best found under this search budget, not a claim of global optimality (BR-25).",
    }
