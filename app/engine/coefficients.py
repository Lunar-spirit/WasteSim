"""Typed access to a coefficient_sets.coefficients JSONB blob. Every key the
engine reads is listed here with a default so a missing key never causes a
silent zero — it either falls back to a documented default or raises a
KeyError naming exactly what is missing (never a bare `KeyError: 'x'`).

Design decisions where the equations in section 5.4 reference an input this
project's actual parameter schema does not carry, made explicit here rather
than silently invented inline:

  - `k_school/k_hospital/k_market` (bulk generators) assume counts of
    schools/hospitals/markets that community_infrastructure does not store.
    Replaced with `bulk_waste_pct_of_domestic`: bulk waste is modelled as a
    coefficient-driven share of domestic waste instead.
  - `terrain_efficiency[terrain_type]` assumes a categorical PLAIN/HILLY/
    COASTAL terrain_type; the terrain category only has `avg_slope_pct`.
    Replaced with a continuous `terrain_slope_penalty_per_pct` applied to
    the habitation's own slope value.
  - `alley_factor * narrow_alley_pct`: no alley-density input exists in the
    schema at all; this term is omitted (equivalent to alley_penalty = 1).
  - `festival_months` / the timing and intensity of the population and
    waste surge is a coefficient-set calendar, scaled by the habitation's
    own `cultural_context.festival_days_count` as an intensity multiplier
    (0 festival days -> no surge, however many months the calendar names).

None of this changes what the seven categories mean; it only maps design
english for inputs the schema does not have onto coefficients calibrated
once for everyone, exactly like `q_ceiling` or `mrf_efficiency` already are.
"""

from __future__ import annotations

from typing import Any


class CoefficientError(KeyError):
    def __init__(self, key: str) -> None:
        super().__init__(f"coefficient set is missing required key '{key}' and has no default")
        self.key = key


# key -> default. `None` default means the key is genuinely required — the
# calibration is meaningless without an explicit choice for it.
_DEFAULTS: dict[str, Any] = {
    # --- Step 2: per-capita generation ---
    "elasticity_income": 0.3,
    "q_ceiling": {"VILLAGE": 0.9, "WARD": 1.1, "TOWN": 1.3, "CITY": 1.6},  # kg/person/day
    # --- Step 3: total generation ---
    "bulk_waste_pct_of_domestic": 0.08,
    "industrial_growth_rate": 0.03,  # annual
    "monsoon_months": [6, 7, 8, 9],
    "monsoon_wet_uplift_base": 0.06,
    "reference_rainfall_mm": 3000.0,
    "festival_months": [10, 11],
    "festival_waste_multiplier": 1.15,
    "festival_population_surge_pct": 5.0,
    "festival_intensity_reference_days": 10.0,
    # --- Step 4: composition drift ---
    "composition_drift_rate": 0.5,  # pct-points shifted per 100% of annual economic growth, per year
    # --- Step 5: collection ---
    "terrain_slope_penalty_per_pct": 0.006,  # each +1% avg slope costs 0.6% accessibility
    # --- Step 6: segregation and recovery ---
    "segregation_ceiling_pct": 90.0,
    "mrf_efficiency": 0.65,
    "informal_recovery_uplift": 0.10,
    # --- Step 7: treatment ---
    "compost_yield": 0.55,
    "compost_reject_rate": 0.08,
    # --- Step 9: fleet ---
    "avg_vehicle_capacity_tonnes": 5.0,
    "trips_per_vehicle_day": 2.0,
    "fleet_availability": 0.85,
    # A transfer station shortens the round trip to disposal, so each vehicle
    # manages more trips/day. Design 5.6 names the effect ("improves effective
    # trips per vehicle per day") without a magnitude — this figure is a
    # scope decision, not a design value.
    "transfer_station_trip_uplift_pct": 15.0,
    # --- Step 10: cost ---
    "cost_collection_per_tonne": 450.0,
    "cost_treatment_per_tonne": 900.0,
    "cost_disposal_per_tonne": 300.0,
    "vehicle_monthly_opex": 45_000.0,
    "admin_overhead_pct": 0.10,
    "inflation_rate": 0.05,
    "vehicle_capex": 3_500_000.0,
    "treatment_capex_per_tpd": 1_200_000.0,
    "landfill_capex_per_tonne": 450.0,
    "transfer_station_capex": 8_000_000.0,
    # --- Step 11: environment ---
    "ch4_factor_tco2e_per_tonne": 0.55,
    "compost_avoided_tco2e_per_tonne": 0.15,
    "recycling_avoided_tco2e_per_tonne": 0.85,
    # --- Run-level default, overridable via simulation_runs.config ---
    "discount_rate": 0.08,
}


class Coefficients:
    """Wraps the raw dict from coefficient_sets.coefficients. `coeffs["x"]`
    (or `coeffs.get("x")`) reads a value, falling back to `_DEFAULTS` when
    the calibration row doesn't set it, and raising CoefficientError for a
    key that has neither an override nor a default."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    def __getitem__(self, key: str) -> Any:
        if key in self._raw:
            return self._raw[key]
        if key in _DEFAULTS:
            return _DEFAULTS[key]
        raise CoefficientError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self._raw.get(key, _DEFAULTS.get(key, default))


def load(raw: dict[str, Any]) -> Coefficients:
    return Coefficients(raw)


def default_values() -> dict[str, Any]:
    """A plain copy of every built-in default — what app/simulation/service.py
    seeds coefficient_sets with the first time a run is requested and no
    default calibration exists yet (see that module for why this can't
    simply be an Alembic data migration: coefficient_sets.created_by is a
    NOT NULL FK to users, and no user exists yet at migration time)."""
    return dict(_DEFAULTS)
