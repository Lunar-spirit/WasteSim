import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class AnalysisStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class SensitivityAnalysis(Base):
    __tablename__ = "sensitivity_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id = Column(UUID(as_uuid=True), ForeignKey("habitations.id"), nullable=False, index=True)
    base_run_id = Column(UUID(as_uuid=True), ForeignKey("simulation_runs.id"), nullable=False, index=True)
    param_path = Column(String(160), nullable=False)
    swept_values = Column(JSONB, nullable=False)
    indicators = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default=AnalysisStatus.QUEUED.value)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    points = relationship(
        "SensitivityPoint", back_populates="analysis", cascade="all, delete-orphan", order_by="SensitivityPoint.swept_value"
    )


class SensitivityPoint(Base):
    __tablename__ = "sensitivity_points"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    analysis_id = Column(
        UUID(as_uuid=True), ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    swept_value = Column(Numeric(18, 4), nullable=False)
    child_run_id = Column(UUID(as_uuid=True), ForeignKey("simulation_runs.id"), nullable=True)
    indicator_values = Column(JSONB, nullable=False, default=dict)
    elasticity = Column(Numeric(10, 4), nullable=True)

    analysis = relationship("SensitivityAnalysis", back_populates="points")
