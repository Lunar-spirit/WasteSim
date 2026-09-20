"""The staged search itself (design 5.6, AD-13, PDD-07):

  1. Latin-hypercube sample across the decision space (~75% of the budget).
  2. Hill-climb one variable at a time around the best 10 samples (~25%).
  3. An optional PuLP LP solve that tightens the two continuous "sizing"
     variables (add_treatment_capacity_tpd, landfill_expansion_tonnes)
     around the best candidate found so far, holding everything else fixed.

`evaluate` is injected by the caller (app/optimization/service.py) — this
module has no idea how a candidate's decision_values become an engine run;
it only knows how to explore the space and rank what evaluate() hands back.
Every candidate evaluate() produces (feasible or not) is kept, per design:
"every candidate ... is written to optimization_candidates".
"""

from __future__ import annotations

import random
from typing import Any, Callable

import pulp

from app.optimization.space import INTEGER_VARIABLES

_SAMPLING_SHARE = 0.75
_HILL_CLIMB_SEEDS = 10
_HILL_CLIMB_STEP_FRACTION = 0.1  # each hill-climb move is 10% of a variable's own range

EvaluateFn = Callable[[dict[str, Any], str], dict[str, Any]]


def latin_hypercube_sample(
    bounds: dict[str, list[float]], n: int, rng: random.Random
) -> list[dict[str, Any]]:
    """One sample per stratum per dimension, strata shuffled independently
    per dimension so the n points don't collapse onto a diagonal."""
    if n <= 0:
        return []
    names = list(bounds.keys())
    per_dimension: dict[str, list[float]] = {}
    for name in names:
        lo, hi = bounds[name]
        points = [lo + ((i + rng.random()) / n) * (hi - lo) for i in range(n)]
        rng.shuffle(points)
        per_dimension[name] = points

    samples = []
    for i in range(n):
        values = {}
        for name in names:
            raw = per_dimension[name][i]
            values[name] = round(raw) if name in INTEGER_VARIABLES else round(raw, 3)
        samples.append(values)
    return samples


def _rank_key(candidate: dict[str, Any]) -> tuple[bool, float]:
    return (candidate["feasible"], candidate["score"] if candidate["score"] is not None else float("-inf"))


def _hill_climb(
    seeds: list[dict[str, Any]],
    bounds: dict[str, list[float]],
    budget: int,
    evaluate: EvaluateFn,
) -> list[dict[str, Any]]:
    evaluated: list[dict[str, Any]] = []
    used = 0
    for seed_candidate in seeds:
        if used >= budget:
            break
        current_values = dict(seed_candidate["decision_values"])
        current_best = seed_candidate
        improved = True
        while improved and used < budget:
            improved = False
            for name, (lo, hi) in bounds.items():
                if hi <= lo:
                    continue
                step = (hi - lo) * _HILL_CLIMB_STEP_FRACTION
                for direction in (1, -1):
                    if used >= budget:
                        break
                    trial_value = max(lo, min(hi, current_values[name] + direction * step))
                    trial_value = round(trial_value) if name in INTEGER_VARIABLES else round(trial_value, 3)
                    if trial_value == current_values[name]:
                        continue
                    trial_values = {**current_values, name: trial_value}
                    candidate = evaluate(trial_values, "REFINEMENT")
                    evaluated.append(candidate)
                    used += 1
                    if _rank_key(candidate) > _rank_key(current_best):
                        current_values = trial_values
                        current_best = candidate
                        improved = True
    return evaluated


def _lp_polish_values(
    best: dict[str, Any],
    bounds: dict[str, list[float]],
    base_capacity: float,
    base_landfill_remaining: float,
    enforce_no_overflow: bool,
    treatment_capex_per_tpd: float,
    landfill_capex_per_tonne: float,
) -> dict[str, Any] | None:
    """Cheapest add_treatment_capacity_tpd / landfill_expansion_tonnes that
    (a) keep every month's organic load within capacity and (b) — only when
    the caller asked for no_landfill_overflow — keep the landfill from
    running out by the end of the horizon, given the best candidate's own
    simulated trajectory. Returns None if the LP itself is infeasible (the
    requirement can't be met within the decision space's own bounds) — the
    stage is skipped rather than forced (design: "optional")."""
    monthly = best["_monthly"]
    yearly = best["_yearly"]
    peak_organic_seg = max((m["organic_seg_tpd"] for m in monthly), default=0.0)
    landfill_deficit = 0.0
    if enforce_no_overflow and yearly:
        cumulative_landfilled = sum(y["landfilled_tpy"] for y in yearly)
        landfill_deficit = max(0.0, cumulative_landfilled - base_landfill_remaining)

    cap_lo, cap_hi = bounds["add_treatment_capacity_tpd"]
    land_lo, land_hi = bounds["landfill_expansion_tonnes"]
    cap_requirement = max(cap_lo, peak_organic_seg - base_capacity)
    land_requirement = max(land_lo, landfill_deficit)
    if cap_requirement > cap_hi or land_requirement > land_hi:
        return None  # can't fix this within the search's own decision space

    problem = pulp.LpProblem("optimization_lp_polish", pulp.LpMinimize)
    cap_add = pulp.LpVariable("cap_add", lowBound=cap_requirement, upBound=cap_hi)
    land_add = pulp.LpVariable("land_add", lowBound=land_requirement, upBound=land_hi)
    problem += treatment_capex_per_tpd * cap_add + landfill_capex_per_tonne * land_add
    status = problem.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        return None

    polished = dict(best["decision_values"])
    polished["add_treatment_capacity_tpd"] = round(cap_add.value(), 3)
    polished["landfill_expansion_tonnes"] = round(land_add.value(), 3)
    return polished


def run_staged_search(
    decision_space: dict[str, list[float]],
    max_evaluations: int,
    evaluate: EvaluateFn,
    seed: int,
    lp_polish_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Returns every candidate evaluated across all stages, in the order
    they were produced."""
    rng = random.Random(seed)
    reserve_for_lp = 1 if lp_polish_context is not None else 0
    n_sampling = max(1, round((max_evaluations - reserve_for_lp) * _SAMPLING_SHARE))
    n_refinement = max(0, max_evaluations - n_sampling - reserve_for_lp)

    samples = latin_hypercube_sample(decision_space, n_sampling, rng)
    all_candidates = [evaluate(values, "SAMPLING") for values in samples]

    ranked = sorted(all_candidates, key=_rank_key, reverse=True)
    seeds = ranked[:_HILL_CLIMB_SEEDS]
    all_candidates += _hill_climb(seeds, decision_space, n_refinement, evaluate)

    if lp_polish_context is not None and all_candidates:
        current_best = max(all_candidates, key=_rank_key)
        polished_values = _lp_polish_values(current_best, decision_space, **lp_polish_context)
        if polished_values is not None:
            all_candidates.append(evaluate(polished_values, "LP_POLISH"))

    return all_candidates
