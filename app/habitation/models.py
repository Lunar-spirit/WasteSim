import enum
import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HabitationType(str, enum.Enum):
    VILLAGE = "VILLAGE"
    WARD = "WARD"
    TOWN = "TOWN"
    CITY = "CITY"


class HabitationStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    ARCHIVED = "ARCHIVED"


class AccessLevel(str, enum.Enum):
    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class Habitation(Base):
    __tablename__ = "habitations"
    __table_args__ = (UniqueConstraint("name", "district", "state", name="uq_habitation_location"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    habitation_type: Mapped[HabitationType] = mapped_column(
        Enum(HabitationType, name="habitation_type")
    )
    state: Mapped[str] = mapped_column(String(128))
    district: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(128), default="India")
    # SRID 4326 everywhere per project rule; GEOGRAPHY (not GEOMETRY) so
    # ST_Area/ST_Buffer return real metres instead of raw degrees.
    # Mapped as Any: GeoAlchemy2 hands back a WKBElement, not a plain string.
    centroid: Mapped[Any | None] = mapped_column(Geography("POINT", srid=4326), nullable=True)
    boundary: Mapped[Any | None] = mapped_column(Geography("MULTIPOLYGON", srid=4326), nullable=True)
    area_sqkm: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    status: Mapped[HabitationStatus] = mapped_column(
        Enum(HabitationStatus, name="habitation_status"),
        default=HabitationStatus.DRAFT,
    )
    # use_alter=True + an explicit name: habitations -> parameter_sets ->
    # habitations is a genuine FK cycle (a parameter_set belongs to a
    # habitation, a habitation points at its active parameter_set). Without
    # use_alter, SQLAlchemy can't topologically order CREATE/DROP TABLE for
    # the two and raises CircularDependencyError; use_alter defers this one
    # constraint to its own ALTER TABLE ... ADD/DROP CONSTRAINT, breaking the
    # cycle. Named to match the constraint migration 0001 creates by hand.
    active_parameter_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "parameter_sets.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_habitations_active_parameter_set",
        ),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HabitationMember(Base):
    __tablename__ = "habitation_members"
    __table_args__ = (
        UniqueConstraint("habitation_id", "user_id", name="uq_habitation_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    access_level: Mapped[AccessLevel] = mapped_column(Enum(AccessLevel, name="access_level"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
