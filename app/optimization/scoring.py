"""Turning one engine run into an objective vector, normalising it against
the base run, and combining the weighted objectives into a single score
(design 5.6). Also the feasibility check (BR-25) and the Pareto front
(cost vs landfill — the two axes the design's own optimization_candidates
column comment names).

None of this is engine code — app/optimization/ is a caller of app/engine/,
not part of it, so it is free to import from the rest of app/ (rule 8 only
restricts app/engine/ itself).
"""

from __future__ import annotations

from typing import Any

from app.engine.coefficients import Coefficients
from app.engine.costs import discounted

MINIMIZE_OBJECTIVES = frozenset({"MIN_COST", "MIN_LANDFILL", "MIN_GHG"})
MAXIMIZE_OBJECTIVES = frozenset({"MAX_COVERAGE", "MAX_RECOVERY", "MAX_RESILIENCE"})
ALL_OBJECTIVES = MINIMIZE_OBJECTIVES | MAXIMIZE_OBJECTIVES

# MAX_RESILIENCE (design 5.6: "performance under a standard stress
# scenario") needs a fixed disruption to test every candidate against — a
# SEVERE flood early in the horizon, long enough to reveal whether a plan's
# extra fleet/capacity/coverage actually holds up under stress. Declared
# rather than derived from GIS, same as any scenario event with no
# affected_area (BR-23 only applies when one is supplied).
STANDARD_STRESS_EVENTS: list[dict[str, Any]] = [
    {
        "event_type": "FLOOD",
        "start_month": 2,
        "duration_months": 2,
        "recovery_months": 4,
        "severity": "SEVERE",
        "impact_params": {"collection_coverage_pct": -30.0, "road_accessibility_loss": 0.35},
    }
]

# Design 5.6's constraint list includes "annual cost <= annual_swm_budget_inr
# x tolerance" as a standing check (not one the caller has to ask for). The
# multiplier itself is a scope decision — the design names the check, not
# the number.
ANNUAL_BUDGET_TOLERANCE = 1.15


def plan_config(decision_values: dict[str, Any], current_coverage: float, current_segregation: float) -> dict[str, Any]:
    """Translate one candidate's decision_values into the engine's own
    `config` dict. target_coverage_pct/target_segregation_pct become flat
    deltas applied from month 1 — the same config keys app/engine/step.py
    already reads for a manual override, established back in module M8;
    reused here rather than inventing a second ramp mechanism. add_vehicles/
    add_treatment_capacity_tpd/landfill_expansion_tonnes/transfer_stations
    are new config keys read by app/engine/state.py and step.py (added
    alongside this module) as a one-time, month-1 capital investment."""
    return {
        "coverage_ramp_pct": decision_values["target_coverage_pct"] - current_coverage,
        "segregation_campaign_pct": decision_values["target_segregation_pct"] - current_segregation,
        "plan_added_vehicles": decision_values["add_vehicles"],
        "plan_added_treatment_capacity_tpd": decision_values["add_treatment_capacity_tpd"],
        "plan_added_landfill_tonnes": decision_values["landfill_expansion_tonnes"],
        "plan_transfer_stations": decision_values["transfer_stations"],
    }


def plan_capex_inr(decision_values: dict[str, Any], coeffs: Coefficients) -> float:
    """The one-time capex a plan commits — not something step.py's own
    capex_inr line captures, since these levers are injected as a starting
    condition rather than through the AUTO capex policy's monthly
    accounting. Added into MIN_COST's NPV separately, at year 1."""
    return (
        decision_values["add_vehicles"] * coeffs["vehicle_capex"]
        + decision_values["add_treatment_capacity_tpd"] * coeffs["treatment_capex_per_tpd"]
        + decision_values["landfill_expansion_tonnes"] * coeffs["landfill_capex_per_tonne"]
        + decision_values["transfer_stations"] * coeffs["transfer_station_capex"]
    )


def raw_objective_values(
    result: dict[str, Any],
    plan_capex: float,
    discount_rate: float,
    resilience_raw: float | None,
) -> dict[str, float]:
    yearly = result["yearly"]
    values = {
        "MIN_COST": sum(y["discounted_cost_inr"] for y in yearly) + discounted(plan_capex, 1, discount_rate),
        "MIN_LANDFILL": sum(y["landfilled_tpy"] for y in yearly),
        "MAX_COVERAGE": (sum(y["avg_coverage_pct"] for y in yearly) / len(yearly)) if yearly else 0.0,
        "MAX_RECOVERY": yearly[-1]["recovery_rate_pct"] if yearly else 0.0,
        "MIN_GHG": sum(y["ghg_tco2e"] for y in yearly),
    }
    if resilience_raw is not None:
        values["MAX_RESILIENCE"] = resilience_raw
    return values


def resilience_raw_value(stressed_result: dict[str, Any]) -> float:
    monthly = stressed_result["monthly"]
    return sum(m["collection_coverage_pct"] for m in monthly) / len(monthly) if monthly else 0.0


def normalize_objective(objective: str, raw: float, basis: float) -> float:
    """0-1-ish against the base run's own value (design 5.6). The do-nothing
    candidate (decision_values all zero / at their current-value floor)
    reproduces the base run exactly (BR-20 determinism), so raw == basis for
    every objective in that case and normalize_objective always returns
    1.0 — meaning a do-nothing candidate's score is always exactly 1.0
    (weights sum to 1, BR-24), which is what T-53 checks the search against.
    Capped at 3.0 so one near-zero raw value (e.g. a candidate that drives
    landfilling to ~0) can't make a single objective swamp the weighted sum.
    """
    if basis == 0:
        if raw == 0:
            return 1.0
        return 0.0 if objective in MINIMIZE_OBJECTIVES else 3.0
    if objective in MINIMIZE_OBJECTIVES:
        return min(3.0, basis / raw) if raw > 0 else 3.0
    return min(3.0, raw / basis)


def weighted_score(normalised_values: dict[str, float], weights: dict[str, float]) -> float:
    return sum(weights[objective] * normalised_values[objective] for objective in weights)


def check_constraints(
    decision_values: dict[str, Any],
    plan_capex: float,
    result: dict[str, Any],
    params: dict[str, Any],
    constraints: dict[str, Any],
    base_peak_annual_cost: float = 0.0,
) -> list[str]:
    """Returns the list of violated constraint names — empty means
    feasible. Every candidate is scored regardless (design: "every candidate
    — feasible or not — is written to optimization_candidates")."""
    violated: list[str] = []
    yearly = result["yearly"]

    capex_budget = constraints.get("capex_budget_inr")
    if capex_budget is not None and plan_capex > float(capex_budget):
        violated.append("CAPEX_BUDGET")

    min_coverage = constraints.get("min_coverage_pct")
    if min_coverage is not None and yearly:
        mean_coverage = sum(y["avg_coverage_pct"] for y in yearly) / len(yearly)
        if mean_coverage < float(min_coverage):
            violated.append("MIN_COVERAGE")

    if constraints.get("no_landfill_overflow"):
        if any(y["landfill_remaining_tonnes"] <= 0 for y in yearly):
            violated.append("NO_LANDFILL_OVERFLOW")

    annual_budget = params.get("economic_conditions", {}).get("swm_annual_budget")
    if annual_budget:
        # A habitation already over budget in its BASE run (a real, common
        # finding — see BUDGET_BREACH_YEAR) must not become permanently
        # unsearchable: the ceiling is whichever is higher, the tolerance
        # line itself or what the base run already costs. A candidate is
        # only flagged for making the budget picture worse than the status
        # quo, never for merely inheriting it.
        # The tiny *1.0001 slack absorbs float noise between a freshly
        # computed candidate and a persisted Numeric(16,2) base-run value —
        # without it, the do-nothing candidate (which reproduces the base
        # run's own numbers up to rounding) can spuriously fail its own
        # ceiling by a fraction of a rupee (design 5.4.1's own tolerance
        # pattern in app/engine/invariants.py is the same idea).
        ceiling = max(float(annual_budget) * ANNUAL_BUDGET_TOLERANCE, base_peak_annual_cost) * 1.0001
        if any(y["total_cost_inr"] > ceiling for y in yearly):
            violated.append("ANNUAL_BUDGET_TOLERANCE")

    return violated


def compute_pareto_front(candidates: list[dict[str, Any]]) -> set[int]:
    """Non-dominated set on (MIN_COST, MIN_LANDFILL) among feasible
    candidates only (design: optimization_candidates.is_pareto is "on the
    non-dominated front of cost versus landfill"). `candidates` is a list of
    {"index": ..., "feasible": ..., "objective_values": {...}}; returns the
    set of indices on the front."""
    feasible = [c for c in candidates if c["feasible"] and "MIN_COST" in c["objective_values"] and "MIN_LANDFILL" in c["objective_values"]]
    front: set[int] = set()
    for candidate in feasible:
        cost = candidate["objective_values"]["MIN_COST"]
        landfill = candidate["objective_values"]["MIN_LANDFILL"]
        dominated = False
        for other in feasible:
            if other is candidate:
                continue
            other_cost = other["objective_values"]["MIN_COST"]
            other_landfill = other["objective_values"]["MIN_LANDFILL"]
            if other_cost <= cost and other_landfill <= landfill and (other_cost < cost or other_landfill < landfill):
                dominated = True
                break
        if not dominated:
            front.add(candidate["index"])
    return front
