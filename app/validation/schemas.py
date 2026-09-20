import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ValidationIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    severity: str
    code: str
    category: str | None = None
    field_path: str
    row_number: int | None = None
    message: str
    observed_value: str | None = None
    expected_range: str | None = None
    suggested_fix: str | None = None


class ValidationReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    parameter_set_id: uuid.UUID | None = None
    upload_id: uuid.UUID | None = None
    scope: str
    result: str
    error_count: int
    warning_count: int
    completeness_pct: float
    completeness_by_category: dict[str, float]
    rules_version: str
    started_at: datetime
    completed_at: datetime | None = None
    issues: list[ValidationIssueOut]
