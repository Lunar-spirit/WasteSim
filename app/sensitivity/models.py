import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.optimization.models import AnalysisStatus  # shared enum — see migration 0011's docstring


class SensitivityAnalysis(Base):
    __tablename__ = "sensitivity_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE"))
    base_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="RESTRICT")
    )
    param_path: Mapped[str] = mapped_column(String(160))
    swept_values: Mapped[list] = mapped_column(JSONB)
    indicators: Mapped[list] = mapped_column(JSONB)
    status: Mapped[AnalysisStatus] = mapped_column(Enum(AnalysisStatus, name="analysis_status"), default=AnalysisStatus.QUEUED)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SensitivityPoint(Base):
    __tablename__ = "sensitivity_points"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sensitivity_analyses.id", ondelete="CASCADE")
    )
    swept_value: Mapped[float] = mapped_column(Numeric(18, 4))
    child_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True
    )
    indicator_values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Per-indicator elasticity: {"NPV_TOTAL_COST": 1.23, ...} — null (not an
    # empty dict) when the point itself failed, so "no elasticity anywhere"
    # is distinguishable from "zero elasticity everywhere".
    elasticity: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["SensitivityAnalysis", "SensitivityPoint"]
