import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.simulation.models import FindingSeverity, RunStatus, RunType


class CoefficientSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = None
    habitation_type_scope: str | None = None
    coefficients: dict[str, Any]
    is_default: bool = False


class CoefficientSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    habitation_type_scope: str | None
    coefficients: dict[str, Any]
    is_default: bool
    created_by: uuid.UUID
    created_at: datetime


class SimulationCreate(BaseModel):
    parameter_set_id: uuid.UUID | None = None
    coefficient_set_id: uuid.UUID | None = None
    label: str | None = None
    horizon_years: int = Field(default=20, ge=1, le=30)
    param_overrides: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class SimulationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    parameter_set_id: uuid.UUID
    coefficient_set_id: uuid.UUID
    engine_version: str
    run_type: str
    parent_run_id: uuid.UUID | None
    label: str | None
    horizon_years: int
    step_granularity: str
    status: str
    progress_pct: int
    error_detail: str | None
    created_by: uuid.UUID
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class RunFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: uuid.UUID
    code: str
    severity: str
    numeric_value: float | None
    year_index: int | None
    message: str


class SimulationYearlyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    year_index: int
    population_end: int
    waste_total_tpy: float
    waste_collected_tpy: float
    waste_uncollected_tpy: float
    treated_tpy: float
    recovered_tpy: float
    landfilled_tpy: float
    landfill_remaining_tonnes: float
    avg_coverage_pct: float
    peak_vehicle_shortfall: int
    opex_inr: float
    capex_inr: float
    total_cost_inr: float
    discounted_cost_inr: float
    ghg_tco2e: float
    recovery_rate_pct: float
