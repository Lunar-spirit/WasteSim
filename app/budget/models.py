import enum

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class CostKind(str, enum.Enum):
    CAPEX = "CAPEX"
    OPEX = "OPEX"


class CostCategory(str, enum.Enum):
    COLLECTION = "COLLECTION"
    TRANSPORT = "TRANSPORT"
    TREATMENT = "TREATMENT"
    DISPOSAL = "DISPOSAL"
    FLEET_PURCHASE = "FLEET_PURCHASE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    ADMIN = "ADMIN"
    AWARENESS = "AWARENESS"


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year_index = Column(SmallInteger, nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    category = Column(String(40), nullable=False)
    amount_inr = Column(Numeric(16, 2), nullable=False)
    discounted_inr = Column(Numeric(16, 2), nullable=False)
    note = Column(String(200), nullable=True)

    simulation_run = relationship("SimulationRun", back_populates="budget_lines")
