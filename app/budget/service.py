"""M12: turns a completed run's monthly history into budget_lines — one row
per year x kind x category (design section 4.3/5.7). Called from
app/simulation/service.py's run-completion transaction, not from its own
endpoint: a budget is a view onto a run's own numbers, not a separate
computation with its own inputs.

The engine (app/engine/step.py) computes one opex_inr/capex_inr total per
month — enough for the simulation_yearly rollup, but budget_lines wants a
named category per row. This module re-splits that same total using the
same coefficients and the same monthly figures, rather than changing the
engine's snapshot shape for a display concern.
"""

from __future__ import annotations

from typing import Any

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.budget.models import BudgetLine, CostCategory, CostKind
from app.engine.coefficients import Coefficients
from app.engine.costs import discounted


def build_budget_lines(
    monthly_history: list[dict[str, Any]], coeffs: Coefficients, discount_rate: float
) -> list[dict[str, Any]]:
    """Returns plain dicts (not ORM rows) — one per (year_index, kind,
    category) that actually had a non-zero amount that year, aggregated
    from the monthly snapshots the same way simulation_yearly is."""
    by_year: dict[int, dict[tuple[CostKind, CostCategory], float]] = {}

    for month in monthly_history:
        year = month["year_index"]
        days = month["days_in_month"]
        bucket = by_year.setdefault(year, {})

        def add(kind: CostKind, category: CostCategory, amount: float) -> None:
            key = (kind, category)
            bucket[key] = bucket.get(key, 0.0) + amount

        collection = month["waste_collected_tpd"] * days * coeffs["cost_collection_per_tonne"]
        treatment = month["organic_treated_tpd"] * days * coeffs["cost_treatment_per_tonne"]
        disposal = month["to_landfill_tpd"] * days * coeffs["cost_disposal_per_tonne"]
        transport = month["vehicles_have"] * coeffs["vehicle_monthly_opex"]
        # step.py applies admin overhead to the sum of exactly these four
        # streams, then inflation on top — mirrored here so the four
        # category rows plus this one add up to the same opex_inr the
        # month's own snapshot recorded.
        pre_admin = collection + treatment + disposal + transport
        admin = pre_admin * coeffs["admin_overhead_pct"]
        inflation_factor = month["opex_inr"] / (pre_admin + admin) if (pre_admin + admin) > 0 else 1.0

        add(CostKind.OPEX, CostCategory.COLLECTION, collection * inflation_factor)
        add(CostKind.OPEX, CostCategory.TREATMENT, treatment * inflation_factor)
        add(CostKind.OPEX, CostCategory.DISPOSAL, disposal * inflation_factor)
        add(CostKind.OPEX, CostCategory.TRANSPORT, transport * inflation_factor)
        add(CostKind.OPEX, CostCategory.ADMIN, admin * inflation_factor)

        if month["vehicles_added_this_month"]:
            add(
                CostKind.CAPEX,
                CostCategory.FLEET_PURCHASE,
                month["vehicles_added_this_month"] * coeffs["vehicle_capex"],
            )
        if month["capacity_added_this_month"]:
            add(
                CostKind.CAPEX,
                CostCategory.INFRASTRUCTURE,
                month["capacity_added_this_month"] * coeffs["treatment_capex_per_tpd"],
            )

    lines: list[dict[str, Any]] = []
    for year, bucket in sorted(by_year.items()):
        for (kind, category), amount in bucket.items():
            if amount <= 0:
                continue
            lines.append(
                {
                    "year_index": year,
                    "kind": kind,
                    "category": category,
                    "amount_inr": amount,
                    "discounted_inr": discounted(amount, year, discount_rate),
                }
            )
    return lines


async def persist_budget_lines(db: AsyncSession, run_id: uuid.UUID, lines: list[dict[str, Any]]) -> None:
    for line in lines:
        db.add(BudgetLine(run_id=run_id, **line))
    await db.flush()


async def get_budget_summary(db: AsyncSession, run_id: uuid.UUID) -> dict[str, Any]:
    from sqlalchemy import select

    rows = list(await db.scalars(select(BudgetLine).where(BudgetLine.run_id == run_id)))
    total_opex = sum(float(r.amount_inr) for r in rows if r.kind == CostKind.OPEX)
    total_capex = sum(float(r.amount_inr) for r in rows if r.kind == CostKind.CAPEX)
    total_discounted = sum(float(r.discounted_inr) for r in rows)

    by_category: dict[str, float] = {}
    for row in rows:
        by_category[row.category.value] = by_category.get(row.category.value, 0.0) + float(row.amount_inr)

    return {
        "run_id": str(run_id),
        "total_opex_inr": total_opex,
        "total_capex_inr": total_capex,
        "total_cost_inr": total_opex + total_capex,
        "npv_total_cost_inr": total_discounted,
        "by_category": by_category,
        "lines": rows,
    }
