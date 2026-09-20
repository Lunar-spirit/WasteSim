import enum
import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, SmallInteger, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EventType(str, enum.Enum):
    FLOOD = "FLOOD"
    LANDSLIDE = "LANDSLIDE"
    HEAVY_MONSOON = "HEAVY_MONSOON"
    ROAD_BLOCKAGE = "ROAD_BLOCKAGE"
    POPULATION_SURGE = "POPULATION_SURGE"
    VEHICLE_BREAKDOWN = "VEHICLE_BREAKDOWN"
    TREATMENT_PLANT_OUTAGE = "TREATMENT_PLANT_OUTAGE"
    FESTIVAL = "FESTIVAL"
    STRIKE = "STRIKE"


class EventSeverity(str, enum.Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ScenarioEvent(Base):
    __tablename__ = "scenario_events"
    __table_args__ = (
        CheckConstraint("start_month BETWEEN 1 AND 240", name="ck_scenario_events_start_month"),
        CheckConstraint("duration_months >= 1", name="ck_scenario_events_duration"),
        Index("ix_scenario_events_run", "simulation_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    simulation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE")
    )
    event_type: Mapped[EventType] = mapped_column(Enum(EventType, name="event_type"))
    start_month: Mapped[int] = mapped_column(SmallInteger)
    duration_months: Mapped[int] = mapped_column(SmallInteger, default=1)
    recovery_months: Mapped[int] = mapped_column(SmallInteger, default=0)
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(EventSeverity, name="event_severity"), default=EventSeverity.MODERATE
    )
    affected_area: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="MULTIPOLYGON", srid=4326), nullable=True
    )
    # As declared by the caller — {"collection_coverage_pct": -35, ...}.
    impact_params: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Spatially computed from affected_area x the ROAD/SETTLEMENT layers
    # (BR-23); overrides impact_params for the keys it produces. Empty when
    # affected_area was never supplied or no relevant layer exists yet.
    derived_impacts: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def effective_impact_params(self) -> dict:
        """derived_impacts wins per-key over impact_params (BR-23: "Derived
        values override declared impact_params; declared values fill in
        only where no geometry exists")."""
        return {**self.impact_params, **self.derived_impacts}
