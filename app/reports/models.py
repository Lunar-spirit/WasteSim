import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ReportFormat(str, enum.Enum):
    PDF = "PDF"
    XLSX = "XLSX"
    CSV = "CSV"


class ReportStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "(run_id IS NOT NULL AND comparison_id IS NULL) OR (run_id IS NULL AND comparison_id IS NOT NULL)",
            name="ck_reports_exactly_one_subject",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=True
    )
    comparison_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run_comparisons.id", ondelete="CASCADE"), nullable=True
    )
    format: Mapped[ReportFormat] = mapped_column(Enum(ReportFormat, name="report_format"))
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus, name="report_status"), default=ReportStatus.QUEUED)
    error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = ["Report", "ReportFormat", "ReportStatus"]
