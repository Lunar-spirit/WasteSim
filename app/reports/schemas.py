import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.reports.models import ReportFormat, ReportStatus


class ReportCreateIn(BaseModel):
    run_id: uuid.UUID | None = None
    comparison_id: uuid.UUID | None = None
    format: ReportFormat = ReportFormat.PDF


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    run_id: uuid.UUID | None
    comparison_id: uuid.UUID | None
    format: ReportFormat
    status: ReportStatus
    error_detail: str | None
    expires_at: datetime | None
    created_at: datetime
