import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import cast, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import Geometry

from app.auth.models import User
from app.core.errors import AppError
from app.gis.models import GISFeature, GISLayer, LayerSource, LayerStatus, LayerType
from app.gis.parsers import CRSUndeclaredError, ParseError, ParsedLayer, parse_gis_file
from app.gis.schemas import LayerUploadIn
from app.habitation.models import Habitation
from app.ingestion.models import DatasetUpload
from app.validation.models import Severity, ValidationIssue, ValidationReport, ValidationResult, ValidationScope
from app.validation.pipeline import Issue, PipelineResult

BOUNDARY_BUFFER_METRES = 2000
OUTSIDE_BOUNDARY_REJECT_FRACTION = 0.3


async def _get_habitation_or_404(db: AsyncSession, habitation_id: uuid.UUID) -> Habitation:
    habitation = await db.get(Habitation, habitation_id)
    if habitation is None or habitation.deleted_at is not None:
        raise AppError("HABITATION_NOT_FOUND", "Habitation not found", 404)
    return habitation


def _geometry_expr(geometry_geojson: dict):
    raw = func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry_geojson)), 4326)
    return cast(func.ST_MakeValid(raw), Geometry(geometry_type="GEOMETRY", srid=4326))


# ---------------------------------------------------------------------------
# MANUAL_DRAW: a small, synchronous layer created from geometry already in
# the request body (design's layer_source.MANUAL_DRAW) — distinct from
# upload_gis_layer_container()/process_gis_file_upload() below, which is the
# async, file-based path (source=UPLOAD, API-34 with target=GIS_LAYER).
# ---------------------------------------------------------------------------
async def create_manual_layer(
    db: AsyncSession,
    habitation_id: uuid.UUID,
    payload: LayerUploadIn,
    user: User,
    source: LayerSource = LayerSource.MANUAL_DRAW,
) -> GISLayer:
    """Synchronous, geometry-already-in-hand layer creation. `source`
    defaults to MANUAL_DRAW (the original caller, API-33's POST
    /habitations/{id}/layers) but the automation module (app/automation/
    service.py) passes LayerSource.OSM_OVERPASS for a layer it built from a
    live Overpass query, so it's labelled correctly rather than lying about
    where the geometry came from."""
    await _get_habitation_or_404(db, habitation_id)

    features = payload.geojson.get("features")
    if payload.geojson.get("type") != "FeatureCollection" or not isinstance(features, list) or not features:
        raise AppError(
            "GEOJSON_INVALID", "geojson must be a FeatureCollection with at least one feature", 400
        )

    first_geom_type = features[0].get("geometry", {}).get("type", "Unknown")

    layer = GISLayer(
        habitation_id=habitation_id,
        layer_name=payload.layer_name,
        layer_type=payload.layer_type,
        geometry_type=first_geom_type,
        source=source,
        status=LayerStatus.PROCESSING,
        created_by=user.id,
    )
    db.add(layer)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise AppError(
            "LAYER_NAME_DUPLICATE", f"A layer named '{payload.layer_name}' already exists here", 409
        ) from exc

    for feature in features:
        geometry = feature.get("geometry")
        if not geometry:
            raise AppError("GEOJSON_INVALID", "Every feature must have a geometry", 400)
        db.add(
            GISFeature(
                layer_id=layer.id,
                geom=_geometry_expr(geometry),
                properties=feature.get("properties") or {},
            )
        )
    await db.flush()

    await _enforce_boundary_integrity(db, layer)
    return layer


async def _compute_total_length_km(db: AsyncSession, layer_id: uuid.UUID) -> float | None:
    """Real-world length via PostGIS's geography cast — geodesically
    accurate anywhere on Earth, unlike a flat-projection estimate, and
    computed the same way no matter how the feature's geometry arrived
    (manually drawn, pasted GeoJSON, file upload, or an automated fetch).
    Summed over whichever features are actually line geometry; None (not
    0) when a layer has none at all, since "road length" is meaningless
    for a point/polygon layer rather than genuinely zero.
    """
    has_any_line = await db.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM gis_features WHERE layer_id = :layer_id "
            "AND GeometryType(geom) IN ('LINESTRING', 'MULTILINESTRING'))"
        ),
        {"layer_id": str(layer_id)},
    )
    if not has_any_line:
        return None
    total_m = await db.scalar(
        text(
            "SELECT COALESCE(SUM(ST_Length(geography(geom))), 0) FROM gis_features "
            "WHERE layer_id = :layer_id AND GeometryType(geom) IN ('LINESTRING', 'MULTILINESTRING')"
        ),
        {"layer_id": str(layer_id)},
    )
    return round(float(total_m) / 1000, 3)


async def _enforce_boundary_integrity(db: AsyncSession, layer: GISLayer) -> None:
    habitation = await db.get(Habitation, layer.habitation_id)
    total = await db.scalar(select(func.count()).select_from(GISFeature).where(GISFeature.layer_id == layer.id))
    total_length_km = await _compute_total_length_km(db, layer.id)

    if habitation.boundary is None:
        layer.status = LayerStatus.READY
        layer.feature_count = total
        layer.total_length_km = total_length_km
        layer.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return

    outside = await db.scalar(
        text(
            """
            SELECT count(*) FROM gis_features f
            JOIN gis_layers l ON l.id = f.layer_id
            JOIN habitations h ON h.id = l.habitation_id
            WHERE f.layer_id = :layer_id
              AND NOT ST_Within(f.geom, ST_Buffer(h.boundary, :buffer_m)::geometry)
            """
        ),
        {"layer_id": str(layer.id), "buffer_m": BOUNDARY_BUFFER_METRES},
    )

    fraction_outside = (outside / total) if total else 0
    if fraction_outside > OUTSIDE_BOUNDARY_REJECT_FRACTION:
        layer.status = LayerStatus.FAILED
        await db.flush()
        raise AppError(
            "LAYER_OUTSIDE_BOUNDARY",
            f"{outside}/{total} features ({fraction_outside * 100:.1f}%) lie outside the habitation "
            f"boundary buffered by {BOUNDARY_BUFFER_METRES}m",
            422,
        )

    layer.status = LayerStatus.READY
    layer.feature_count = total
    layer.total_length_km = total_length_km
    # Set explicitly rather than relying on the column's onupdate=func.now():
    # an UPDATE's server-generated onupdate value isn't always eagerly
    # re-fetched into the Python object the way an INSERT's server_default
    # is, so serialising `layer` right after this flush can otherwise try a
    # lazy load — which throws MissingGreenlet in an async session.
    layer.updated_at = datetime.now(timezone.utc)
    await db.flush()


# ---------------------------------------------------------------------------
# BG-01: the async file-upload path. create_gis_layer_container() runs
# inside the upload request (mirrors how a PARAMETERS upload is linked to a
# parameter_set_id the client already created); process_gis_file_upload()
# is the worker logic that actually loads the features into it.
# ---------------------------------------------------------------------------
async def create_gis_layer_container(
    db: AsyncSession,
    habitation_id: uuid.UUID,
    upload: DatasetUpload,
    *,
    layer_name: str,
    layer_type: LayerType,
    user: User,
) -> GISLayer:
    """Creates the GISLayer row eagerly, at upload time, in PROCESSING —
    exactly parallel to how the client already picks the target
    parameter_set_id before a PARAMETERS upload starts. The worker fills in
    geometry_type/feature_count/status once it has actually read the file.
    """
    habitation = await _get_habitation_or_404(db, habitation_id)
    if habitation.boundary is None:
        raise AppError(
            "HABITATION_BOUNDARY_REQUIRED",
            "This habitation has no boundary yet; a GIS layer needs one to validate against (BR-06)",
            409,
        )

    layer = GISLayer(
        habitation_id=habitation_id,
        layer_name=layer_name,
        layer_type=layer_type,
        geometry_type="UNKNOWN",
        source=LayerSource.UPLOAD,
        source_ref=upload.original_filename,
        status=LayerStatus.PROCESSING,
        upload_id=upload.id,
        created_by=user.id,
    )
    db.add(layer)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise AppError(
            "LAYER_NAME_DUPLICATE", f"A layer named '{layer_name}' already exists here", 409
        ) from exc
    return layer


async def process_gis_file_upload(db: AsyncSession, upload: DatasetUpload, data: bytes) -> ValidationReport:
    """The core of BG-01. Parses the stored file, reprojects/repairs
    geometry, checks it against the habitation boundary (BR-06), and — only
    if everything passes — bulk-loads gis_features and marks the layer
    READY, all inside the one transaction the caller (tasks_gis.py) commits
    or rolls back as a whole (BR-14: a layer is never half-loaded).
    """
    layer = await db.scalar(select(GISLayer).where(GISLayer.upload_id == upload.id))
    if layer is None:
        raise AppError("GIS_LAYER_CONTAINER_MISSING", "No layer container found for this upload", 500)

    extension = upload.original_filename.rsplit(".", 1)[-1].lower() if "." in upload.original_filename else ""

    result = PipelineResult()
    try:
        parsed = parse_gis_file(data, extension)
    except CRSUndeclaredError:
        layer.status = LayerStatus.FAILED
        result.issues.append(
            Issue(
                Severity.ERROR,
                "CRS_UNDECLARED",
                "file",
                "No coordinate reference system could be determined for this file "
                "(e.g. a shapefile with no .prj) — it is rejected rather than assumed to be WGS84 (BR-07)",
            )
        )
        return await _write_gis_report(db, upload, layer, result)
    except ParseError as exc:
        layer.status = LayerStatus.FAILED
        result.issues.append(Issue(Severity.ERROR, "STRUCTURAL_INVALID", "file", exc.message))
        return await _write_gis_report(db, upload, layer, result)

    layer.srid_original = parsed.srid_original
    layer.geometry_type = parsed.geometry_type
    await _bulk_insert_features(db, layer.id, parsed)
    await db.flush()

    habitation = await db.get(Habitation, layer.habitation_id)
    outside_fraction, total = await _boundary_outside_fraction(db, layer.id, habitation)

    if total and outside_fraction > OUTSIDE_BOUNDARY_REJECT_FRACTION:
        # BR-14 / "never half-loaded": reject the WHOLE layer by deleting
        # what was just inserted, in this SAME transaction, rather than
        # relying on the caller to roll back — the validation_report
        # explaining why still needs to persist, and a transaction can't
        # undo part of itself while keeping the rest.
        await db.execute(text("DELETE FROM gis_features WHERE layer_id = :layer_id"), {"layer_id": str(layer.id)})
        layer.status = LayerStatus.FAILED
        layer.feature_count = 0
        result.issues.append(
            Issue(
                Severity.ERROR,
                "LAYER_OUTSIDE_BOUNDARY",
                "file",
                f"{outside_fraction * 100:.1f}% of features lie outside the habitation boundary "
                f"buffered by {BOUNDARY_BUFFER_METRES}m — the whole layer is rejected (BR-06), nothing is kept",
                expected_range=f"<= {OUTSIDE_BOUNDARY_REJECT_FRACTION * 100:.0f}% outside",
                observed_value=f"{outside_fraction * 100:.1f}%",
            )
        )
        return await _write_gis_report(db, upload, layer, result)

    if total:
        # Between 0% and 30% outside: WARNING issues, layer still loads.
        outside_count = round(outside_fraction * total)
        if outside_count:
            result.issues.append(
                Issue(
                    Severity.WARNING,
                    "FEATURES_OUTSIDE_BOUNDARY",
                    "file",
                    f"{outside_count}/{total} features ({outside_fraction * 100:.1f}%) lie outside the "
                    f"habitation boundary buffered by {BOUNDARY_BUFFER_METRES}m, but under the 30% "
                    "threshold that would reject the whole layer",
                )
            )

    layer.feature_count = len(parsed.features)
    layer.total_length_km = (
        sum(f.length_m or 0 for f in parsed.features) / 1000 if parsed.geometry_type.endswith("LineString") else None
    )
    layer.status = LayerStatus.READY
    layer.updated_at = datetime.now(timezone.utc)
    return await _write_gis_report(db, upload, layer, result)


async def _bulk_insert_features(db: AsyncSession, layer_id: uuid.UUID, parsed: ParsedLayer) -> None:
    if not parsed.features:
        return
    insert_stmt = text(
        """
        INSERT INTO gis_features (layer_id, geom, length_m, properties)
        VALUES (
            :layer_id,
            ST_SetSRID(ST_MakeValid(ST_GeomFromText(:wkt)), 4326),
            :length_m,
            CAST(:properties AS jsonb)
        )
        """
    )
    await db.execute(
        insert_stmt,
        [
            {
                "layer_id": str(layer_id),
                "wkt": f.wkt,
                "length_m": f.length_m,
                "properties": json.dumps(f.properties),
            }
            for f in parsed.features
        ],
    )


async def _boundary_outside_fraction(
    db: AsyncSession, layer_id: uuid.UUID, habitation: Habitation
) -> tuple[float, int]:
    if habitation.boundary is None:
        return 0.0, 0
    total = await db.scalar(select(func.count()).select_from(GISFeature).where(GISFeature.layer_id == layer_id))
    if not total:
        return 0.0, 0
    outside = await db.scalar(
        text(
            """
            SELECT count(*) FROM gis_features f
            JOIN gis_layers l ON l.id = f.layer_id
            JOIN habitations h ON h.id = l.habitation_id
            WHERE f.layer_id = :layer_id
              AND NOT ST_Within(f.geom, ST_Buffer(h.boundary, :buffer_m)::geometry)
            """
        ),
        {"layer_id": str(layer_id), "buffer_m": BOUNDARY_BUFFER_METRES},
    )
    return (outside / total), total


async def _write_gis_report(
    db: AsyncSession, upload: DatasetUpload, layer: GISLayer, result: PipelineResult
) -> ValidationReport:
    outcome = (
        ValidationResult.FAIL
        if result.error_count > 0
        else (ValidationResult.PASS_WITH_WARNINGS if result.warning_count > 0 else ValidationResult.PASS)
    )
    report = ValidationReport(
        habitation_id=upload.habitation_id,
        upload_id=upload.id,
        gis_layer_id=layer.id,
        scope=ValidationScope.GIS_LAYER,
        result=outcome,
        error_count=result.error_count,
        warning_count=result.warning_count,
        triggered_by=upload.uploaded_by,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(report)
    await db.flush()
    for issue in result.issues:
        db.add(
            ValidationIssue(
                report_id=report.id,
                severity=issue.severity,
                code=issue.code,
                category=issue.category,
                field_path=issue.field_path,
                message=issue.message,
                observed_value=issue.observed_value,
                expected_range=issue.expected_range,
                suggested_fix=issue.suggested_fix,
            )
        )
    await db.flush()
    return report


# ---------------------------------------------------------------------------
# Reads: list/get/features/map/tiles, and the two write endpoints PATCH/DELETE
# ---------------------------------------------------------------------------
async def list_layers(db: AsyncSession, habitation_id: uuid.UUID) -> list[GISLayer]:
    await _get_habitation_or_404(db, habitation_id)
    result = await db.scalars(
        select(GISLayer).where(GISLayer.habitation_id == habitation_id).order_by(GISLayer.created_at.desc())
    )
    return list(result)


async def get_layer_or_404(db: AsyncSession, layer_id: uuid.UUID) -> GISLayer:
    layer = await db.get(GISLayer, layer_id)
    if layer is None:
        raise AppError("LAYER_NOT_FOUND", "Layer not found", 404)
    return layer


async def update_layer(
    db: AsyncSession, layer: GISLayer, *, layer_name: str | None, style: dict | None, z_index: int | None, is_visible_default: bool | None
) -> GISLayer:
    if layer_name is not None:
        layer.layer_name = layer_name
    if style is not None:
        layer.style = style
    if z_index is not None:
        layer.z_index = z_index
    if is_visible_default is not None:
        layer.is_visible_default = is_visible_default
    layer.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise AppError("LAYER_NAME_DUPLICATE", "A layer with this name already exists here", 409) from exc
    return layer


async def delete_layer(db: AsyncSession, layer: GISLayer) -> None:
    await db.delete(layer)  # ON DELETE CASCADE on gis_features.layer_id
    await db.flush()


async def get_features_geojson(
    db: AsyncSession, habitation_id: uuid.UUID, layer_id: uuid.UUID | None
) -> dict[str, Any]:
    await _get_habitation_or_404(db, habitation_id)

    stmt = (
        select(GISFeature.id, GISFeature.properties, func.ST_AsGeoJSON(GISFeature.geom))
        .join(GISLayer, GISLayer.id == GISFeature.layer_id)
        .where(GISLayer.habitation_id == habitation_id)
    )
    if layer_id is not None:
        stmt = stmt.where(GISFeature.layer_id == layer_id)

    rows = (await db.execute(stmt)).all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": feature_id,
                "properties": properties or {},
                "geometry": json.loads(geom_json),
            }
            for feature_id, properties, geom_json in rows
        ],
    }


DEFAULT_MAP_FEATURE_LIMIT = 20_000


async def get_map_overlay(
    db: AsyncSession,
    habitation_id: uuid.UUID,
    *,
    layer_types: list[LayerType] | None,
    bbox: tuple[float, float, float, float] | None,
    limit: int,
) -> dict[str, Any]:
    """API-43: several layers in one response, each either inline GeoJSON or
    a tile_url when its feature count in the viewport exceeds `limit`
    (AD-16) — never a layer belonging to another habitation, since every
    query below is scoped by habitation_id."""
    habitation = await _get_habitation_or_404(db, habitation_id)

    stmt = select(GISLayer).where(
        GISLayer.habitation_id == habitation_id,
        GISLayer.status == LayerStatus.READY,
        GISLayer.is_visible_default.is_(True),
    )
    if layer_types:
        stmt = stmt.where(GISLayer.layer_type.in_(layer_types))
    layers = list(await db.scalars(stmt.order_by(GISLayer.z_index)))

    boundary_geojson = None
    habitation_bbox = None
    if habitation.boundary is not None:
        boundary_row = await db.execute(
            select(func.ST_AsGeoJSON(Habitation.boundary), func.ST_XMin(cast(Habitation.boundary, Geometry())),
                   func.ST_YMin(cast(Habitation.boundary, Geometry())), func.ST_XMax(cast(Habitation.boundary, Geometry())),
                   func.ST_YMax(cast(Habitation.boundary, Geometry())))
            .where(Habitation.id == habitation_id)
        )
        geom_json, xmin, ymin, xmax, ymax = boundary_row.one()
        boundary_geojson = json.loads(geom_json)
        habitation_bbox = [xmin, ymin, xmax, ymax]

    layer_payloads = []
    for layer in layers:
        count_in_view = layer.feature_count
        if bbox is not None:
            count_in_view = (
                await db.scalar(
                    select(func.count())
                    .select_from(GISFeature)
                    .where(
                        GISFeature.layer_id == layer.id,
                        func.ST_Intersects(
                            GISFeature.geom,
                            func.ST_MakeEnvelope(bbox[0], bbox[1], bbox[2], bbox[3], 4326),
                        ),
                    )
                )
                or 0
            )

        entry: dict[str, Any] = {
            "layer_id": str(layer.id),
            "layer_type": layer.layer_type.value,
            "layer_name": layer.layer_name,
            "z_index": layer.z_index,
            "style": layer.style,
            "feature_count": count_in_view or 0,
        }
        if (count_in_view or 0) > limit:
            entry["mode"] = "tiles"
            entry["tile_url"] = f"/api/v1/layers/{layer.id}/tiles/{{z}}/{{x}}/{{y}}.mvt"
        else:
            entry["mode"] = "geojson"
            entry["features"] = await get_features_geojson(db, habitation_id, layer.id)
        layer_payloads.append(entry)

    return {
        "habitation_id": str(habitation_id),
        "bbox": list(bbox) if bbox is not None else habitation_bbox,
        "boundary": boundary_geojson,
        "layers": layer_payloads,
        "cache": {"hit": False, "ttl_seconds": 600},
    }


async def get_tile_mvt(db: AsyncSession, layer_id: uuid.UUID, z: int, x: int, y: int) -> bytes:
    """API-44: ST_AsMVT via ST_TileEnvelope. z/x/y are bound as parameters,
    never string-formatted into SQL."""
    await get_layer_or_404(db, layer_id)
    row = await db.execute(
        text(
            """
            SELECT ST_AsMVT(tile, 'features', 4096, 'geom') FROM (
                SELECT
                    id,
                    properties,
                    ST_AsMVTGeom(
                        ST_Transform(geom, 3857),
                        ST_TileEnvelope(:z, :x, :y),
                        4096, 64, true
                    ) AS geom
                FROM gis_features
                WHERE layer_id = :layer_id
                  AND geom && ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)
            ) AS tile
            WHERE tile.geom IS NOT NULL
            """
        ),
        {"z": z, "x": x, "y": y, "layer_id": str(layer_id)},
    )
    return row.scalar() or b""
