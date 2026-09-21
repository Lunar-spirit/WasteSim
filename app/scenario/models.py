import enum
import uuid

from geoalchemy2 import Geography
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    simulation_run_id = Column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type = Column(String(40), nullable=False)
    start_month = Column(SmallInteger, nullable=False)
    duration_months = Column(SmallInteger, nullable=False, default=1)
    recovery_months = Column(SmallInteger, nullable=False, default=0)
    severity = Column(String(20), nullable=False, default=EventSeverity.MODERATE.value)
    affected_area = Column(Geography(geometry_type="MULTIPOLYGON", srid=4326), nullable=True)
    impact_params = Column(JSONB, nullable=False, default=dict)
    derived_impacts = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    simulation_run = relationship("SimulationRun", back_populates="events")
