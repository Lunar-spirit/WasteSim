import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RunComparison(Base):
    __tablename__ = "run_comparisons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE"))
    # Ordered list of run ids, 2-5 entries (BR-27) — order matters: deltas
    # (API-78) are always computed against run_ids[0].
    run_ids: Mapped[list[str]] = mapped_column(JSONB)
    indicators: Mapped[list[str]] = mapped_column(JSONB)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = ["RunComparison"]
