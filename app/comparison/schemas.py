import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_COMPARISON_INDICATORS = ["total_cost_inr", "landfilled_tpy", "recovery_rate_pct", "landfill_remaining_tonnes"]


class ComparisonCreateIn(BaseModel):
    run_ids: list[uuid.UUID] = Field(min_length=2, max_length=5)  # BR-27
    indicators: list[str] = Field(default_factory=lambda: list(DEFAULT_COMPARISON_INDICATORS))
    title: str | None = None


class ComparisonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    run_ids: list[str]
    indicators: list[str]
    title: str | None
    created_at: datetime


class ComparisonSeriesOut(BaseModel):
    run_ids: list[str]
    indicators: list[str]
    series: dict[str, list[dict[str, Any]]]


class ComparisonDeltasOut(BaseModel):
    base_run_id: str
    deltas: dict[str, list[dict[str, Any]]]
