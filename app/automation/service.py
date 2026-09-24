"""Automated parameter ingestion (EXT-01 OSM Overpass, EXT-03 Open-Meteo,
plus an elevation/terrain autofill the design left as an idea without an
API named — Open-Elevation is this session's own choice, a free/keyless
public elevation API, consistent with EXT-01/EXT-03's own "free, keyless
public endpoint" shape).

Every write in this module goes through the SAME `upsert_category` /
`upsert_waste_baseline` functions the category PUT endpoints use — never a
raw ORM `setattr` — so the immutability trigger, the 409
PARAMETER_SET_IMMUTABLE guard, and Stage-1 normalization all apply exactly
as they do to a planner's own manual edit (rule #1). Nothing here bypasses
/validate or /commit: a habitation auto-populated this way still needs an
explicit POST .../validate and .../commit before any run can use it, same
as every other draft.

This module is a caller of app/parameters/ and app/gis/, not part of
app/engine/, so (like app/optimization/ and the other Drop 2/3 modules) it
is free to import ORM models and other app/ services.
"""

from __future__ import annotations

import asyncio
import functools
import json
import uuid
from datetime import date, timedelta
from typing import Any

import geopandas as gpd
import httpx
from geoalchemy2 import Geometry
from pyproj import Geod
from shapely.geometry import LineString, mapping, shape
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.config import settings
from app.core.deps import check_habitation_access
from app.core.errors import AppError
from app.gis.models import LayerSource, LayerType
from app.gis.schemas import LayerUploadIn
from app.gis.service import create_manual_layer
from app.habitation.models import AccessLevel, Habitation
from app.habitation.service import get_habitation_or_404
from app.parameters.models import ParameterDefinition, ParameterSet, ParameterSetStatus
from app.parameters.schemas import ParameterSetCreate
from app.parameters.service import (
    create_parameter_set,
    derive_semi_automated_fields,
    get_parameter_set_full,
    get_parameter_set_or_404,
    upsert_category,
)

EXTERNAL_TIMEOUT_SECONDS = 15.0  # per spec: "concurrent 15s-timeout tasks and graceful degradation"
ELEVATION_GRID_SIZE = 3  # 3x3 = 9 sample points, per the brief
COASTAL_MAX_ELEVATION_M = 5.0
HILLY_SLOPE_THRESHOLD_PCT = 8.0
COASTAL_BUFFER_METERS = 500.0

# A real User-Agent, not httpx's default: confirmed against the live
# Overpass instance while building this module that it 406s an anonymous
# client outright (Overpass's own abuse policy — the design's EXT-02 note
# "policy requires ... a real User-Agent" turned out to apply here too, not
# just to Nominatim). Sent on every external call in this module.
_REQUEST_HEADERS = {"User-Agent": "SWMS-Backend/1.0 (Smart Waste Management Simulator; hackathon project)"}

# Both thresholds above are this session's own scope decision — the design
# names no numeric cutoff for "coastal" or "hilly", only the shape of the
# classification (design 5.4.6 talks about terrain efficiency by type, not
# how a type is derived from raw elevation). Documented here rather than
# silently invented, same convention as app/engine/coefficients.py.


# ---------------------------------------------------------------------------
# Geometry extraction (PostGIS side) — same ST_AsGeoJSON/ST_XMin/etc. pattern
# already used by app/gis/service.py's get_map_overlay().
# ---------------------------------------------------------------------------
async def _get_habitation_geometry(
    db: AsyncSession, habitation_id: uuid.UUID
) -> tuple[dict[str, Any], tuple[float, float, float, float], tuple[float, float]]:
    row = (
        await db.execute(
            select(
                func.ST_AsGeoJSON(Habitation.boundary),
                func.ST_XMin(cast(Habitation.boundary, Geometry())),
                func.ST_YMin(cast(Habitation.boundary, Geometry())),
                func.ST_XMax(cast(Habitation.boundary, Geometry())),
                func.ST_YMax(cast(Habitation.boundary, Geometry())),
                func.ST_X(cast(Habitation.centroid, Geometry())),
                func.ST_Y(cast(Habitation.centroid, Geometry())),
            ).where(Habitation.id == habitation_id)
        )
    ).one_or_none()

    if row is None or row[0] is None:
        raise AppError(
            "HABITATION_BOUNDARY_REQUIRED", "Habitation has no boundary geometry to automate from", 409
        )
    geom_json, xmin, ymin, xmax, ymax, lon, lat = row
    boundary_geojson = json.loads(geom_json)
    return boundary_geojson, (float(xmin), float(ymin), float(xmax), float(ymax)), (float(lon), float(lat))


# ---------------------------------------------------------------------------
# 1. Road network (Overpass) -> community_infrastructure.road_network_km
#    + a new ROAD GIS layer.
# ---------------------------------------------------------------------------
def _polygon_ring_for_overpass(boundary_geojson: dict[str, Any]) -> str:
    """Overpass's `poly:` filter takes exactly one ring, "lat1 lon1 lat2
    lon2 ...". A habitation boundary is a MultiPolygon (project-wide rule);
    this uses its first polygon's exterior ring — a documented
    simplification for the (rare) disjoint-multi-part boundary case, since
    Overpass QL has no multi-ring polygon filter to hand it the rest."""
    geom_type = boundary_geojson.get("type")
    if geom_type == "MultiPolygon":
        ring = boundary_geojson["coordinates"][0][0]
    elif geom_type == "Polygon":
        ring = boundary_geojson["coordinates"][0]
    else:
        raise AppError("BOUNDARY_UNSUPPORTED", f"Cannot build a road-network query from a {geom_type} boundary", 422)
    return " ".join(f"{lat} {lon}" for lon, lat in ring)


def _fetch_road_network_sync(boundary_geojson: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Synchronous core of the road-network fetch — run in a worker thread by
    _fetch_road_network below, not awaited directly against an async client
    like every other fetch in this module.

    Found live, reproducibly: the free Overpass mirror this deployment's
    .env points at (overpass.kumi.systems) can accept a connection and the
    full POST body, then simply never send a response or close the socket.
    That failure mode defeated every purely-async bound tried against it —
    httpx.AsyncClient's own configured timeout, asyncio.wait(timeout=...)
    around the task, and asyncio.wait_for(...) around the whole coroutine —
    all of which ultimately still have to `await` something that depends on
    the stuck connection eventually yielding control back (whether that's
    the read itself, or a cleanup path like client.aclose() called on a
    client with a read in flight). A worker thread sidesteps this
    completely: _fetch_road_network wraps this call in
    asyncio.wait_for(loop.run_in_executor(...)), which returns to the caller
    on schedule regardless of whether this thread ever finishes, because it
    never has to wait for the thread — only observe whether it finished in
    time. The abandoned thread (and its socket) cleans itself up once the OS
    finally times out or resets the underlying connection; we just stop
    waiting for confirmation that it did.
    """
    poly = _polygon_ring_for_overpass(boundary_geojson)
    # The Overpass QL's own [timeout:N] tells the SERVER how long it may
    # keep working, independent of any HTTP-client-side timeout — the
    # actual root cause of a real, reproducible multi-minute hang found
    # while building this module: with this set to 60 (well past
    # EXTERNAL_TIMEOUT_SECONDS), a genuinely slow query gets a well-behaved
    # server's full cooperation to keep running — and to keep the
    # connection alive while it does — for up to 60 seconds, regardless of
    # what the client intended. Keeping it strictly below
    # EXTERNAL_TIMEOUT_SECONDS means the SERVER gives up and sends a clean
    # error first, before the client-side timeout would otherwise have to.
    overpass_budget = max(5, int(timeout) - 3)
    query = (
        f"[out:json][timeout:{overpass_budget}];"
        f'way["highway"~"^(primary|secondary|tertiary|residential|service|unclassified)$"](poly:"{poly}");'
        "out body; >; out skel qt;"
    )
    with httpx.Client(timeout=timeout, headers=_REQUEST_HEADERS) as client:
        response = client.post(settings.overpass_api_url, data={"data": query})
        response.raise_for_status()
        data = response.json()

    nodes: dict[int, tuple[float, float]] = {}
    ways: list[list[int]] = []
    for element in data.get("elements", []):
        if element.get("type") == "node":
            nodes[element["id"]] = (element["lon"], element["lat"])
        elif element.get("type") == "way":
            ways.append(element.get("nodes", []))

    lines: list[LineString] = []
    for way_node_ids in ways:
        coords = [nodes[node_id] for node_id in way_node_ids if node_id in nodes]
        if len(coords) >= 2:  # Shapely raises on a 0- or 1-point LineString, so filter first
            lines.append(LineString(coords))
    if not lines:
        return {"road_network_km": 0.0, "geojson_features": []}

    boundary_geom = shape(boundary_geojson)
    gdf_lines = gpd.GeoDataFrame(geometry=lines, crs="EPSG:4326")
    gdf_boundary = gpd.GeoDataFrame(geometry=[boundary_geom], crs="EPSG:4326")
    # A local UTM zone, not raw lon/lat degrees, so .length below is real
    # metres — the same "reproject before measuring" rule
    # app/scenario/spatial_impact.py follows via PostGIS ::geography casts,
    # done here in GeoPandas/pyproj instead since the geometry only ever
    # exists in Python for this one clip-and-measure step.
    utm_crs = gdf_boundary.estimate_utm_crs()
    lines_utm = gdf_lines.to_crs(utm_crs)
    boundary_utm = gdf_boundary.to_crs(utm_crs).geometry.iloc[0]

    clipped = lines_utm.geometry.intersection(boundary_utm)
    clipped = clipped[~clipped.is_empty]
    total_length_m = float(clipped.length.sum()) if len(clipped) else 0.0

    clipped_wgs84 = gpd.GeoSeries(clipped, crs=utm_crs).to_crs("EPSG:4326") if len(clipped) else clipped
    features = [
        {"type": "Feature", "properties": {}, "geometry": mapping(geom)}
        for geom in clipped_wgs84
        if not geom.is_empty
    ]

    return {"road_network_km": round(total_length_m / 1000.0, 3), "geojson_features": features}


async def _fetch_road_network(boundary_geojson: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Async shim around _fetch_road_network_sync — see that function's
    docstring for why this dispatches to a worker thread instead of using an
    async httpx client the way every other fetch in this module does."""
    loop = asyncio.get_running_loop()
    fn = functools.partial(_fetch_road_network_sync, boundary_geojson, timeout)
    # +2s over the thread's own httpx timeout: gives the thread a fair
    # chance to hit its own timeout and return cleanly first; if it doesn't,
    # we give up anyway rather than trust it to.
    return await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=timeout + 2.0)


# ---------------------------------------------------------------------------
# 2. Annual rainfall (Open-Meteo) -> natural_resources.annual_rainfall_mm
# ---------------------------------------------------------------------------
async def _fetch_annual_rainfall(client: httpx.AsyncClient, lat: float, lon: float) -> float:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=365)
    params: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "precipitation_sum",
        "timezone": "UTC",
    }
    if settings.open_meteo_api_key:
        params["apikey"] = settings.open_meteo_api_key
    response = await client.get(settings.open_meteo_api_url, params=params)
    response.raise_for_status()
    daily = response.json().get("daily", {}).get("precipitation_sum", [])
    total = sum(v for v in daily if v is not None)
    return round(total, 2)


# ---------------------------------------------------------------------------
# 3 & 4. Terrain/slope (Open-Elevation) -> terrain.avg_slope_pct,
#    terrain.terrain_type, terrain.coastal_buffer_zone_meters.
# ---------------------------------------------------------------------------
async def _fetch_terrain(client: httpx.AsyncClient, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    xmin, ymin, xmax, ymax = bbox
    n = ELEVATION_GRID_SIZE
    xs = [xmin + (xmax - xmin) * i / (n - 1) for i in range(n)]
    ys = [ymin + (ymax - ymin) * i / (n - 1) for i in range(n)]
    grid = [(x, y) for y in ys for x in xs]  # row-major

    locations = [{"latitude": y, "longitude": x} for x, y in grid]
    response = await client.post(settings.open_elevation_api_url, json={"locations": locations})
    response.raise_for_status()
    results = response.json().get("results", [])
    if len(results) != len(grid):
        raise AppError("ELEVATION_RESPONSE_INVALID", "Open-Elevation returned an unexpected number of points", 502)
    elevations = [float(r["elevation"]) for r in results]

    geod = Geod(ellps="WGS84")
    slopes: list[float] = []
    for row in range(n):
        for col in range(n):
            idx = row * n + col
            lon, lat = grid[idx]
            elev = elevations[idx]
            if col + 1 < n:
                right = row * n + (col + 1)
                _, _, dist_m = geod.inv(lon, lat, grid[right][0], grid[right][1])
                if dist_m > 0:
                    slopes.append(abs(elevations[right] - elev) / dist_m * 100)
            if row + 1 < n:
                down = (row + 1) * n + col
                _, _, dist_m = geod.inv(lon, lat, grid[down][0], grid[down][1])
                if dist_m > 0:
                    slopes.append(abs(elevations[down] - elev) / dist_m * 100)

    avg_slope_pct = round(sum(slopes) / len(slopes), 3) if slopes else 0.0
    min_elevation = min(elevations)

    if min_elevation <= COASTAL_MAX_ELEVATION_M and avg_slope_pct < HILLY_SLOPE_THRESHOLD_PCT:
        terrain_type = "COASTAL_PLAINS"
    elif avg_slope_pct >= HILLY_SLOPE_THRESHOLD_PCT:
        terrain_type = "HILLY"
    else:
        terrain_type = "PLAINS"

    return {"avg_slope_pct": avg_slope_pct, "terrain_type": terrain_type, "min_elevation_m": min_elevation}


# ---------------------------------------------------------------------------
# Target parameter set resolution — "creates or targets the active draft".
# ---------------------------------------------------------------------------
async def _resolve_target_parameter_set(
    db: AsyncSession, habitation: Habitation, payload: Any, user: User
) -> ParameterSet:
    if payload.parameter_set_id is not None:
        ps = await get_parameter_set_or_404(db, payload.parameter_set_id)
        if ps.habitation_id != habitation.id:
            raise AppError("PARAMETER_SET_NOT_FOUND", "Parameter set does not belong to this habitation", 404)
        return ps

    latest = await db.scalar(
        select(ParameterSet)
        .where(ParameterSet.habitation_id == habitation.id)
        .order_by(ParameterSet.version_no.desc())
        .limit(1)
    )
    if latest is not None and latest.status in (ParameterSetStatus.DRAFT, ParameterSetStatus.INVALID):
        return latest

    # No editable set exists: start a fresh draft, cloned from the currently
    # active VALIDATED version if there is one (so auto-populate fills gaps
    # in what's already there instead of starting from a blank sheet).
    clone_from_version = None
    if habitation.active_parameter_set_id is not None:
        active = await db.get(ParameterSet, habitation.active_parameter_set_id)
        if active is not None:
            clone_from_version = active.version_no

    return await create_parameter_set(
        db,
        habitation.id,
        ParameterSetCreate(clone_from_version=clone_from_version, change_note="Auto-populate draft"),
        user,
    )


async def _list_missing_required_fields(db: AsyncSession, psid: uuid.UUID) -> list[str]:
    full = await get_parameter_set_full(db, psid)
    definitions = await db.scalars(select(ParameterDefinition).where(ParameterDefinition.is_required.is_(True)))
    missing = []
    for definition in definitions:
        row = full["waste_baseline"] if definition.category == "waste_baseline" else full["categories"].get(definition.category)
        value = row.get(definition.param_key) if row else None
        if value is None:
            missing.append(f"{definition.category}.{definition.param_key}")
    return sorted(missing)


def _skip_reason(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return f"timed out after {EXTERNAL_TIMEOUT_SECONDS:.0f}s"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"upstream returned {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return f"network error: {exc}"
    if isinstance(exc, AppError):
        return exc.message
    return str(exc) or type(exc).__name__


async def auto_populate(db: AsyncSession, habitation_id: uuid.UUID, payload: Any, user: User) -> dict[str, Any]:
    habitation = await get_habitation_or_404(db, habitation_id)
    # Same EDITOR-level check every category PUT endpoint already applies
    # (app/parameters/router.py) — auto-populate is just another way of
    # writing category values, so it needs exactly the same permission.
    await check_habitation_access(db, user, habitation_id, AccessLevel.EDITOR)

    boundary_geojson, bbox, (lon, lat) = await _get_habitation_geometry(db, habitation_id)
    parameter_set = await _resolve_target_parameter_set(db, habitation, payload, user)

    automated_categories: list[str] = []
    skipped_categories: list[dict[str, str]] = []
    derived_fields: list[str] = []
    gis_layer_id: str | None = None

    # verify=True (the default) — never disable TLS certificate verification
    # even for a known-broken host (Open-Elevation's cert is expired): that
    # failure is exactly what _skip_reason()/skipped_categories exists to
    # report cleanly, not something to route around by trusting bad certs.
    #
    # Rainfall and terrain use an async httpx client bounded by
    # asyncio.wait(timeout=...) — proven reliable in practice for both.
    # Roads uses a completely different mechanism (see _fetch_road_network's
    # docstring): the free Overpass mirror this deployment's .env points at
    # (overpass.kumi.systems) was found, live and reproducibly, to
    # occasionally accept a connection and the request body and then never
    # send a response or close the socket — a failure mode that defeated
    # every purely-async bound tried against it, because each one still had
    # to *await* something (a read, or a cleanup path like client.aclose())
    # that depended on the stuck connection eventually yielding control
    # back. _fetch_road_network instead runs the whole call in a worker
    # thread via asyncio.wait_for(loop.run_in_executor(...)), which returns
    # to this caller on schedule regardless of whether that thread ever
    # finishes.
    async def _run_bounded(coro_factory, timeout: float) -> Any:
        client = httpx.AsyncClient(timeout=EXTERNAL_TIMEOUT_SECONDS, headers=_REQUEST_HEADERS)
        task = asyncio.ensure_future(coro_factory(client))
        try:
            done, _pending = await asyncio.wait({task}, timeout=timeout)
            if task in done:
                result = task.result()
                if not client.is_closed:
                    asyncio.ensure_future(client.aclose())
                return result
            task.cancel()
            if not client.is_closed:
                asyncio.ensure_future(client.aclose())
            return TimeoutError(f"no response within {timeout:.0f}s")
        except Exception as exc:  # noqa: BLE001 - reported via skipped_categories, not raised
            if not client.is_closed:
                asyncio.ensure_future(client.aclose())
            return exc

    async def _run_road_bounded() -> Any:
        try:
            return await _fetch_road_network(boundary_geojson, EXTERNAL_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - reported via skipped_categories, not raised
            return exc

    road_result, rainfall_result, terrain_result = await asyncio.gather(
        _run_road_bounded(),
        _run_bounded(lambda c: _fetch_annual_rainfall(c, lat, lon), EXTERNAL_TIMEOUT_SECONDS),
        _run_bounded(lambda c: _fetch_terrain(c, bbox), EXTERNAL_TIMEOUT_SECONDS),
    )

    # --- 1. Roads --------------------------------------------------------
    if isinstance(road_result, BaseException):
        skipped_categories.append(
            {"category": "community_infrastructure.road_network_km", "reason": _skip_reason(road_result)}
        )
    else:
        await upsert_category(
            db, parameter_set.id, "community_infrastructure", {"road_network_km": road_result["road_network_km"]}
        )
        automated_categories.append("community_infrastructure.road_network_km")
        if road_result["geojson_features"]:
            layer_payload = LayerUploadIn(
                layer_name=f"Auto-Ingested OSM Roads ({date.today().isoformat()}-{uuid.uuid4().hex[:6]})",
                layer_type=LayerType.ROAD,
                geojson={"type": "FeatureCollection", "features": road_result["geojson_features"]},
            )
            try:
                layer = await create_manual_layer(
                    db, habitation_id, layer_payload, user, source=LayerSource.OSM_OVERPASS
                )
                gis_layer_id = str(layer.id)
                automated_categories.append("gis_layers.ROAD")
            except AppError as exc:
                skipped_categories.append({"category": "gis_layers.ROAD", "reason": exc.message})

    # --- 2. Rainfall -------------------------------------------------------
    if isinstance(rainfall_result, BaseException):
        skipped_categories.append(
            {"category": "natural_resources.annual_rainfall_mm", "reason": _skip_reason(rainfall_result)}
        )
    else:
        await upsert_category(db, parameter_set.id, "natural_resources", {"annual_rainfall_mm": rainfall_result})
        automated_categories.append("natural_resources.annual_rainfall_mm")

    # --- 3 & 4. Terrain / slope / coastal buffer ---------------------------
    if isinstance(terrain_result, BaseException):
        skipped_categories.append({"category": "terrain", "reason": _skip_reason(terrain_result)})
    else:
        terrain_payload: dict[str, Any] = {
            "avg_slope_pct": terrain_result["avg_slope_pct"],
            "terrain_type": terrain_result["terrain_type"],
        }
        if terrain_result["terrain_type"] == "COASTAL_PLAINS":
            terrain_payload["coastal_buffer_zone_meters"] = COASTAL_BUFFER_METERS
        await upsert_category(db, parameter_set.id, "terrain", terrain_payload)
        automated_categories.extend(f"terrain.{key}" for key in terrain_payload)

    # --- 5. Semi-automated formulations --------------------------------------
    # Shared with app/ingestion/service.py's ingest_accepted_rows, so the
    # same two formulas apply on every path data can enter a parameter set
    # through, not just this one.
    derived_fields.extend(await derive_semi_automated_fields(db, parameter_set.id))

    manual_fields_remaining = await _list_missing_required_fields(db, parameter_set.id)

    return {
        "parameter_set_id": str(parameter_set.id),
        "automated_categories": automated_categories,
        "skipped_categories": skipped_categories,
        "derived_fields": derived_fields,
        "manual_fields_remaining": manual_fields_remaining,
        "gis_layer_id": gis_layer_id,
    }
