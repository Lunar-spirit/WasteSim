import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Severity(str, enum.Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    # Stage 1 (normalization) reports a value it silently converted, e.g.
    # "0.45 kg/person/day" -> 0.45 with a derived total — informational only,
    # never counted in error_count or warning_count.
    INFO = "INFO"


class ValidationResult(str, enum.Enum):
    PASS = "PASS"
    # Zero errors, but at least one WARNING issue (e.g. a value outside its
    # catalogue warn band). Still commit-eligible — only ERROR blocks commit
    # (BR-01) — but visibly different from a totally clean PASS.
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


class ValidationScope(str, enum.Enum):
    PARAMETER_SET = "PARAMETER_SET"
    UPLOAD = "UPLOAD"
    GIS_LAYER = "GIS_LAYER"
    FULL_HABITATION = "FULL_HABITATION"


class ValidationReport(Base):
    __tablename__ = "validation_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE")
    )
    # Exactly one of these three is set, matching `scope` — parameter_set_id
    # for PARAMETER_SET/FULL_HABITATION, upload_id for UPLOAD, gis_layer_id
    # for GIS_LAYER. Nullable rather than a discriminated union because
    # Postgres has no clean "exactly one of" CHECK across three FKs without
    # a lot of ceremony for a hackathon timeline.
    parameter_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parameter_sets.id", ondelete="CASCADE"), nullable=True
    )
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_uploads.id", ondelete="CASCADE"), nullable=True
    )
    gis_layer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gis_layers.id", ondelete="CASCADE"), nullable=True
    )
    scope: Mapped[ValidationScope] = mapped_column(Enum(ValidationScope, name="validation_scope"))
    result: Mapped[ValidationResult] = mapped_column(Enum(ValidationResult, name="validation_result"))
    error_count: Mapped[int] = mapped_column(default=0)
    warning_count: Mapped[int] = mapped_column(default=0)
    completeness_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=0)
    # {"DEMOGRAPHY": 100.0, "TERRAIN": 57.1, ...} — per-category completeness
    # for the UI's "Terrain: 4 of 7" progress display.
    completeness_by_category: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Stamped from parameter_definitions.rules_version at report time, so an
    # old report stays interpretable even after the catalogue changes later.
    rules_version: Mapped[str] = mapped_column(String(20), default="v1")
    triggered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("validation_reports.id", ondelete="CASCADE")
    )
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="issue_severity"))
    code: Mapped[str] = mapped_column(String(64))
    # UPPER_SNAKE category name (e.g. "DEMOGRAPHY"), separate from field_path
    # so the UI can group/filter issues without string-splitting field_path.
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    field_path: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    observed_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_range: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Populated for a tabular (CSV/XLSX) upload row via M5 ingestion — which
    # row in the source file this issue came from. NULL for an issue raised
    # against a normal JSON parameter-set API call, where there is no "row".
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
