import uuid

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


from app.auth.models import User
from app.core.db import get_db
from app.core.deps import check_habitation_access, get_current_user
from app.core.errors import AppError
from app.gis import service
from app.gis.models import LayerType
from app.gis.schemas import GISLayerOut, LayerPatchIn, LayerUploadIn
from app.habitation.models import AccessLevel
from app.habitation.service import get_habitation_or_404, ensure_read_access

router = APIRouter(tags=["gis"])


@router.post("/api/v1/habitations/{habitation_id}/layers", status_code=201)
async def create_manual_layer(
    habitation_id: uuid.UUID,
    payload: LayerUploadIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """MANUAL_DRAW: geometry already in the request body. For a real file
    (GeoJSON/KML/zipped Shapefile), use POST /habitations/{id}/uploads with
    target=GIS_LAYER instead (async, BG-01)."""
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.EDITOR)
    layer = await service.create_manual_layer(db, habitation_id, payload, current_user)
    await db.commit()
    return {"success": True, "data": GISLayerOut.model_validate(layer)}


@router.get("/api/v1/habitations/{habitation_id}/layers")
async def list_layers(
    habitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, current_user, habitation)
    layers = await service.list_layers(db, habitation_id)
    return {"success": True, "data": [GISLayerOut.model_validate(layer) for layer in layers]}


@router.get("/api/v1/layers/{layer_id}")
async def get_layer(
    layer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    layer = await service.get_layer_or_404(db, layer_id)
    habitation = await get_habitation_or_404(db, layer.habitation_id)
    await ensure_read_access(db, current_user, habitation)
    return {"success": True, "data": GISLayerOut.model_validate(layer)}


@router.patch("/api/v1/layers/{layer_id}")
async def patch_layer(
    layer_id: uuid.UUID,
    payload: LayerPatchIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    layer = await service.get_layer_or_404(db, layer_id)
    await check_habitation_access(db, current_user, layer.habitation_id, AccessLevel.EDITOR)
    layer = await service.update_layer(
        db,
        layer,
        layer_name=payload.layer_name,
        style=payload.style,
        z_index=payload.z_index,
        is_visible_default=payload.is_visible_default,
    )
    await db.commit()
    return {"success": True, "data": GISLayerOut.model_validate(layer)}


@router.delete("/api/v1/layers/{layer_id}", status_code=204)
async def delete_layer(
    layer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    layer = await service.get_layer_or_404(db, layer_id)
    await check_habitation_access(db, current_user, layer.habitation_id, AccessLevel.EDITOR)
    await service.delete_layer(db, layer)
    await db.commit()
    return Response(status_code=204)


@router.get("/api/v1/habitations/{habitation_id}/features")
async def get_features(
    habitation_id: uuid.UUID,
    layer_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, current_user, habitation)
    geojson = await service.get_features_geojson(db, habitation_id, layer_id)
    return {"success": True, "data": geojson}


@router.get("/api/v1/layers/{layer_id}/features")
async def get_layer_features(
    layer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    layer = await service.get_layer_or_404(db, layer_id)
    habitation = await get_habitation_or_404(db, layer.habitation_id)
    await ensure_read_access(db, current_user, habitation)
    geojson = await service.get_features_geojson(db, layer.habitation_id, layer_id)
    return {"success": True, "data": geojson}


@router.get("/api/v1/habitations/{habitation_id}/map")
async def get_map(
    habitation_id: uuid.UUID,
    layers: str | None = Query(default=None, description="Comma-separated layer_type values"),
    bbox: str | None = Query(default=None, description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(default=20_000, ge=1, le=200_000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, current_user, habitation)

    layer_types: list[LayerType] | None = None
    if layers:
        try:
            layer_types = [LayerType(v.strip()) for v in layers.split(",") if v.strip()]
        except ValueError as exc:
            raise AppError("UNKNOWN_LAYER_TYPE", f"Unknown layer_type in 'layers': {exc}", 400) from exc

    bbox_tuple = None
    if bbox:
        try:
            parts = [float(v) for v in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError("bbox must have exactly 4 numbers")
            bbox_tuple = (parts[0], parts[1], parts[2], parts[3])
        except ValueError as exc:
            raise AppError("INVALID_BBOX", f"'{bbox}' is not minLon,minLat,maxLon,maxLat: {exc}", 400) from exc

    data = await service.get_map_overlay(db, habitation_id, layer_types=layer_types, bbox=bbox_tuple, limit=limit)
    return {"success": True, "data": data}


@router.get("/api/v1/layers/{layer_id}/tiles/{z}/{x}/{y}.mvt")
async def get_tile(
    layer_id: uuid.UUID,
    z: int,
    x: int,
    y: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    layer = await service.get_layer_or_404(db, layer_id)
    habitation = await get_habitation_or_404(db, layer.habitation_id)
    await ensure_read_access(db, current_user, habitation)
    tile_bytes = await service.get_tile_mvt(db, layer_id, z, x, y)
    return Response(
        content=tile_bytes,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.post("/api/v1/habitations/{habitation_id}/layers/import-osm", status_code=202)
async def import_osm_endpoint(
    habitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.EDITOR)
    result = await service.import_osm_for_habitation(db, habitation_id, current_user)
    return {"success": True, "data": result}


class GeocodeIn(BaseModel):
    query: str


@router.post("/api/v1/habitations/{habitation_id}/geocode")
async def geocode_endpoint(
    habitation_id: uuid.UUID,
    payload: GeocodeIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_habitation_access(db, current_user, habitation_id, AccessLevel.EDITOR)
    result = await service.geocode_place(db, habitation_id, payload.query)
    return {"success": True, "data": result}

