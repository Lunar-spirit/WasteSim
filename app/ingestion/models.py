import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FileFormat(str, enum.Enum):
    CSV = "CSV"
    XLSX = "XLSX"
    JSON = "JSON"
    GEOJSON = "GEOJSON"
    SHAPEFILE_ZIP = "SHAPEFILE_ZIP"
    KML = "KML"


class UploadTarget(str, enum.Enum):
    PARAMETERS = "PARAMETERS"
    GIS_LAYER = "GIS_LAYER"


class UploadStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    INGESTED = "INGESTED"
    FAILED = "FAILED"


# File extension (lowercased, no dot) -> the canonical FileFormat the design
# names. ".zip" is assumed to be a zipped shapefile because that is the only
# archive format the design accepts on this endpoint (BR-07's CRS check
# happens on what's inside it, in the GIS worker, not here).
EXTENSION_TO_FORMAT: dict[str, FileFormat] = {
    "csv": FileFormat.CSV,
    "xlsx": FileFormat.XLSX,
    "json": FileFormat.JSON,
    "geojson": FileFormat.GEOJSON,
    "kml": FileFormat.KML,
    "zip": FileFormat.SHAPEFILE_ZIP,
}


class DatasetUpload(Base):
    __tablename__ = "dataset_uploads"
    __table_args__ = (
        # 50 MB cap (PDD-11) — enforced again here at the DB level, on top of
        # the check the router does before ever reading the file into memory.
        CheckConstraint("size_bytes <= 52428800", name="ck_dataset_uploads_size_cap"),
        Index("ix_dataset_uploads_dedup", "habitation_id", "checksum_sha256", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE"), nullable=True
    )
    # Set once POST /uploads/{id}/ingest actually commits accepted rows into
    # a draft parameter set — NULL from RECEIVED through VALIDATED.
    parameter_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parameter_sets.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[FileFormat] = mapped_column(Enum(FileFormat, name="file_format"))
    target: Mapped[UploadTarget] = mapped_column(Enum(UploadTarget, name="upload_target"))
    storage_key: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, name="upload_status"), default=UploadStatus.RECEIVED
    )
    rows_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_accepted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_rejected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
