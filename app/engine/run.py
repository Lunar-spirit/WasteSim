"""The 240-step loop (design 5.4.1), yearly aggregation (AD-11) and headline
findings (5.4.13) — the only entry point app/simulation/ calls. Pure
Python: `run()` takes plain dicts and lists in, returns plain dicts out, no
database, no ORM, no un-seeded randomness (BR-20, BR-21).
"""

from __future__ import annotations

from typing import Any

from app.engine.coefficients import load as load_coefficients
from app.engine.events import active_in
from app.engine.invariants import MassBalanceError, check_month
from app.engine.state import initial_state
from app.engine.step import step

ENGINE_VERSION = "1.0.0"
DEFAULT_MONTHS = 240


def run(
    params: dict[str, Any],
    events: list[dict[str, Any]],
    coeffs_raw: dict[str, Any],
    months: int = DEFAULT_MONTHS,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or {}
    coeffs = load_coefficients(coeffs_raw)
    state = initial_state(params, coeffs)

    history: list[dict[str, Any]] = []
    for month in range(1, months + 1):
        active_events = active_in(events, month)
        state, snapshot = step(state, params, coeffs, active_events, month, config)
        check_month(snapshot, month)  # raises MassBalanceError — caller's job to mark the run FAILED
        history.append(snapshot)

    discount_rate = float(config.get("discount_rate", coeffs["discount_rate"]))
    yearly = aggregate_by_year(history, discount_rate)
    findings = derive_findings(history, yearly, params)

    return {"monthly": history, "yearly": yearly, "findings": findings, "engine_version": ENGINE_VERSION}


def aggregate_by_year(history: list[dict[str, Any]], discount_rate: float) -> list[dict[str, Any]]:
    from app.engine.costs import discounted

    years: dict[int, list[dict[str, Any]]] = {}
    for snapshot in history:
        years.setdefault(snapshot["year_index"], []).append(snapshot)

    yearly: list[dict[str, Any]] = []
    for year_index in sorted(years):
        months = years[year_index]
        last = months[-1]

        def sum_tonnes(key: str) -> float:
            return sum(m[key] * m["days_in_month"] for m in months)

        waste_total_tpy = sum_tonnes("waste_total_tpd")
        waste_collected_tpy = sum_tonnes("waste_collected_tpd")
        waste_uncollected_tpy = sum_tonnes("waste_uncollected_tpd")
        treated_tpy = sum_tonnes("organic_treated_tpd")
        recovered_tpy = sum_tonnes("recyclables_recovered_tpd")
        landfilled_tpy = sum_tonnes("to_landfill_tpd")

        opex_inr = sum(m["opex_inr"] for m in months)
        capex_inr = sum(m["capex_inr"] for m in months)
        total_cost_inr = opex_inr + capex_inr

        yearly.append(
            {
                "year_index": year_index,
                "population_end": last["population"],
                "waste_total_tpy": waste_total_tpy,
                "waste_collected_tpy": waste_collected_tpy,
                "waste_uncollected_tpy": waste_uncollected_tpy,
                "treated_tpy": treated_tpy,
                "recovered_tpy": recovered_tpy,
                "landfilled_tpy": landfilled_tpy,
                "landfill_remaining_tonnes": last["landfill_remaining_tonnes"],
                "avg_coverage_pct": sum(m["collection_coverage_pct"] for m in months) / len(months),
                "peak_vehicle_shortfall": max(m["vehicle_shortfall"] for m in months),
                "opex_inr": opex_inr,
                "capex_inr": capex_inr,
                "total_cost_inr": total_cost_inr,
                "discounted_cost_inr": discounted(total_cost_inr, year_index, discount_rate),
                "ghg_tco2e": sum(m["ghg_tco2e"] for m in months),
                "recovery_rate_pct": (
                    (treated_tpy + recovered_tpy) / waste_total_tpy * 100 if waste_total_tpy > 0 else 0.0
                ),
            }
        )
    return yearly


def derive_findings(
    history: list[dict[str, Any]], yearly: list[dict[str, Any]], params: dict[str, Any]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    exhaustion_month = next((m["month_index"] for m in history if m["landfill_remaining_tonnes"] <= 0), None)
    if exhaustion_month is not None:
        year = (exhaustion_month - 1) // 12 + 1
        findings.append(
            {
                "code": "LANDFILL_EXHAUSTION_YEAR",
                "severity": "CRITICAL",
                "numeric_value": year,
                "year_index": year,
                "message": f"Landfill capacity is exhausted in year {year}.",
            }
        )

    shortfall_month = next((m["month_index"] for m in history if m["vehicle_shortfall"] > 0), None)
    if shortfall_month is not None:
        year = (shortfall_month - 1) // 12 + 1
        findings.append(
            {
                "code": "FIRST_VEHICLE_SHORTFALL_YEAR",
                "severity": "WATCH",
                "numeric_value": year,
                "year_index": year,
                "message": f"The collection fleet first falls short of what is needed in year {year}.",
            }
        )

    saturation_month = next((m["month_index"] for m in history if m["treatment_utilization_pct"] >= 100), None)
    if saturation_month is not None:
        year = (saturation_month - 1) // 12 + 1
        findings.append(
            {
                "code": "TREATMENT_SATURATION_YEAR",
                "severity": "WATCH",
                "numeric_value": year,
                "year_index": year,
                "message": f"Treatment capacity is fully saturated in year {year}.",
            }
        )

    npv_total = sum(y["discounted_cost_inr"] for y in yearly)
    findings.append(
        {
            "code": "NPV_TOTAL_COST",
            "severity": "INFO",
            "numeric_value": npv_total,
            "year_index": None,
            "message": f"20-year net present value of total cost is INR {npv_total:,.0f}.",
        }
    )

    peak_uncollected = max(history, key=lambda m: m["waste_uncollected_tpd"])
    findings.append(
        {
            "code": "PEAK_UNCOLLECTED_TPD",
            "severity": "INFO",
            "numeric_value": peak_uncollected["waste_uncollected_tpd"],
            "year_index": peak_uncollected["year_index"],
            "message": (
                f"Peak uncollected waste is {peak_uncollected['waste_uncollected_tpd']:.1f} tonnes/day, "
                f"in year {peak_uncollected['year_index']}."
            ),
        }
    )

    if yearly:
        last_year = yearly[-1]
        findings.append(
            {
                "code": "RECOVERY_RATE_Y20",
                "severity": "INFO",
                "numeric_value": last_year["recovery_rate_pct"],
                "year_index": last_year["year_index"],
                "message": (
                    f"By year {last_year['year_index']}, {last_year['recovery_rate_pct']:.1f}% of "
                    "generated waste is treated or recovered."
                ),
            }
        )

    annual_budget = params.get("economic_conditions", {}).get("swm_annual_budget")
    if annual_budget:
        breach_year = next((y["year_index"] for y in yearly if y["total_cost_inr"] > annual_budget), None)
        if breach_year is not None:
            findings.append(
                {
                    "code": "BUDGET_BREACH_YEAR",
                    "severity": "CRITICAL",
                    "numeric_value": breach_year,
                    "year_index": breach_year,
                    "message": f"Annual cost first exceeds the declared SWM budget in year {breach_year}.",
                }
            )

    return findings


__all__ = ["run", "aggregate_by_year", "derive_findings", "ENGINE_VERSION", "MassBalanceError"]
