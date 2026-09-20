import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import DDL

from app.core.db import Base
from app.habitation.models import HabitationType


class RunType(str, enum.Enum):
    BASE = "BASE"
    SCENARIO = "SCENARIO"
    SENSITIVITY = "SENSITIVITY"
    OPTIMIZED = "OPTIMIZED"


class RunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepGranularity(str, enum.Enum):
    MONTHLY = "MONTHLY"


class FindingSeverity(str, enum.Enum):
    INFO = "INFO"
    WATCH = "WATCH"
    CRITICAL = "CRITICAL"


# The nine canonical composition fractions (app.engine.state.CANONICAL_FRACTIONS)
# — one column per fraction, matching design section 4.3 exactly.
COMPOSITION_FRACTIONS = ("organic", "plastic", "paper", "metal", "glass", "textile", "inert", "ewaste", "other")


class CoefficientSet(Base):
    __tablename__ = "coefficient_sets"
    __table_args__ = (
        # At most one default set overall — enforced the same way as "at
        # most one VALIDATED parameter_set per habitation" in Drop 1.
        Index(
            "uq_one_default_coefficient_set", "is_default", unique=True, postgresql_where=text("is_default = true")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    habitation_type_scope: Mapped[HabitationType | None] = mapped_column(
        Enum(HabitationType, name="habitation_type"), nullable=True
    )
    coefficients: Mapped[dict] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    __table_args__ = (
        Index("ix_simulation_runs_habitation_type_created", "habitation_id", "run_type", "created_at"),
        Index("ix_simulation_runs_parent", "parent_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE")
    )
    # RESTRICT, not CASCADE: BR-03 — a parameter set a run points at can
    # never be deleted, and neither can the calibration it used.
    parameter_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parameter_sets.id", ondelete="RESTRICT")
    )
    coefficient_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coefficient_sets.id", ondelete="RESTRICT")
    )
    engine_version: Mapped[str] = mapped_column(String(20))
    run_type: Mapped[RunType] = mapped_column(Enum(RunType, name="run_type"), default=RunType.BASE)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    horizon_years: Mapped[int] = mapped_column(SmallInteger, default=20)
    step_granularity: Mapped[StepGranularity] = mapped_column(
        Enum(StepGranularity, name="step_granularity"), default=StepGranularity.MONTHLY
    )
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, name="run_status"), default=RunStatus.QUEUED)
    param_overrides: Mapped[dict] = mapped_column(JSONB, default=dict)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress_pct: Mapped[int] = mapped_column(SmallInteger, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulationResult(Base):
    """One row per run per month. Insert-only (rule #2 / BR-31) — see the
    trigger attached below, mirroring app/parameters/models.py's
    immutability trigger for VALIDATED parameter sets."""

    __tablename__ = "simulation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "month_index", name="uq_simulation_results_run_month"),
        Index("ix_simulation_results_run_year", "run_id", "year_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    month_index: Mapped[int] = mapped_column(SmallInteger)
    year_index: Mapped[int] = mapped_column(SmallInteger)
    calendar_month: Mapped[int] = mapped_column(SmallInteger)
    population: Mapped[int] = mapped_column(Integer)
    population_effective: Mapped[int] = mapped_column(Integer)
    per_capita_kg_day: Mapped[float] = mapped_column(Numeric(6, 3))
    waste_domestic_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    waste_bulk_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    waste_industrial_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    waste_total_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    organic_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    plastic_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    paper_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    metal_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    glass_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    textile_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    inert_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    ewaste_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    other_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    collection_coverage_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    accessibility_index: Mapped[float] = mapped_column(Numeric(5, 4))
    waste_collected_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    waste_uncollected_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    segregation_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    organic_treated_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    recyclables_recovered_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    compost_output_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    treatment_capacity_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    treatment_utilization_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    to_landfill_tpd: Mapped[float] = mapped_column(Numeric(12, 3))
    landfill_cumulative_tonnes: Mapped[float] = mapped_column(Numeric(16, 2))
    landfill_remaining_tonnes: Mapped[float] = mapped_column(Numeric(16, 2))
    vehicles_required: Mapped[int] = mapped_column(SmallInteger)
    vehicle_shortfall: Mapped[int] = mapped_column(SmallInteger)
    opex_inr: Mapped[float] = mapped_column(Numeric(16, 2))
    capex_inr: Mapped[float] = mapped_column(Numeric(16, 2), default=0)
    ghg_tco2e: Mapped[float] = mapped_column(Numeric(14, 3))
    active_event_codes: Mapped[list] = mapped_column(JSONB, default=list)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)


class SimulationYearly(Base):
    __tablename__ = "simulation_yearly"
    __table_args__ = (UniqueConstraint("run_id", "year_index", name="uq_simulation_yearly_run_year"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    year_index: Mapped[int] = mapped_column(SmallInteger)
    population_end: Mapped[int] = mapped_column(Integer)
    waste_total_tpy: Mapped[float] = mapped_column(Numeric(14, 2))
    waste_collected_tpy: Mapped[float] = mapped_column(Numeric(14, 2))
    waste_uncollected_tpy: Mapped[float] = mapped_column(Numeric(14, 2))
    treated_tpy: Mapped[float] = mapped_column(Numeric(14, 2))
    recovered_tpy: Mapped[float] = mapped_column(Numeric(14, 2))
    landfilled_tpy: Mapped[float] = mapped_column(Numeric(14, 2))
    landfill_remaining_tonnes: Mapped[float] = mapped_column(Numeric(16, 2))
    avg_coverage_pct: Mapped[float] = mapped_column(Numeric(5, 2))
    peak_vehicle_shortfall: Mapped[int] = mapped_column(SmallInteger)
    opex_inr: Mapped[float] = mapped_column(Numeric(16, 2))
    capex_inr: Mapped[float] = mapped_column(Numeric(16, 2))
    total_cost_inr: Mapped[float] = mapped_column(Numeric(16, 2))
    discounted_cost_inr: Mapped[float] = mapped_column(Numeric(16, 2))
    ghg_tco2e: Mapped[float] = mapped_column(Numeric(14, 3))
    recovery_rate_pct: Mapped[float] = mapped_column(Numeric(5, 2))


class RunFinding(Base):
    __tablename__ = "run_findings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(60))
    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(FindingSeverity, name="finding_severity"), default=FindingSeverity.INFO
    )
    numeric_value: Mapped[float | None] = mapped_column(Numeric(18, 3), nullable=True)
    year_index: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    message: Mapped[str] = mapped_column(Text)


# --- Insert-only enforcement (rule #2 / BR-31) --------------------------
# Same two-mechanism pattern as app/parameters/models.py's immutability
# trigger: a DDL function + per-table triggers, attached to Base.metadata so
# both `alembic upgrade head` and the test suite's create_all() get it.
# "%%" (not "%"): sqlalchemy.schema.DDL runs `text % context` on this whole
# string before Postgres ever sees it, so a literal "%" meant only for
# Postgres's own RAISE EXCEPTION placeholder must be doubled or Python's
# %-operator misreads it as a format spec (see app/parameters/models.py's
# identical trigger for the first time this bit us).
_CREATE_INSERT_ONLY_TRIGGER_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION swms_block_all_updates() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'this table is insert-only (rule #2): %% rows are never updated after insert', TG_TABLE_NAME
            USING ERRCODE = '23514';
    END;
    $$ LANGUAGE plpgsql;
    """
)
event.listen(Base.metadata, "before_create", _CREATE_INSERT_ONLY_TRIGGER_FUNCTION)

_INSERT_ONLY_TABLES = (SimulationResult, SimulationYearly, RunFinding)
for _model in _INSERT_ONLY_TABLES:
    _table_name = _model.__tablename__
    event.listen(
        _model.__table__,
        "after_create",
        DDL(
            f"""
            CREATE TRIGGER trg_insert_only_{_table_name}
            BEFORE UPDATE ON {_table_name}
            FOR EACH ROW EXECUTE FUNCTION swms_block_all_updates();
            """
        ),
    )
