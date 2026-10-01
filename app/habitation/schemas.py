import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.habitation.models import AccessLevel, HabitationStatus, HabitationType


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


class HabitationMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    user_id: uuid.UUID
    access_level: AccessLevel
    created_at: datetime


class HabitationMemberAdminOut(HabitationMemberOut):
    """Same shape a member row has, plus who the user actually is — this
    is the ADMIN-facing listing; nothing else in the app lists members."""

    user_email: str
    user_full_name: str


class GrantAccessIn(BaseModel):
    email: EmailStr
    access_level: AccessLevel
