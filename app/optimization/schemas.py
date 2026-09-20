import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.optimization.models import AnalysisStatus, OptStage, OptStrategy


class OptimizationCreateIn(BaseModel):
    base_run_id: uuid.UUID
    objectives: dict[str, float] = Field(min_length=1)
    constraints: dict[str, Any] = Field(default_factory=dict)
    decision_space: dict[str, list[float]] | None = None
    strategy: OptStrategy = OptStrategy.STAGED_SEARCH
    max_evaluations: int = Field(default=400, ge=1, le=1000)


class PromoteIn(BaseModel):
    candidate_id: int | None = None


class OptimizationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    base_run_id: uuid.UUID
    decision_space: dict[str, Any]
    constraints: dict[str, Any]
    strategy: OptStrategy
    candidates_evaluated: int
    status: AnalysisStatus
    best_candidate_id: int | None
    promoted_run_id: uuid.UUID | None
    infeasible_reason: str | None
    created_at: datetime
    completed_at: datetime | None


class OptimizationCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage: OptStage
    decision_values: dict[str, Any]
    feasible: bool
    violated_constraints: list[str]
    objective_values: dict[str, float]
    normalised_values: dict[str, float]
    score: float | None
    is_pareto: bool
    capex_total_inr: float | None
