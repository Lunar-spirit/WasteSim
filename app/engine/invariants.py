"""Mass-balance and sanity assertions, run after every month (design 5.4 —
"assert these before persisting any run; if either breaks, fail the run
rather than storing numbers nobody can defend"). Both invariants hold by
construction in step.py's arithmetic; this is the backstop that catches a
future bug in that arithmetic before it ever reaches the database.
"""

from __future__ import annotations

import math
from typing import Any

TOLERANCE_PCT = 0.1  # design's own "+/- 0.1%"


class MassBalanceError(Exception):
    def __init__(self, month: int, message: str) -> None:
        self.month = month
        self.message = message
        super().__init__(f"month {month}: {message}")


def _close_enough(a: float, b: float, tolerance_pct: float = TOLERANCE_PCT) -> bool:
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) / scale * 100 <= tolerance_pct


def check_month(snapshot: dict[str, Any], month: int) -> None:
    for key in (
        "waste_total_tpd",
        "waste_collected_tpd",
        "waste_uncollected_tpd",
        "organic_treated_tpd",
        "recyclables_recovered_tpd",
        "to_landfill_tpd",
        "opex_inr",
        "landfill_remaining_tonnes",
    ):
        value = snapshot[key]
        if math.isnan(value) or math.isinf(value):
            raise MassBalanceError(month, f"{key} is NaN or infinite ({value})")
        if value < 0:
            raise MassBalanceError(month, f"{key} is negative ({value}) — no flow may be negative")

    generated = snapshot["waste_total_tpd"]
    collected = snapshot["waste_collected_tpd"]
    uncollected = snapshot["waste_uncollected_tpd"]
    if not _close_enough(generated, collected + uncollected):
        raise MassBalanceError(
            month,
            f"generated ({generated:.4f}) != collected + uncollected ({collected + uncollected:.4f})",
        )

    treated = snapshot["organic_treated_tpd"]
    recovered = snapshot["recyclables_recovered_tpd"]
    landfilled = snapshot["to_landfill_tpd"]
    rejects = snapshot["rejects_tpd"]
    if not _close_enough(collected + rejects, treated + recovered + landfilled):
        raise MassBalanceError(
            month,
            f"collected + rejects ({collected + rejects:.4f}) != "
            f"treated + recovered + landfilled ({treated + recovered + landfilled:.4f})",
        )
