"""NPV discounting (design 5.7): per-month opex/capex arithmetic already
happens inline in step.py — this is only the year-level present-value roll-up
shared by run.py's yearly aggregation and app/budget/service.py.
"""

from __future__ import annotations


def discount_factor(year_index: int, discount_rate: float) -> float:
    return 1.0 / ((1 + discount_rate) ** year_index)


def discounted(nominal_amount: float, year_index: int, discount_rate: float) -> float:
    return nominal_amount * discount_factor(year_index, discount_rate)


def npv(yearly_nominal_costs: list[float], discount_rate: float) -> float:
    """`yearly_nominal_costs[0]` is year 1's total cost, `[1]` year 2's, etc."""
    return sum(discounted(cost, year + 1, discount_rate) for year, cost in enumerate(yearly_nominal_costs))
