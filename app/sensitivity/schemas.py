import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.optimization.models import AnalysisStatus


class SensitivitySweepIn(BaseModel):
    base_run_id: uuid.UUID
    param_path: str
    values: list[float] = Field(min_length=2, max_length=25)
    indicators: list[str] = Field(default_factory=list)


class SensitivityPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    swept_value: float
    child_run_id: uuid.UUID | None
    indicator_values: dict[str, Any]
    elasticity: dict[str, float] | None
    error: str | None


class SensitivityAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    base_run_id: uuid.UUID
    param_path: str
    swept_values: list[float]
    indicators: list[str]
    status: AnalysisStatus
    created_at: datetime
    completed_at: datetime | None
