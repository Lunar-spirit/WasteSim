import uuid

from pydantic import BaseModel


class AutoPopulateIn(BaseModel):
    parameter_set_id: uuid.UUID | None = None


class RoadDiagnosticsOut(BaseModel):
    """Explicit execution diagnostics for the OSM Overpass road fetch — never
    just "0 features, empty 200 OK". status is one of SUCCESS, NO_DATA_FOUND
    (Overpass responded but nothing usable came back — boundary/coordinate-
    order/query problem, not a network failure) or ERROR (the request itself
    failed — timeout, rate limit, network error). query_boundary_ring is
    exactly what was sent to Overpass's poly: filter, so a lat/lon-vs-lon/lat
    mismatch is visible by inspection, not guesswork."""

    status: str
    reason: str | None = None
    query_boundary_ring: list[list[float]] | None = None
    overpass_raw_node_count: int | None = None
    overpass_raw_way_count: int | None = None
    overpass_raw_relation_count: int | None = None
    parsed_linestring_count: int | None = None
    # PostGIS ST_Length(geography(geom))-computed, read back from the
    # persisted layer after create_manual_layer() — the same number
    # GisStudioPage's inspector card shows, not a separately-computed one.
    total_length_km: float | None = None
    gis_layer_id: str | None = None


class AutoPopulateOut(BaseModel):
    parameter_set_id: str
    automated_categories: list[str]
    skipped_categories: list[dict[str, str]]
    derived_fields: list[str]
    manual_fields_remaining: list[str]
    gis_layer_id: str | None = None
    road_diagnostics: RoadDiagnosticsOut
