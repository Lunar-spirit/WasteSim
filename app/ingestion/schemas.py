import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UploadCreateOut(BaseModel):
    upload_id: uuid.UUID
    status: str
    job_id: str | None = None
    file_format: str
    size_bytes: int
    poll_url: str
    duplicate_of: uuid.UUID | None = None


class UploadStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID | None = None
    parameter_set_id: uuid.UUID | None = None
    original_filename: str
    file_format: str
    target: str
    status: str
    rows_total: int | None = None
    rows_accepted: int | None = None
    rows_rejected: int | None = None
    retry_count: int
    error_summary: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
