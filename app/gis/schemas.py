import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.gis.models import LayerSource, LayerStatus, LayerType


class LayerUploadIn(BaseModel):
    """Body for the synchronous MANUAL_DRAW path (POST /habitations/{id}/layers)
    — geometry already in hand, no file. See app/ingestion/router.py's
    POST /habitations/{id}/uploads for the async, file-based UPLOAD path."""

    layer_name: str
    layer_type: LayerType
    geojson: dict[str, Any]  # a GeoJSON FeatureCollection


class LayerPatchIn(BaseModel):
    layer_name: str | None = None
    style: dict[str, Any] | None = None
    z_index: int | None = None
    is_visible_default: bool | None = None


class GISLayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    layer_name: str
    layer_type: LayerType
    geometry_type: str
    source: LayerSource
    source_ref: str | None
    status: LayerStatus
    is_visible_default: bool
    z_index: int
    style: dict[str, Any]
    feature_count: int
    total_length_km: float | None
    srid_original: int | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
