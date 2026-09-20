"""One month of arithmetic. No I/O, no randomness, no imports from app/ —
only app.engine.* and the standard library. `step()` is called 240 times by
run.py; every one of the eleven parts below is a literal translation of
design document section 5.4, with the substitutions documented in
coefficients.py's module docstring where this project's actual parameter
schema doesn't carry a field the design's prose names.
"""

from __future__ import annotations

import math
from typing import Any

from app.engine.coefficients import Coefficients
from app.engine.events import (
    accessibility_multiplier,
    active_event_codes,
    capacity_delta_tpd,
    coverage_delta_pct,
    population_surge_multiplier,
)
from app.engine.state import State

_DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def calendar_month_of(month: int) -> int:
    """Month 1 of a run is always treated as January — a run has no real
    calendar start date, only a deterministic one (BR-20)."""
    return ((month - 1) % 12) + 1


def days_in_calendar_month(calendar_month: int) -> int:
    return _DAYS_IN_MONTH[calendar_month - 1]


def _renormalize_to_100(composition: dict[str, float]) -> dict[str, float]:
    total = sum(composition.values())
    if total <= 0:
        return composition
    return {k: v * 100.0 / total for k, v in composition.items()}


def step(
    state: State,
    params: dict[str, Any],
    coeffs: Coefficients,
    active_events: list[dict[str, Any]],
    month: int,
    config: dict[str, Any] | None = None,
) -> tuple[State, dict[str, Any]]:
    config = config or {}
    demography = params["demography"]
    community = params["community_infrastructure"]
    industrial = params["industrial_activities"]
    natural = params["natural_resources"]
    terrain = params["terrain"]
    economic = params["economic_conditions"]
    cultural = params["cultural_context"]
    habitation_type = params.get("habitation_type", "VILLAGE")

    calendar_month = calendar_month_of(month)
    days = days_in_calendar_month(calendar_month)
    is_festival_month = calendar_month in coeffs["festival_months"]
    festival_intensity = min(
        1.0, float(cultural.get("festival_days_count") or 0) / coeffs["festival_intensity_reference_days"]
    )

    # ---- Part 1: Population ------------------------------------------
    annual_growth_pct = float(demography.get("annual_growth_rate_pct") or 0.0)
    r_month = (1 + annual_growth_pct / 100.0) ** (1 / 12) - 1
    population = state.population * (1 + r_month)
    floating = population * float(demography.get("floating_population_pct") or 0.0) / 100.0
    surge = (
        population * coeffs["festival_population_surge_pct"] / 100.0 * festival_intensity
        if is_festival_month
        else 0.0
    )
    population_effective = (population + floating + surge) * population_surge_multiplier(active_events)

    # ---- Part 2: Per-capita generation --------------------------------
    income_growth_pct = float(
        economic.get("annual_income_growth_rate_pct")
        if economic.get("annual_income_growth_rate_pct") is not None
        else coeffs.get("default_income_growth_rate_pct", 4.0)
    )
    per_capita = state.per_capita_kg_day * (1 + coeffs["elasticity_income"] * (income_growth_pct / 100.0) / 12)
    q_ceiling = coeffs["q_ceiling"].get(habitation_type, coeffs["q_ceiling"]["VILLAGE"])
    per_capita = min(per_capita, q_ceiling)

    # ---- Part 3: Total generation --------------------------------------
    waste_domestic = population_effective * per_capita / 1000.0  # tonnes/day
    waste_bulk = waste_domestic * coeffs["bulk_waste_pct_of_domestic"]
    industrial_base = float(industrial.get("industrial_waste_tpd") or 0.0)
    waste_industrial = industrial_base * (1 + coeffs["industrial_growth_rate"]) ** (month / 12)

    monsoon_factor = 1.0
    if calendar_month in coeffs["monsoon_months"]:
        rainfall = float(natural.get("annual_rainfall_mm") or coeffs["reference_rainfall_mm"])
        monsoon_factor = 1 + coeffs["monsoon_wet_uplift_base"] * (rainfall / coeffs["reference_rainfall_mm"])
    festival_factor = coeffs["festival_waste_multiplier"] if is_festival_month else 1.0
    # Festival intensity scales how much of the multiplier actually applies
    # (a habitation with festival_days_count=0 gets no waste surge even in
    # a nominally festive month).
    festival_factor = 1.0 + (festival_factor - 1.0) * festival_intensity

    waste_total = (waste_domestic + waste_bulk + waste_industrial) * monsoon_factor * festival_factor

    # ---- Part 4: Composition drift --------------------------------------
    drift = coeffs["composition_drift_rate"] * (income_growth_pct / 100.0) / 12
    composition = dict(state.composition)
    composition["organic"] -= drift
    composition["plastic"] += drift * 0.55
    composition["paper"] += drift * 0.35
    composition["other"] += drift * 0.10
    composition = {k: max(0.0, v) for k, v in composition.items()}
    composition = _renormalize_to_100(composition)

    # ---- Part 5: Collection ----------------------------------------------
    slope_pct = float(terrain.get("avg_slope_pct") or 0.0)
    terrain_factor = max(0.5, 1.0 - coeffs["terrain_slope_penalty_per_pct"] * slope_pct)
    event_accessibility = accessibility_multiplier(active_events)
    accessibility = terrain_factor * event_accessibility

    base_coverage = float(community.get("collection_coverage_pct") or 0.0)
    coverage = base_coverage + coverage_delta_pct(active_events) + config.get("coverage_ramp_pct", 0.0)
    coverage = max(0.0, min(100.0, coverage))

    waste_collected = waste_total * (coverage / 100.0) * accessibility
    waste_uncollected = waste_total - waste_collected

    # ---- Part 6: Segregation and recovery --------------------------------
    seg_ceiling = coeffs["segregation_ceiling_pct"]
    segregation = float(cultural.get("segregation_practice_pct") or 0.0) + config.get("segregation_campaign_pct", 0.0)
    segregation = max(0.0, min(seg_ceiling, segregation))

    organic_seg = waste_collected * (composition["organic"] / 100.0) * (segregation / 100.0)
    dry_share = (composition["plastic"] + composition["paper"] + composition["metal"] + composition["glass"]) / 100.0
    dry_available = waste_collected * dry_share * (segregation / 100.0)

    informal_by_type = coeffs.get(
        "informal_recycling_present_by_type", {"VILLAGE": True, "WARD": True, "TOWN": False, "CITY": False}
    )
    informal_bonus = coeffs["informal_recovery_uplift"] if informal_by_type.get(habitation_type, False) else 0.0
    dry_recovered = dry_available * min(1.0, coeffs["mrf_efficiency"] + informal_bonus)

    # ---- Part 7: Treatment ------------------------------------------------
    base_capacity = float(community.get("treatment_capacity_tpd") or 0.0)
    capacity = max(0.0, base_capacity + state.capacity_added_cumulative - capacity_delta_tpd(active_events))
    organic_treated = min(organic_seg, capacity)
    treatment_rejects = organic_treated * coeffs["compost_reject_rate"]
    compost_output = organic_treated * coeffs["compost_yield"]
    mrf_rejects = dry_available - dry_recovered
    utilization_pct = (100.0 * organic_treated / capacity) if capacity > 0 else 0.0

    # ---- Part 8: Disposal and landfill -------------------------------------
    to_landfill = waste_collected - organic_treated - dry_recovered + treatment_rejects + mrf_rejects
    to_landfill = max(0.0, to_landfill)
    landfill_cumulative = state.landfill_cumulative_tonnes + to_landfill * days
    landfill_remaining = state.landfill_remaining_tonnes - to_landfill * days
    exhaustion_month = state.exhaustion_month
    if landfill_remaining <= 0 and exhaustion_month is None:
        exhaustion_month = month

    # ---- Part 9: Fleet ------------------------------------------------------
    transfer_stations = int(config.get("plan_transfer_stations", 0))
    trips_per_vehicle_day = coeffs["trips_per_vehicle_day"] * (
        1.0 + coeffs["transfer_station_trip_uplift_pct"] / 100.0 * transfer_stations
    )
    trips_needed = waste_collected / coeffs["avg_vehicle_capacity_tonnes"] if coeffs["avg_vehicle_capacity_tonnes"] else 0.0
    vehicles_needed = math.ceil(trips_needed / (trips_per_vehicle_day * coeffs["fleet_availability"])) if trips_needed > 0 else 0
    vehicles_have = int(community.get("collection_vehicles_count") or 0) + state.vehicles_added_cumulative
    shortfall = max(0, vehicles_needed - vehicles_have)

    # --- AUTO capex policy: buy the shortfall immediately; expand capacity
    # after 6 straight months over 90% utilisation. NONE (a BASE run) skips
    # this entirely, so added_* stays 0 and the shortfall is real and visible.
    capex_policy = config.get("capex_policy", "NONE")
    vehicles_added_this_month = 0
    capacity_added_this_month = 0.0
    utilization_streak = state.utilization_streak_months
    if capex_policy == "AUTO":
        if shortfall > 0:
            vehicles_added_this_month = shortfall
        utilization_streak = utilization_streak + 1 if utilization_pct >= 90 else 0
        if utilization_streak >= 6:
            capacity_added_this_month = base_capacity * 0.20
            utilization_streak = 0

    # ---- Part 10: Cost --------------------------------------------------
    opex = (
        waste_collected * days * coeffs["cost_collection_per_tonne"]
        + organic_treated * days * coeffs["cost_treatment_per_tonne"]
        + to_landfill * days * coeffs["cost_disposal_per_tonne"]
        + vehicles_have * coeffs["vehicle_monthly_opex"]
    )
    opex *= 1 + coeffs["admin_overhead_pct"]
    opex *= (1 + coeffs["inflation_rate"]) ** (month / 12)

    capex = (
        vehicles_added_this_month * coeffs["vehicle_capex"]
        + capacity_added_this_month * coeffs["treatment_capex_per_tpd"]
    )

    # ---- Part 11: Environment ---------------------------------------------
    landfill_ch4 = to_landfill * (composition["organic"] / 100.0) * coeffs["ch4_factor_tco2e_per_tonne"] * days
    avoided_compost = organic_treated * coeffs["compost_avoided_tco2e_per_tonne"] * days
    avoided_recyc = dry_recovered * coeffs["recycling_avoided_tco2e_per_tonne"] * days
    ghg_net = landfill_ch4 - avoided_compost - avoided_recyc

    new_state = State(
        population=population,
        per_capita_kg_day=per_capita,
        composition=composition,
        landfill_cumulative_tonnes=landfill_cumulative,
        landfill_remaining_tonnes=landfill_remaining,
        exhaustion_month=exhaustion_month,
        vehicles_added_cumulative=state.vehicles_added_cumulative + vehicles_added_this_month,
        capacity_added_cumulative=state.capacity_added_cumulative + capacity_added_this_month,
        utilization_streak_months=utilization_streak,
        capacity_added_this_month=capacity_added_this_month,
        vehicles_added_this_month=vehicles_added_this_month,
    )

    snapshot = {
        "month_index": month,
        "year_index": (month - 1) // 12 + 1,
        "calendar_month": calendar_month,
        "days_in_month": days,
        "population": round(population),
        "population_effective": round(population_effective),
        "per_capita_kg_day": per_capita,
        "waste_domestic_tpd": waste_domestic,
        "waste_bulk_tpd": waste_bulk,
        "waste_industrial_tpd": waste_industrial,
        "waste_total_tpd": waste_total,
        "composition": dict(composition),
        "collection_coverage_pct": coverage,
        "accessibility_index": accessibility,
        "waste_collected_tpd": waste_collected,
        "waste_uncollected_tpd": waste_uncollected,
        "segregation_pct": segregation,
        # Not a simulation_results column — pre-capacity-cap organic load,
        # carried only so app/optimization/search.py's LP polish can size
        # add_treatment_capacity_tpd against a real number instead of
        # guessing (once capacity caps it, organic_treated_tpd alone can't
        # tell you how much more capacity would actually help).
        "organic_seg_tpd": organic_seg,
        "organic_treated_tpd": organic_treated,
        "recyclables_recovered_tpd": dry_recovered,
        "compost_output_tpd": compost_output,
        "treatment_capacity_tpd": capacity,
        "treatment_utilization_pct": utilization_pct,
        # Not a simulation_results column — carried only so invariants.py
        # can check "collected == treated + recovered + landfilled - rejects"
        # (design 5.4 mass balance) without recomputing it from scratch.
        "rejects_tpd": treatment_rejects + mrf_rejects,
        "to_landfill_tpd": to_landfill,
        "landfill_cumulative_tonnes": landfill_cumulative,
        "landfill_remaining_tonnes": max(0.0, landfill_remaining),
        "vehicles_required": vehicles_needed,
        "vehicles_have": vehicles_have,
        "vehicle_shortfall": shortfall,
        "opex_inr": opex,
        "capex_inr": capex,
        # Not simulation_results columns — carried only so
        # app/budget/service.py can split capex_inr into FLEET_PURCHASE vs
        # INFRASTRUCTURE budget_lines without re-deriving them from state.
        "vehicles_added_this_month": vehicles_added_this_month,
        "capacity_added_this_month": capacity_added_this_month,
        "ghg_tco2e": ghg_net,
        "active_event_codes": active_event_codes(active_events),
    }
    return new_state, snapshot
