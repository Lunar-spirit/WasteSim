import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.daily_logs.models import AnomalyFlag


class DailyLogIn(BaseModel):
    log_date: date
    total_collected_tonnes: float = Field(ge=0)
    organic_tonnes: float = Field(ge=0)
    dry_recyclable_tonnes: float = Field(ge=0)
    hazardous_tonnes: float | None = Field(default=None, ge=0)
    vehicles_deployed: int = Field(ge=0)
    trips_completed: int = Field(ge=0)
    diesel_consumed_litres: float | None = Field(default=None, ge=0)
    collection_coverage_pct_observed: float | None = Field(default=None, ge=0, le=100)
    anomaly_flag: AnomalyFlag = AnomalyFlag.NORMAL
    notes: str | None = None


class DailyLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    logged_by: uuid.UUID
    log_date: date
    total_collected_tonnes: float
    organic_tonnes: float
    dry_recyclable_tonnes: float
    hazardous_tonnes: float | None
    vehicles_deployed: int
    trips_completed: int
    diesel_consumed_litres: float | None
    collection_coverage_pct_observed: float | None
    anomaly_flag: AnomalyFlag
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DailyLogPage(BaseModel):
    items: list[DailyLogOut]
    total: int
    page: int
    page_size: int


class BulkImportRowError(BaseModel):
    row_number: int
    message: str


class BulkImportResult(BaseModel):
    total_rows: int
    created_count: int
    updated_count: int
    error_count: int
    errors: list[BulkImportRowError]
