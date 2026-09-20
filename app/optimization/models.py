import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class OptStrategy(str, enum.Enum):
    STAGED_SEARCH = "STAGED_SEARCH"
    LP_POLISH = "LP_POLISH"
    GRID = "GRID"


# Distinct from simulation_runs' run_status (design's own table): PARTIAL
# stands in for CANCELLED here — a search that exhausts its max_evaluations
# budget without covering the space it wanted still reports what it found.
class AnalysisStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ObjectiveKind(str, enum.Enum):
    MIN_COST = "MIN_COST"
    MIN_LANDFILL = "MIN_LANDFILL"
    MAX_COVERAGE = "MAX_COVERAGE"
    MAX_RECOVERY = "MAX_RECOVERY"
    MIN_GHG = "MIN_GHG"
    MAX_RESILIENCE = "MAX_RESILIENCE"


class OptStage(str, enum.Enum):
    SAMPLING = "SAMPLING"
    REFINEMENT = "REFINEMENT"
    LP_POLISH = "LP_POLISH"


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE"))
    base_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="RESTRICT")
    )
    # Variable bounds actually used for this search (design 5.6) — the
    # catalogue/physical defaults, narrowed by any caller overrides and by
    # BR-26 (forced to [0, 0] in an eco-sensitive zone).
    decision_space: Mapped[dict] = mapped_column(JSONB)
    constraints: Mapped[dict] = mapped_column(JSONB)
    strategy: Mapped[OptStrategy] = mapped_column(
        Enum(OptStrategy, name="opt_strategy"), default=OptStrategy.STAGED_SEARCH
    )
    candidates_evaluated: Mapped[int] = mapped_column(default=0)
    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(AnalysisStatus, name="analysis_status"), default=AnalysisStatus.QUEUED
    )
    # use_alter=True: same circular-FK resolution as the migration's own
    # ALTER TABLE (this table <-> optimization_candidates each reference the
    # other) — without it, SQLAlchemy's create_all/drop_all (used by the
    # test suite's schema fixture, not Alembic) can't topologically sort the
    # two tables at all.
    best_candidate_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "optimization_candidates.id", ondelete="SET NULL", use_alter=True, name="fk_optimization_runs_best_candidate"
        ),
        nullable=True,
    )
    promoted_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True
    )
    infeasible_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OptimizationObjective(Base):
    __tablename__ = "optimization_objectives"
    __table_args__ = (
        CheckConstraint("weight >= 0 AND weight <= 1", name="ck_optimization_objectives_weight_range"),
        UniqueConstraint("optimization_id", "objective", name="uq_optimization_objectives_one_per_kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    optimization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("optimization_runs.id", ondelete="CASCADE")
    )
    objective: Mapped[ObjectiveKind] = mapped_column(Enum(ObjectiveKind, name="objective_kind"))
    weight: Mapped[float] = mapped_column(Numeric(4, 3))
    # The base run's own value for this objective — what 0.0/1.0 mean when
    # normalising a candidate's raw value onto the 0-1 scale (design 5.6:
    # "each normalised 0-1 against the base run").
    normalisation_basis: Mapped[float | None] = mapped_column(Numeric(18, 3), nullable=True)


class OptimizationCandidate(Base):
    __tablename__ = "optimization_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    optimization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("optimization_runs.id", ondelete="CASCADE")
    )
    stage: Mapped[OptStage] = mapped_column(Enum(OptStage, name="opt_stage"))
    decision_values: Mapped[dict] = mapped_column(JSONB)
    feasible: Mapped[bool] = mapped_column(Boolean)
    violated_constraints: Mapped[list] = mapped_column(JSONB, default=list)
    objective_values: Mapped[dict] = mapped_column(JSONB, default=dict)
    normalised_values: Mapped[dict] = mapped_column(JSONB, default=dict)
    score: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    is_pareto: Mapped[bool] = mapped_column(Boolean, default=False)
    capex_total_inr: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)


__all__ = [
    "OptStrategy",
    "AnalysisStatus",
    "ObjectiveKind",
    "OptStage",
    "OptimizationRun",
    "OptimizationObjective",
    "OptimizationCandidate",
]
