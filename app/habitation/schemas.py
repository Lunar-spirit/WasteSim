import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.habitation.models import HabitationStatus, HabitationType


class HabitationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    habitation_type: HabitationType
    state: str = Field(min_length=1, max_length=128)
    district: str = Field(min_length=1, max_length=128)
    country: str = "India"
    # GeoJSON Point / MultiPolygon. Optional: area_sqkm is computed from
    # boundary when boundary is given and area_sqkm is omitted.
    centroid_geojson: dict[str, Any] | None = None
    boundary_geojson: dict[str, Any] | None = None
    area_sqkm: float | None = None


class HabitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    habitation_type: HabitationType
    state: str
    district: str
    country: str
    area_sqkm: float | None
    status: HabitationStatus
    active_parameter_set_id: uuid.UUID | None
    created_by: uuid.UUID
    created_at: datetime


class HabitationDetailOut(HabitationOut):
    active_parameter_set_summary: dict[str, Any] | None = None


class HabitationUpdate(BaseModel):
    name: str | None = None
    habitation_type: HabitationType | None = None
    state: str | None = None
    district: str | None = None
    country: str | None = None
    boundary_geojson: dict[str, Any] | None = None
    centroid_geojson: dict[str, Any] | None = None
    area_sqkm: float | None = None


class MemberCreate(BaseModel):
    user_id: uuid.UUID
    access_level: str = Field(description="OWNER, EDITOR, or VIEWER")


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    access_level: str
    created_at: datetime

