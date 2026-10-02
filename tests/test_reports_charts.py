"""app/reports/svg.py — pure SVG-string generation, no DB/network needed."""

from app.reports import svg


def test_trajectory_chart_svg_includes_milestone_marker():
    yearly = [
        {"year_index": i, "waste_total_tpy": 1000 + i * 10, "landfilled_tpy": 200, "recovery_rate_pct": 30 + i}
        for i in range(1, 6)
    ]
    findings = [{"code": "LANDFILL_EXHAUSTION_YEAR", "year_index": 3}]
    result = svg.trajectory_chart_svg(yearly, findings)
    assert result.startswith("<svg")
    assert "Landfill exhausted" in result
    assert "polyline" in result


def test_trajectory_chart_svg_handles_empty_series():
    result = svg.trajectory_chart_svg([], [])
    assert result.startswith("<svg")
    assert "No yearly results" in result


def test_composition_donut_svg_renders_a_slice_per_nonzero_fraction():
    composition = {"organic": 55.0, "plastic": 20.0, "paper": 0.0, "metal": 25.0}
    result = svg.composition_donut_svg(composition)
    assert result.count("<path") == 3  # paper is 0, excluded
    assert "organic 55%" in result


def test_composition_donut_svg_handles_all_zero():
    result = svg.composition_donut_svg({"organic": 0.0})
    assert "No composition data" in result


def test_cost_curve_svg_draws_two_bars_per_year():
    yearly = [{"year_index": i, "capex_inr": 10_000, "opex_inr": 5_000} for i in range(1, 4)]
    result = svg.cost_curve_svg(yearly)
    # 2 series x 3 years of bars, plus 2 legend swatches.
    assert result.count("<rect") == 8
    assert "#0ea5e9" in result and "#f59e0b" in result


def test_masked_chart_svg_shows_lock_message():
    result = svg.masked_chart_svg(640, 280)
    assert "Researcher Access Required" in result
