"""Daily Waste Collection & Operational Logging. Field-recorded reality for
a habitation — what a crew actually collected on a given day — kept
separate from parameters/parameter_sets: this is not an input the
simulation engine reads (module rule 8, app/engine/ takes only frozen
parameter values), it's an operational record a planner enters and can
correct later, so unlike simulation_results/simulation_yearly it is a plain
upsert-by-natural-key table, not insert-only.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AnomalyFlag(str, enum.Enum):
    NORMAL = "NORMAL"
    MONSOON_FLOOD = "MONSOON_FLOOD"
    FESTIVAL_SURGE = "FESTIVAL_SURGE"
    WORKER_STRIKE = "WORKER_STRIKE"
    BREAKDOWN = "BREAKDOWN"


class DailyWasteLog(Base):
    __tablename__ = "daily_waste_logs"
    __table_args__ = (
        # One log per habitation per day — a resubmission for the same day
        # is an update (POST .../daily-logs is create-or-update), not a
        # second row.
        UniqueConstraint("habitation_id", "log_date", name="uq_daily_waste_log_habitation_date"),
        CheckConstraint("total_collected_tonnes >= 0", name="ck_daily_log_total_collected_nonneg"),
        CheckConstraint("organic_tonnes >= 0", name="ck_daily_log_organic_nonneg"),
        CheckConstraint("dry_recyclable_tonnes >= 0", name="ck_daily_log_dry_recyclable_nonneg"),
        CheckConstraint("hazardous_tonnes IS NULL OR hazardous_tonnes >= 0", name="ck_daily_log_hazardous_nonneg"),
        CheckConstraint("vehicles_deployed >= 0", name="ck_daily_log_vehicles_nonneg"),
        CheckConstraint("trips_completed >= 0", name="ck_daily_log_trips_nonneg"),
        CheckConstraint(
            "diesel_consumed_litres IS NULL OR diesel_consumed_litres >= 0",
            name="ck_daily_log_diesel_nonneg",
        ),
        CheckConstraint(
            "collection_coverage_pct_observed IS NULL "
            "OR collection_coverage_pct_observed BETWEEN 0 AND 100",
            name="ck_daily_log_coverage_pct_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE")
    )
    logged_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    log_date: Mapped[date] = mapped_column(Date, index=True)
    total_collected_tonnes: Mapped[float] = mapped_column(Numeric(10, 3))
    organic_tonnes: Mapped[float] = mapped_column(Numeric(10, 3))
    dry_recyclable_tonnes: Mapped[float] = mapped_column(Numeric(10, 3))
    hazardous_tonnes: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    vehicles_deployed: Mapped[int] = mapped_column(Integer)
    trips_completed: Mapped[int] = mapped_column(Integer)
    diesel_consumed_litres: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    collection_coverage_pct_observed: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    anomaly_flag: Mapped[AnomalyFlag] = mapped_column(
        Enum(AnomalyFlag, name="daily_log_anomaly_flag"), default=AnomalyFlag.NORMAL
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
