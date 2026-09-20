"""API-72's explanation output (design 5.6): "the contribution of each
decision variable to the score, the binding constraint, the cost per tonne
of waste diverted from landfill, and the marginal comparison against the
next-best candidate." Pure functions only — every number they combine was
already produced by a real engine run or a real candidate record; nothing
here is estimated or invented past that.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def variable_contributions(winner: dict[str, Any], counterfactuals: dict[str, dict[str, Any]]) -> dict[str, float]:
    """`counterfactuals[name]` is the winner's own candidate re-evaluated
    with `name` reset to its baseline (current, unchanged) value and every
    other decision variable left exactly as the winner has it. The
    contribution is how much score is lost by giving that one variable
    back — a real finite-difference, not an estimate."""
    return {
        name: round(winner["score"] - counterfactual["score"], 6)
        for name, counterfactual in counterfactuals.items()
    }


def binding_constraint(near_best_infeasible: list[dict[str, Any]]) -> str | None:
    """Which constraint most often stopped a near-best candidate from being
    feasible — the one actually limiting how much better the search could
    do. None when nothing close to the winner failed a constraint."""
    counts = Counter(v for c in near_best_infeasible for v in c["violated_constraints"])
    return counts.most_common(1)[0][0] if counts else None


def cost_per_tonne_diverted(
    winner_cost_inr: float, base_cost_inr: float, winner_landfill_tonnes: float, base_landfill_tonnes: float
) -> float | None:
    diverted = base_landfill_tonnes - winner_landfill_tonnes
    if diverted <= 0:
        return None
    return round((winner_cost_inr - base_cost_inr) / diverted, 2)


def marginal_vs_next_best(winner: dict[str, Any], next_best: dict[str, Any] | None) -> dict[str, Any] | None:
    if next_best is None:
        return None
    return {
        "next_best_score": next_best["score"],
        "score_margin": round(winner["score"] - next_best["score"], 6),
        "decision_differences": {
            key: {"winner": winner["decision_values"][key], "next_best": next_best["decision_values"][key]}
            for key in winner["decision_values"]
            if winner["decision_values"][key] != next_best["decision_values"][key]
        },
    }
