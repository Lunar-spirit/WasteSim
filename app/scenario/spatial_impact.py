"""BR-23: where an event carries a real affected_area polygon, its
accessibility impact is derived from the habitation's own GIS layers rather
than accepted as a guess — "the same flood must hurt more where the road
network actually gets cut, not by however severe the caller declares it."

Derived values always win over a declared impact_params value for the same
key (see ScenarioEvent.effective_impact_params); a declared value is used
only where no geometry exists to derive from — either no affected_area was
given, or the habitation has no READY layer of the relevant type yet.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gis.models import LayerStatus, LayerType


async def derive_road_accessibility_loss(
    db: AsyncSession, habitation_id: uuid.UUID, affected_area_geojson: dict[str, Any]
) -> float | None:
    """Share of the habitation's ROAD network length that falls inside the
    affected area — design 5.5/5.9's literal formula:
    SUM(ST_Length(ST_Intersection(feature.geom, affected_area))) / SUM(ST_Length(feature.geom)).
    Returns None (not 0.0) when there is no ROAD layer to measure against,
    so the caller knows to fall back to a declared value instead of
    silently reporting "no damage"."""
    params = {
        "habitation_id": str(habitation_id),
        "layer_type": LayerType.ROAD.value,
        "status": LayerStatus.READY.value,
    }
    total_length = await db.scalar(
        text(
            """
            SELECT SUM(ST_Length(f.geom::geography))
            FROM gis_features f
            JOIN gis_layers l ON l.id = f.layer_id
            WHERE l.habitation_id = :habitation_id AND l.layer_type = :layer_type AND l.status = :status
            """
        ),
        params,
    )
    if not total_length:
        return None

    intersected_length = await db.scalar(
        text(
            """
            SELECT COALESCE(SUM(
                ST_Length(
                    ST_Intersection(
                        f.geom::geography,
                        ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326)::geography
                    )
                )
            ), 0)
            FROM gis_features f
            JOIN gis_layers l ON l.id = f.layer_id
            WHERE l.habitation_id = :habitation_id AND l.layer_type = :layer_type AND l.status = :status
            """
        ),
        {**params, "geojson": json.dumps(affected_area_geojson)},
    )
    return min(1.0, float(intersected_length) / float(total_length))


async def derive_population_affected_pct(
    db: AsyncSession, habitation_id: uuid.UUID, affected_area_geojson: dict[str, Any]
) -> float | None:
    """Approximated as the share of SETTLEMENT features intersecting the
    affected area — a feature-count ratio, not a population-weighted one,
    since no per-feature population figure exists in gis_features.properties
    for every dataset a planner might upload. Documented approximation, not
    a silent one."""
    params = {
        "habitation_id": str(habitation_id),
        "layer_type": LayerType.SETTLEMENT.value,
        "status": LayerStatus.READY.value,
    }
    total_count = await db.scalar(
        text(
            """
            SELECT COUNT(*) FROM gis_features f
            JOIN gis_layers l ON l.id = f.layer_id
            WHERE l.habitation_id = :habitation_id AND l.layer_type = :layer_type AND l.status = :status
            """
        ),
        params,
    )
    if not total_count:
        return None

    intersecting_count = await db.scalar(
        text(
            """
            SELECT COUNT(*) FROM gis_features f
            JOIN gis_layers l ON l.id = f.layer_id
            WHERE l.habitation_id = :habitation_id AND l.layer_type = :layer_type AND l.status = :status
              AND ST_Intersects(f.geom, ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326))
            """
        ),
        {**params, "geojson": json.dumps(affected_area_geojson)},
    )
    return min(100.0, float(intersecting_count) / float(total_count) * 100.0)


async def derive_impacts(
    db: AsyncSession, habitation_id: uuid.UUID, event_type: str, affected_area_geojson: dict[str, Any] | None
) -> dict[str, float]:
    """Only FLOOD and LANDSLIDE have a spatial derivation defined (design
    5.5's table — every other event type's magnitude is declared, not
    measured from geometry). Returns {} when there's nothing to derive,
    which effective_impact_params() treats as "use the declared value"."""
    if affected_area_geojson is None or event_type not in ("FLOOD", "LANDSLIDE"):
        return {}

    derived: dict[str, float] = {}
    road_loss = await derive_road_accessibility_loss(db, habitation_id, affected_area_geojson)
    if road_loss is not None:
        derived["road_accessibility_loss"] = road_loss
    population_pct = await derive_population_affected_pct(db, habitation_id, affected_area_geojson)
    if population_pct is not None:
        derived["population_affected_pct"] = population_pct
    return derived
