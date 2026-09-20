"""Decision space (design 5.6): the six levers a planner may change, and the
bounds a search is allowed to explore them within. Bounds come from the
current habitation's own parameters and the coefficient set's physical
limits (BR-26) — nothing here is a hardcoded threshold picked out of the air
except where explicitly called out below as a scope decision, the same way
app/engine/coefficients.py documents its own substitutions.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.engine.coefficients import Coefficients
from app.gis.models import GISLayer, LayerStatus, LayerType

DECISION_VARIABLES = (
    "add_vehicles",
    "add_treatment_capacity_tpd",
    "target_coverage_pct",
    "target_segregation_pct",
    "landfill_expansion_tonnes",
    "transfer_stations",
)

# add_vehicles and transfer_stations are counts; the rest are continuous.
INTEGER_VARIABLES = frozenset({"add_vehicles", "transfer_stations"})

# Design 5.6 states the range as "0 ... limit" without naming the limit —
# genuinely underspecified. Chosen as the simplest sensible default (roughly
# a small town's landfill capacity) rather than guessing at a per-habitation
# formula the design never gives.
DEFAULT_LANDFILL_EXPANSION_LIMIT_TONNES = 50_000.0


async def _habitation_has_eco_sensitive_layer(db: AsyncSession, habitation_id: uuid.UUID) -> bool:
    """BR-26's "eco-sensitive zone" check: does this habitation have any
    successfully-ingested ECO_SENSITIVE GIS layer at all. A habitation-level
    check, not a site-level intersection — the design names no landfill site
    geometry to intersect against, only the habitation as a whole."""
    stmt = (
        select(GISLayer.id)
        .where(
            GISLayer.habitation_id == habitation_id,
            GISLayer.layer_type == LayerType.ECO_SENSITIVE,
            GISLayer.status == LayerStatus.READY,
        )
        .limit(1)
    )
    return (await db.scalar(stmt)) is not None


def default_bounds(params: dict[str, Any], coeffs: Coefficients) -> dict[str, list[float]]:
    community = params["community_infrastructure"]
    cultural = params["cultural_context"]
    current_coverage = float(community.get("collection_coverage_pct") or 0.0)
    current_treatment = float(community.get("treatment_capacity_tpd") or 0.0)
    current_segregation = float(cultural.get("segregation_practice_pct") or 0.0)
    seg_ceiling = float(coeffs["segregation_ceiling_pct"])  # BR-26 physical limit: segregation <= 90%

    return {
        "add_vehicles": [0, 20],
        "add_treatment_capacity_tpd": [0.0, round(current_treatment * 3, 3)],
        "target_coverage_pct": [current_coverage, 100.0],  # BR-26 physical limit: coverage <= 100%
        "target_segregation_pct": [current_segregation, max(current_segregation, seg_ceiling)],
        "landfill_expansion_tonnes": [0.0, DEFAULT_LANDFILL_EXPANSION_LIMIT_TONNES],
        "transfer_stations": [0, 3],
    }


async def build_decision_space(
    db: AsyncSession,
    habitation_id: uuid.UUID,
    params: dict[str, Any],
    coeffs: Coefficients,
    overrides: dict[str, list[float]] | None,
) -> tuple[dict[str, list[float]], list[str]]:
    """Returns (decision_space, notes). `overrides` (API-67's optional
    decision_space body field) can only narrow a bound, never widen it past
    the physical/catalogue limit — BR-26 would otherwise be trivially
    bypassed by a caller just asking for a wider landfill_expansion range."""
    space = default_bounds(params, coeffs)
    notes: list[str] = []

    if await _habitation_has_eco_sensitive_layer(db, habitation_id):
        space["landfill_expansion_tonnes"] = [0.0, 0.0]
        notes.append("landfill_expansion forced to 0 — habitation lies in an eco-sensitive zone (BR-26)")

    if overrides:
        for key, bounds in overrides.items():
            if key not in space:
                raise AppError("INVALID_DECISION_SPACE", f"'{key}' is not a known decision variable", 400)
            lo, hi = float(bounds[0]), float(bounds[1])
            phys_lo, phys_hi = space[key]
            space[key] = [max(lo, phys_lo), min(hi, phys_hi)]

    return space, notes
