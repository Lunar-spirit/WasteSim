import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Numeric, SmallInteger, String, event, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import DDL

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
    """One row per run per year per cost kind/category. Insert-only, same
    as simulation_results/simulation_yearly/run_findings — the trigger
    function itself is created once by app/simulation/models.py's
    before_create hook; this just attaches the same function to this table.
    """

    __tablename__ = "budget_lines"
    __table_args__ = (Index("ix_budget_lines_run_year_kind", "run_id", "year_index", "kind"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    year_index: Mapped[int] = mapped_column(SmallInteger)
    kind: Mapped[CostKind] = mapped_column(Enum(CostKind, name="cost_kind"))
    category: Mapped[CostCategory] = mapped_column(Enum(CostCategory, name="cost_category"))
    amount_inr: Mapped[float] = mapped_column(Numeric(16, 2))
    discounted_inr: Mapped[float] = mapped_column(Numeric(16, 2))
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(
    BudgetLine.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER trg_insert_only_budget_lines
        BEFORE UPDATE ON budget_lines
        FOR EACH ROW EXECUTE FUNCTION swms_block_all_updates();
        """
    ),
)
