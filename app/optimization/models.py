import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class OptStrategy(str, enum.Enum):
    STAGED_SEARCH = "STAGED_SEARCH"
    LP_POLISH = "LP_POLISH"
    GRID = "GRID"


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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id = Column(UUID(as_uuid=True), ForeignKey("habitations.id"), nullable=False, index=True)
    base_run_id = Column(UUID(as_uuid=True), ForeignKey("simulation_runs.id"), nullable=False, index=True)
    decision_space = Column(JSONB, nullable=False, default=dict)
    constraints = Column(JSONB, nullable=False, default=dict)
    strategy = Column(String(40), nullable=False, default=OptStrategy.STAGED_SEARCH.value)
    candidates_evaluated = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="QUEUED", index=True)
    best_candidate_id = Column(BigInteger, nullable=True)
    promoted_run_id = Column(UUID(as_uuid=True), ForeignKey("simulation_runs.id"), nullable=True)
    infeasible_reason = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    objectives = relationship("OptimizationObjective", back_populates="optimization", cascade="all, delete-orphan")
    candidates = relationship("OptimizationCandidate", back_populates="optimization", cascade="all, delete-orphan")


class OptimizationObjective(Base):
    __tablename__ = "optimization_objectives"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    optimization_id = Column(
        UUID(as_uuid=True), ForeignKey("optimization_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    objective = Column(String(40), nullable=False)
    weight = Column(Numeric(4, 3), nullable=False)
    normalisation_basis = Column(Numeric(18, 3), nullable=True)

    optimization = relationship("OptimizationRun", back_populates="objectives")


class OptimizationCandidate(Base):
    __tablename__ = "optimization_candidates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    optimization_id = Column(
        UUID(as_uuid=True), ForeignKey("optimization_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage = Column(String(40), nullable=False)
    decision_values = Column(JSONB, nullable=False)
    feasible = Column(Boolean, nullable=False)
    violated_constraints = Column(JSONB, nullable=False, default=list)
    objective_values = Column(JSONB, nullable=False, default=dict)
    normalised_values = Column(JSONB, nullable=False, default=dict)
    score = Column(Numeric(10, 6), nullable=True)
    is_pareto = Column(Boolean, nullable=False, default=False)
    capex_total_inr = Column(Numeric(16, 2), nullable=True)

    optimization = relationship("OptimizationRun", back_populates="candidates")
