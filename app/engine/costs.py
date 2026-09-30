"""NPV discounting (design 5.7): per-month opex/capex arithmetic already
happens inline in step.py — this is only the year-level present-value roll-up
shared by run.py's yearly aggregation and app/budget/service.py.
"""

from __future__ import annotations

import math

# Generous enough that no realistic (or even badly miscalibrated) coefficient
# set produces a genuinely different answer once clamped here — it only
# exists so a bad growth/inflation/discount rate degrades a run to an
# extreme-but-finite number instead of crashing it outright.
_OVERFLOW_CEILING = 1e15


def safe_pow(base: float, exponent: float) -> float:
    """`base ** exponent`, guarded against the two ways a bad growth-rate or
    coefficient value can otherwise break a run: a negative base with a
    fractional exponent silently returns a *complex* number in Python (e.g.
    an annual decline steeper than -100% sent straight into the monthly
    compounding formula), and a large base/exponent raises OverflowError
    instead of just producing a big number. Used everywhere this engine
    compounds a rate over time — population growth, industrial growth,
    inflation, NPV discounting — so "handle negative growth gracefully" and
    "prevent arithmetic overflow" both hold at the one place the math
    actually happens, not just at the parameter-validation boundary that
    already rejects extreme values before a run ever gets this far."""
    base = max(0.0, base)
    try:
        result = base**exponent
    except OverflowError:
        return _OVERFLOW_CEILING
    return result if math.isfinite(result) else _OVERFLOW_CEILING


def discount_factor(year_index: int, discount_rate: float) -> float:
    # A discount_rate <= -100% would zero out (or negate) the denominator;
    # floored just above zero so this stays a division by a tiny number
    # (a huge but finite discount factor) rather than a ZeroDivisionError.
    denominator = max(1e-9, safe_pow(1 + discount_rate, year_index))
    return 1.0 / denominator


def discounted(nominal_amount: float, year_index: int, discount_rate: float) -> float:
    return nominal_amount * discount_factor(year_index, discount_rate)


def npv(yearly_nominal_costs: list[float], discount_rate: float) -> float:
    """`yearly_nominal_costs[0]` is year 1's total cost, `[1]` year 2's, etc."""
    return sum(discounted(cost, year + 1, discount_rate) for year, cost in enumerate(yearly_nominal_costs))
