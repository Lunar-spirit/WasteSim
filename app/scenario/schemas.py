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
