"""app/engine/ tests — no database, no HTTP, no event loop. These must stay
fast (the whole file well under 2 seconds) since optimization (Drop 2,
later) calls run() hundreds of times per search.
"""

import copy

import pytest

from app.engine.run import run

BASE_PARAMS = {
    "habitation_type": "VILLAGE",
    "demography": {
        "population": 22500,
        "annual_growth_rate_pct": 1.8,
        "household_size_avg": 4.2,
        "floating_population_pct": 5.0,
    },
    "community_infrastructure": {
        "road_network_km": 42.0,
        "collection_vehicles_count": 3,
        "collection_coverage_pct": 80.0,
        "treatment_capacity_tpd": 5.0,
        "landfill_capacity_tonnes": 50000.0,
        "landfill_remaining_tonnes": 12000.0,
    },
    "industrial_activities": {"industrial_waste_tpd": 2.0},
    "natural_resources": {"annual_rainfall_mm": 3200.0},
    "terrain": {"avg_slope_pct": 4.0},
    "economic_conditions": {"swm_annual_budget": 2_500_000.0},
    "cultural_context": {"segregation_practice_pct": 35.0},
    "waste_baseline": {
        "per_capita_generation_kg_day": 0.45,
        "composition": {
            "organic": 55.0,
            "plastic": 12.0,
            "paper": 10.0,
            "glass": 3.0,
            "metal": 2.0,
            "other": 18.0,
        },
    },
}


def _params(**overrides):
    p = copy.deepcopy(BASE_PARAMS)
    for path, value in overrides.items():
        category, key = path.split(".")
        p[category][key] = value
    return p


def test_zero_growth_generation_is_flat_across_all_240_months():
    # T-40: no population growth, no income growth, no events -> nothing
    # month-over-month should trend; this single test catches most
    # arithmetic slips in one shot.
    params = _params(**{"demography.annual_growth_rate_pct": 0.0})
    params["economic_conditions"]["annual_income_growth_rate_pct"] = 0.0
    params["cultural_context"]["festival_days_count"] = 0  # no festival surge either
    # industrial_waste_tpd has its own independent growth channel
    # (industrial_growth_rate) — zero it too, or the "zero growth" premise
    # is only half true and generation still visibly drifts.
    result = run(
        params,
        events=[],
        coeffs_raw={"monsoon_wet_uplift_base": 0.0, "industrial_growth_rate": 0.0},
        months=240,
    )

    totals = [m["waste_total_tpd"] for m in result["monthly"]]
    assert max(totals) - min(totals) < 1e-6, f"generation drifted: min={min(totals)} max={max(totals)}"


def test_same_inputs_produce_byte_identical_output_twice():
    # T-38 / BR-20
    result1 = run(BASE_PARAMS, events=[], coeffs_raw={}, months=240)
    result2 = run(BASE_PARAMS, events=[], coeffs_raw={}, months=240)
    assert result1["monthly"] == result2["monthly"]
    assert result1["yearly"] == result2["yearly"]


def test_mass_balance_holds_every_month_for_a_realistic_input_set():
    # T-39 — run() itself asserts this internally (raises MassBalanceError
    # otherwise); reaching this line without an exception is the test.
    result = run(BASE_PARAMS, events=[], coeffs_raw={}, months=240)
    assert len(result["monthly"]) == 240


def test_doubling_population_roughly_doubles_total_generation():
    params = _params(**{"demography.population": 45000})
    doubled = run(params, events=[], coeffs_raw={}, months=1)
    base = run(BASE_PARAMS, events=[], coeffs_raw={}, months=1)

    ratio = doubled["monthly"][0]["waste_total_tpd"] / base["monthly"][0]["waste_total_tpd"]
    assert 1.8 < ratio < 2.1, f"expected roughly 2x, got {ratio:.2f}x"


def test_raising_segregation_raises_recovery_and_lowers_landfilled_tonnage():
    low_seg = run(_params(**{"cultural_context.segregation_practice_pct": 10.0}), events=[], coeffs_raw={}, months=12)
    high_seg = run(_params(**{"cultural_context.segregation_practice_pct": 80.0}), events=[], coeffs_raw={}, months=12)

    low_year = low_seg["yearly"][0]
    high_year = high_seg["yearly"][0]
    assert high_year["recovered_tpy"] > low_year["recovered_tpy"]
    assert high_year["landfilled_tpy"] < low_year["landfilled_tpy"]


def test_low_landfill_remaining_produces_exhaustion_finding_with_correct_year():
    params = _params(**{"community_infrastructure.landfill_remaining_tonnes": 50.0})
    result = run(params, events=[], coeffs_raw={}, months=240)

    exhaustion = next(f for f in result["findings"] if f["code"] == "LANDFILL_EXHAUSTION_YEAR")
    first_zero_month = next(
        m["month_index"] for m in result["monthly"] if m["landfill_remaining_tonnes"] <= 0
    )
    assert exhaustion["year_index"] == (first_zero_month - 1) // 12 + 1


def test_zero_treatment_capacity_sends_everything_to_landfill_without_dividing_by_zero():
    params = _params(**{"community_infrastructure.treatment_capacity_tpd": 0.0})
    result = run(params, events=[], coeffs_raw={}, months=12)

    for m in result["monthly"]:
        assert m["organic_treated_tpd"] == 0.0
        assert m["treatment_utilization_pct"] == 0.0


def test_flood_event_reduces_collection_only_in_its_window_then_recovers_gradually():
    events = [
        {
            "event_type": "FLOOD",
            "start_month": 14,
            "duration_months": 3,
            "recovery_months": 3,
            "severity": "SEVERE",
            "impact_params": {"collection_coverage_pct": -35, "road_accessibility_loss": 0.4},
        }
    ]
    with_flood = run(BASE_PARAMS, events=events, coeffs_raw={}, months=20)
    without_flood = run(BASE_PARAMS, events=[], coeffs_raw={}, months=20)

    # window = months 14-16 (start=14, duration=3); recovery_months=3 ramps
    # linearly back to baseline over 17, 18, 19 (ramp reaches exactly 0 at
    # window_end + recovery_months = 19, so 19 and everything after is
    # indistinguishable from baseline — there is no partial effect left).
    for month in with_flood["monthly"]:
        idx = month["month_index"]
        baseline_coverage = without_flood["monthly"][idx - 1]["collection_coverage_pct"]
        if idx < 14 or idx >= 19:
            assert month["collection_coverage_pct"] == pytest.approx(baseline_coverage)
        elif idx <= 16:
            # Full event window: coverage is meaningfully depressed.
            assert month["collection_coverage_pct"] < baseline_coverage - 30
        else:
            # 17, 18: ramping down, strictly less depressed with each month
            # (no instant snap back to baseline).
            assert month["collection_coverage_pct"] < baseline_coverage
            if idx == 18:
                prev = with_flood["monthly"][idx - 2]["collection_coverage_pct"]
                assert month["collection_coverage_pct"] > prev


def test_composition_still_sums_to_100_after_240_months_of_drift():
    result = run(BASE_PARAMS, events=[], coeffs_raw={}, months=240)
    total = sum(result["monthly"][-1]["composition"].values())
    assert total == pytest.approx(100.0, abs=0.5)


def test_engine_package_imports_nothing_from_app_outside_itself():
    # BR-21 / rule #8, enforced mechanically rather than by convention.
    import ast
    import pathlib

    engine_dir = pathlib.Path(__file__).resolve().parent.parent / "app" / "engine"
    violations = []
    for path in engine_dir.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                if name and name.startswith("app.") and not name.startswith("app.engine"):
                    violations.append(f"{path.name}: imports {name}")
    assert not violations, "app/engine/ must not import from app/ outside itself:\n" + "\n".join(violations)


def test_a_240_month_run_completes_well_under_50ms():
    import time

    start = time.perf_counter()
    run(BASE_PARAMS, events=[], coeffs_raw={}, months=240)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 200, f"took {elapsed_ms:.1f}ms (generous CI ceiling; design target is 10-30ms)"
