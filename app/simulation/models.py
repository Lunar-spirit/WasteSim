import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class HabitationTypeScope(str, enum.Enum):
    VILLAGE = "VILLAGE"
    WARD = "WARD"
    TOWN = "TOWN"
    CITY = "CITY"


class RunType(str, enum.Enum):
    BASE = "BASE"
    SCENARIO = "SCENARIO"
    SENSITIVITY = "SENSITIVITY"
    OPTIMIZED = "OPTIMIZED"


class StepGranularity(str, enum.Enum):
    MONTHLY = "MONTHLY"


class RunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FindingSeverity(str, enum.Enum):
    INFO = "INFO"
    WATCH = "WATCH"
    CRITICAL = "CRITICAL"


class CoefficientSet(Base):
    __tablename__ = "coefficient_sets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(80), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    habitation_type_scope = Column(String(32), nullable=True)
    coefficients = Column(JSONB, nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    runs = relationship("SimulationRun", back_populates="coefficient_set")


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id = Column(UUID(as_uuid=True), ForeignKey("habitations.id"), nullable=False, index=True)
    parameter_set_id = Column(
        UUID(as_uuid=True), ForeignKey("parameter_sets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    coefficient_set_id = Column(
        UUID(as_uuid=True), ForeignKey("coefficient_sets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    engine_version = Column(String(20), nullable=False, default="1.0.0")
    run_type = Column(String(32), nullable=False, default=RunType.BASE.value, index=True)
    parent_run_id = Column(UUID(as_uuid=True), ForeignKey("simulation_runs.id"), nullable=True, index=True)
    label = Column(String(120), nullable=True)
    horizon_years = Column(SmallInteger, nullable=False, default=20)
    step_granularity = Column(String(20), nullable=False, default=StepGranularity.MONTHLY.value)
    status = Column(String(20), nullable=False, default=RunStatus.QUEUED.value, index=True)
    param_overrides = Column(JSONB, nullable=False, default=dict)
    config = Column(JSONB, nullable=False, default=dict)
    job_id = Column(String(64), nullable=True)
    progress_pct = Column(SmallInteger, nullable=False, default=0)
    error_detail = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    coefficient_set = relationship("CoefficientSet", back_populates="runs")
    monthly_results = relationship(
        "SimulationResult", back_populates="run", cascade="all, delete-orphan", order_by="SimulationResult.month_index"
    )
    yearly_results = relationship(
        "SimulationYearly", back_populates="run", cascade="all, delete-orphan", order_by="SimulationYearly.year_index"
    )
    findings = relationship("RunFinding", back_populates="run", cascade="all, delete-orphan")
    events = relationship("ScenarioEvent", back_populates="simulation_run", cascade="all, delete-orphan")
    budget_lines = relationship("BudgetLine", back_populates="simulation_run", cascade="all, delete-orphan")


class SimulationResult(Base):
    __tablename__ = "simulation_results"
    __table_args__ = (UniqueConstraint("run_id", "month_index", name="uq_simulation_results_run_month"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    month_index = Column(SmallInteger, nullable=False)
    year_index = Column(SmallInteger, nullable=False, index=True)
    calendar_month = Column(SmallInteger, nullable=False)
    population = Column(Integer, nullable=False)
    population_effective = Column(Integer, nullable=False)
    per_capita_kg_day = Column(Numeric(6, 3), nullable=False)
    waste_domestic_tpd = Column(Numeric(12, 3), nullable=False)
    waste_bulk_tpd = Column(Numeric(12, 3), nullable=False)
    waste_industrial_tpd = Column(Numeric(12, 3), nullable=False)
    waste_total_tpd = Column(Numeric(12, 3), nullable=False)
    composition = Column(JSONB, nullable=False)
    collection_coverage_pct = Column(Numeric(5, 2), nullable=False)
    accessibility_index = Column(Numeric(5, 4), nullable=False)
    waste_collected_tpd = Column(Numeric(12, 3), nullable=False)
    waste_uncollected_tpd = Column(Numeric(12, 3), nullable=False)
    segregation_pct = Column(Numeric(5, 2), nullable=False)
    organic_treated_tpd = Column(Numeric(12, 3), nullable=False)
    recyclables_recovered_tpd = Column(Numeric(12, 3), nullable=False)
    compost_output_tpd = Column(Numeric(12, 3), nullable=False)
    treatment_capacity_tpd = Column(Numeric(12, 3), nullable=False)
    treatment_utilization_pct = Column(Numeric(5, 2), nullable=False)
    to_landfill_tpd = Column(Numeric(12, 3), nullable=False)
    landfill_cumulative_tonnes = Column(Numeric(16, 2), nullable=False)
    landfill_remaining_tonnes = Column(Numeric(16, 2), nullable=False)
    vehicles_required = Column(SmallInteger, nullable=False)
    vehicles_have = Column(SmallInteger, nullable=False)
    vehicle_shortfall = Column(SmallInteger, nullable=False)
    opex_inr = Column(Numeric(16, 2), nullable=False)
    capex_inr = Column(Numeric(16, 2), nullable=False, default=0)
    ghg_tco2e = Column(Numeric(14, 3), nullable=False)
    active_event_codes = Column(JSONB, nullable=False, default=list)
    extra = Column(JSONB, nullable=False, default=dict)

    run = relationship("SimulationRun", back_populates="monthly_results")


class SimulationYearly(Base):
    __tablename__ = "simulation_yearly"
    __table_args__ = (UniqueConstraint("run_id", "year_index", name="uq_simulation_yearly_run_year"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year_index = Column(SmallInteger, nullable=False)
    population_end = Column(Integer, nullable=False)
    waste_total_tpy = Column(Numeric(14, 2), nullable=False)
    waste_collected_tpy = Column(Numeric(14, 2), nullable=False)
    waste_uncollected_tpy = Column(Numeric(14, 2), nullable=False)
    treated_tpy = Column(Numeric(14, 2), nullable=False)
    recovered_tpy = Column(Numeric(14, 2), nullable=False)
    landfilled_tpy = Column(Numeric(14, 2), nullable=False)
    landfill_remaining_tonnes = Column(Numeric(16, 2), nullable=False)
    avg_coverage_pct = Column(Numeric(5, 2), nullable=False)
    peak_vehicle_shortfall = Column(SmallInteger, nullable=False)
    opex_inr = Column(Numeric(16, 2), nullable=False)
    capex_inr = Column(Numeric(16, 2), nullable=False)
    total_cost_inr = Column(Numeric(16, 2), nullable=False)
    discounted_cost_inr = Column(Numeric(16, 2), nullable=False)
    ghg_tco2e = Column(Numeric(14, 3), nullable=False)
    recovery_rate_pct = Column(Numeric(5, 2), nullable=False)

    run = relationship("SimulationRun", back_populates="yearly_results")


class RunFinding(Base):
    __tablename__ = "run_findings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code = Column(String(60), nullable=False)
    severity = Column(String(20), nullable=False, default=FindingSeverity.INFO.value)
    numeric_value = Column(Numeric(18, 3), nullable=True)
    year_index = Column(SmallInteger, nullable=True)
    message = Column(Text, nullable=False)

    run = relationship("SimulationRun", back_populates="findings")
