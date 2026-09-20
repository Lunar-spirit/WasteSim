import enum
import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography, Geometry
from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


# Matches the design's gis_layers.layer_type exactly (design section 4.2) —
# the earlier, shorter list this model shipped with was missing
# ECO_SENSITIVE in particular, which BR-26 depends on (no landfill expansion
# in an eco-sensitive zone has nothing to check against without this value).
class LayerType(str, enum.Enum):
    ROAD = "ROAD"
    SETTLEMENT = "SETTLEMENT"
    INDUSTRIAL_ZONE = "INDUSTRIAL_ZONE"
    WATER_BODY = "WATER_BODY"
    TERRAIN_CONTOUR = "TERRAIN_CONTOUR"
    ECO_SENSITIVE = "ECO_SENSITIVE"
    ADMIN_BOUNDARY = "ADMIN_BOUNDARY"
    FACILITY_TREATMENT = "FACILITY_TREATMENT"
    FACILITY_LANDFILL = "FACILITY_LANDFILL"
    COLLECTION_ZONE = "COLLECTION_ZONE"


# Only 3 values in the design (PROCESSING / READY / FAILED) — a layer that
# fails BR-06 (too much outside the boundary) or BR-07 (no declared CRS)
# lands on FAILED, same as a worker crash; the *reason* lives in the
# validation_report/error_summary, not in a separate status value.
class LayerStatus(str, enum.Enum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class LayerSource(str, enum.Enum):
    UPLOAD = "UPLOAD"
    OSM_OVERPASS = "OSM_OVERPASS"
    MANUAL_DRAW = "MANUAL_DRAW"
    DERIVED = "DERIVED"


class GISLayer(Base):
    __tablename__ = "gis_layers"
    __table_args__ = (UniqueConstraint("habitation_id", "layer_name", name="uq_gis_layer_name"),)  # BR-14

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE")
    )
    layer_name: Mapped[str] = mapped_column(String(255))
    layer_type: Mapped[LayerType] = mapped_column(Enum(LayerType, name="gis_layer_type"))
    geometry_type: Mapped[str] = mapped_column(String(32))
    source: Mapped[LayerSource] = mapped_column(
        Enum(LayerSource, name="gis_layer_source"), default=LayerSource.UPLOAD
    )
    # Original filename for an UPLOAD layer, or the Overpass QL query for an
    # OSM_OVERPASS one — whatever explains "where did this data come from".
    source_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[LayerStatus] = mapped_column(
        Enum(LayerStatus, name="gis_layer_status"),
        default=LayerStatus.PROCESSING,
    )
    is_visible_default: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    srid_original: Mapped[int | None] = mapped_column(Integer, nullable=True)
    z_index: Mapped[int] = mapped_column(SmallInteger, default=0)
    style: Mapped[dict] = mapped_column(JSONB, default=dict)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    total_length_km: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    # GEOGRAPHY, not GEOMETRY, to match the design and so ST_DWithin-style
    # cheap out-of-area rejection on /map works in real metres.
    bbox: Mapped[Any | None] = mapped_column(Geography(geometry_type="POLYGON", srid=4326), nullable=True)
    # Which upload produced this layer, when it came from one (vs. OSM
    # import or a manual draw). NULL for those other sources.
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_uploads.id", ondelete="SET NULL"), nullable=True
    )


class GISFeature(Base):
    __tablename__ = "gis_features"
    __table_args__ = (
        Index("ix_gis_features_geom", "geom", postgresql_using="gist"),
        Index("ix_gis_features_properties", "properties", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    layer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gis_layers.id", ondelete="CASCADE")
    )
    # Source identifier (e.g. an OSM way id) so a re-import can be matched
    # against the same real-world feature instead of always creating a new
    # row. Not enforced unique — a re-import replaces the whole layer.
    feature_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    geom: Mapped[Any] = mapped_column(Geometry(geometry_type="GEOMETRY", srid=4326))
    # Precomputed for line features so the flood accessibility calculation
    # (design section 5.5) never has to recompute ST_Length under load.
    length_m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
