import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.parameters.models import ParameterSetStatus


class ParameterSetCreate(BaseModel):
    clone_from_version: int | None = None
    change_note: str | None = None


class ParameterSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    version_no: int
    status: ParameterSetStatus
    cloned_from_id: uuid.UUID | None
    change_note: str | None
    created_by: uuid.UUID
    created_at: datetime


class ParameterSetDetailOut(ParameterSetOut):
    categories: dict[str, dict[str, Any]] = {}
    waste_baseline: dict[str, Any] | None = None


class WasteBaselineIn(BaseModel):
    per_capita_generation_kg_day: Any | None = None
    total_generation_tpd: Any | None = None
    composition: dict[str, Any] | None = None


class ParameterDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str
    param_key: str
    display_label: str
    unit: str | None
    data_type: str
    min_value: float | None
    max_value: float | None
    is_required: bool
    normalization_rule: str | None
