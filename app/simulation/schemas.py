import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.simulation.models import RunStatus, RunType


class SimulationCreateIn(BaseModel):
    run_type: RunType = RunType.BASE
    label: str | None = None
    parameter_set_id: uuid.UUID | None = None
    coefficient_set_id: uuid.UUID | None = None
    horizon_years: int = Field(default=20, ge=1, le=30)
    param_overrides: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class SimulationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    parameter_set_id: uuid.UUID
    coefficient_set_id: uuid.UUID
    engine_version: str
    run_type: RunType
    parent_run_id: uuid.UUID | None
    label: str | None
    horizon_years: int
    status: RunStatus
    param_overrides: dict[str, Any]
    config: dict[str, Any]
    job_id: str | None
    progress_pct: int
    error_detail: str | None
    created_by: uuid.UUID
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class RunFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    severity: str
    numeric_value: float | None
    year_index: int | None
    message: str
