"""The monthly state a `step()` call carries forward. Everything else the
engine needs (the frozen habitation inputs, the coefficient set, this
month's active events) is passed into `step()` fresh each call — only what
must persist between months lives here.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.coefficients import Coefficients

# The design's nine canonical composition fractions (design section 4.3's
# simulation_results has one column per fraction). A habitation's own
# composition JSONB is free-form, so normalize_composition() folds any
# unrecognised key's share into "other" — done once here, at state
# construction, so step.py's drift math can always assume exactly these
# nine keys exist without a .get() on every access.
CANONICAL_FRACTIONS = ("organic", "plastic", "paper", "metal", "glass", "textile", "inert", "ewaste", "other")


def normalize_composition(raw: dict[str, float]) -> dict[str, float]:
    result = dict.fromkeys(CANONICAL_FRACTIONS, 0.0)
    for key, value in raw.items():
        target = key if key in result else "other"
        result[target] += float(value)
    total = sum(result.values())
    if total > 0:
        result = {k: v * 100.0 / total for k, v in result.items()}
    return result


@dataclass
class State:
    population: float
    per_capita_kg_day: float
    # {"organic": 55.0, "plastic": 12.0, ...} — whatever keys the habitation's
    # waste_baseline.composition supplied; drift touches organic/plastic/
    # paper/other by name and renormalises everything else proportionally.
    composition: dict[str, float]
    landfill_cumulative_tonnes: float
    landfill_remaining_tonnes: float
    # Set once, the first month landfill_remaining_tonnes <= 0 (design 5.4.9).
    exhaustion_month: int | None = None
    # AUTO capex policy bookkeeping (config.capex_policy — NONE for a BASE
    # run, so these all stay at their initial value and every added_*()
    # function returns 0, exactly matching "a BASE run does nothing").
    vehicles_added_cumulative: int = 0
    capacity_added_cumulative: float = 0.0
    utilization_streak_months: int = 0
    capacity_added_this_month: float = 0.0
    vehicles_added_this_month: int = 0


def initial_state(params: dict, coeffs: Coefficients) -> State:
    demography = params["demography"]
    community = params["community_infrastructure"]
    baseline = params["waste_baseline"]

    population = float(demography["population"])

    per_capita = baseline.get("per_capita_generation_kg_day")
    if per_capita is None:
        # BR-05: the missing one is derived from the other using population.
        total_tpd = float(baseline["total_generation_tpd"])
        per_capita = (total_tpd * 1000.0) / population if population else 0.0

    composition = normalize_composition(baseline.get("composition") or {"organic": 100.0})

    landfill_capacity = float(community.get("landfill_capacity_tonnes") or 0.0)
    landfill_remaining = community.get("landfill_remaining_tonnes")
    # "Left blank, the engine assumes the landfill starts full" — the exact
    # rule stated in the landfill_remaining_tonnes catalogue help_text.
    landfill_remaining = landfill_capacity if landfill_remaining is None else float(landfill_remaining)

    return State(
        population=population,
        per_capita_kg_day=float(per_capita),
        composition=composition,
        landfill_cumulative_tonnes=0.0,
        landfill_remaining_tonnes=landfill_remaining,
    )
