import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.scenario.models import EventSeverity, EventType


class EventIn(BaseModel):
    event_type: EventType
    start_month: int = Field(ge=1, le=240)
    duration_months: int = Field(default=1, ge=1)
    recovery_months: int = Field(default=0, ge=0)
    severity: EventSeverity = EventSeverity.MODERATE
    affected_area: dict[str, Any] | None = None  # GeoJSON (Multi)Polygon
    impact_params: dict[str, Any] = Field(default_factory=dict)


class ScenarioCreateIn(BaseModel):
    label: str | None = None
    events: list[EventIn] = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class ScenarioEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: EventType
    start_month: int
    duration_months: int
    recovery_months: int
    severity: EventSeverity
    impact_params: dict[str, Any]
    derived_impacts: dict[str, Any]
    created_at: datetime


class ImpactPreviewIn(BaseModel):
    event_type: EventType
    affected_area: dict[str, Any]


class ComparativePreviewIn(BaseModel):
    """POST /api/v1/scenarios/preview — an instant, synchronous base-vs-
    shocked comparison (see app/scenario/service.py's
    preview_comparative_impact for why this never touches simulation_runs/
    simulation_results/simulation_yearly: those are insert-only, real-run
    tables, rule #2, and this endpoint persists nothing at all)."""

    habitation_id: uuid.UUID
    base_run_id: uuid.UUID
    event_type: EventType
    severity_intensity: EventSeverity = EventSeverity.MODERATE
    duration_weeks: int = Field(ge=1, le=104)
    start_month: int = Field(ge=1, le=240)
    apply_full_boundary: bool = False
    custom_polygon_geojson: dict[str, Any] | None = None


class ComparativePreviewPoint(BaseModel):
    month: int
    base_collected_tpd: float
    scenario_collected_tpd: float
    base_opex_inr: float
    scenario_opex_inr: float
    uncollected_backlog_tonnes: float


class ComparativePreviewOut(BaseModel):
    event_type: EventType
    severity_intensity: EventSeverity
    duration_months: int
    start_month: int
    horizon_months: int
    series: list[ComparativePreviewPoint]
    peak_backlog_tonnes: float
    net_financial_penalty_inr: float
    recovery_time_weeks: float | None
    notes: list[str]
