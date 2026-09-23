import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core import storage
from app.core.errors import AppError
from app.gis.models import LayerType
from app.gis.service import create_gis_layer_container
from app.habitation.service import get_habitation_or_404
from app.ingestion.models import EXTENSION_TO_FORMAT, DatasetUpload, FileFormat, UploadStatus, UploadTarget
from app.ingestion.parsers import ParseError, parse_rows
from app.parameters.models import ParameterDefinition
from app.parameters.service import (
    derive_semi_automated_fields,
    get_parameter_set_or_404,
    upsert_category,
    upsert_waste_baseline,
)
from app.validation.models import Severity, ValidationIssue, ValidationReport, ValidationResult, ValidationScope
from app.validation.pipeline import Issue, PipelineResult, validate_and_normalize_field

MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # PDD-11
DEDUP_WINDOW = timedelta(hours=24)  # BR-11

PARAMETERS_FORMATS = (FileFormat.CSV, FileFormat.XLSX, FileFormat.JSON)
GIS_LAYER_FORMATS = (FileFormat.GEOJSON, FileFormat.KML, FileFormat.SHAPEFILE_ZIP)


async def create_upload(
    db: AsyncSession,
    habitation_id: uuid.UUID,
    *,
    filename: str,
    data: bytes,
    target: UploadTarget,
    parameter_set_id: uuid.UUID | None = None,
    layer_name: str | None = None,
    layer_type: LayerType | None = None,
    user: User,
) -> tuple[DatasetUpload, uuid.UUID | None]:
    """Returns (upload, duplicate_of). duplicate_of is set (and `upload` is
    the EXISTING record) when BR-11's 24h dedup check matches — the caller
    then returns 200 instead of 202 and enqueues nothing."""
    await get_habitation_or_404(db, habitation_id)

    if len(data) > MAX_UPLOAD_SIZE_BYTES:
        raise AppError("FILE_TOO_LARGE", "File exceeds the 50 MB limit", 413)

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_format = EXTENSION_TO_FORMAT.get(extension)

    if target == UploadTarget.PARAMETERS:
        if file_format not in PARAMETERS_FORMATS:
            raise AppError(
                "FILE_TYPE_NOT_SUPPORTED",
                f"'.{extension}' is not a supported PARAMETERS format (csv, xlsx, json)",
                400,
            )
    else:
        if file_format not in GIS_LAYER_FORMATS:
            raise AppError(
                "FILE_TYPE_NOT_SUPPORTED",
                f"'.{extension}' is not a supported GIS_LAYER format (geojson, kml, zip)",
                400,
            )
        if not layer_name or layer_type is None:
            raise AppError(
                "MISSING_LAYER_TYPE", "layer_type and layer_name are required when target=GIS_LAYER", 400
            )

    checksum = hashlib.sha256(data).hexdigest()
    cutoff = datetime.now(timezone.utc) - DEDUP_WINDOW
    existing = await db.scalar(
        select(DatasetUpload)
        .where(
            DatasetUpload.habitation_id == habitation_id,
            DatasetUpload.checksum_sha256 == checksum,
            DatasetUpload.created_at >= cutoff,
        )
        .order_by(DatasetUpload.created_at.desc())
    )
    if existing is not None:
        return existing, existing.id

    # Object storage BEFORE the DB row (EXT-04): a record must never point
    # at a file that was never actually written.
    storage_key = f"uploads/{habitation_id}/{uuid.uuid4()}_{filename}"
    storage.put_object(storage_key, data, content_type=_content_type_for(file_format))

    upload = DatasetUpload(
        habitation_id=habitation_id,
        parameter_set_id=parameter_set_id,
        uploaded_by=user.id,
        original_filename=filename,
        file_format=file_format,
        target=target,
        storage_key=storage_key,
        size_bytes=len(data),
        checksum_sha256=checksum,
        status=UploadStatus.RECEIVED,
    )
    db.add(upload)
    await db.flush()

    if target == UploadTarget.GIS_LAYER:
        # Already validated non-None above; asserted (not just relied upon)
        # so mypy's flow analysis — which doesn't carry narrowing across the
        # separate `if target == ...` blocks — agrees.
        assert layer_name is not None and layer_type is not None
        # Eagerly creates the GISLayer container (status=PROCESSING) — the
        # exact same pattern as a PARAMETERS upload naming an existing
        # parameter_set_id: the "where does this go" decision is made at
        # upload time, and the worker (BG-01) only fills it in.
        await create_gis_layer_container(
            db, habitation_id, upload, layer_name=layer_name, layer_type=layer_type, user=user
        )

    return upload, None


def _content_type_for(file_format: FileFormat) -> str:
    return {
        FileFormat.CSV: "text/csv",
        FileFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        FileFormat.JSON: "application/json",
    }.get(file_format, "application/octet-stream")


async def get_upload_or_404(db: AsyncSession, upload_id: uuid.UUID) -> DatasetUpload:
    upload = await db.get(DatasetUpload, upload_id)
    if upload is None:
        raise AppError("UPLOAD_NOT_FOUND", "Upload not found", 404)
    return upload


async def list_upload_issues(db: AsyncSession, upload_id: uuid.UUID) -> list[ValidationIssue]:
    report = await db.scalar(
        select(ValidationReport)
        .where(ValidationReport.upload_id == upload_id)
        .order_by(ValidationReport.started_at.desc())
    )
    if report is None:
        return []
    return list(await db.scalars(select(ValidationIssue).where(ValidationIssue.report_id == report.id)))


async def validate_upload_rows(db: AsyncSession, upload: DatasetUpload) -> ValidationReport:
    """The core of BG-02: read the file back from object storage, validate
    every row against the catalogue (Stage 1/2, reused from the same
    pipeline the JSON API path uses), and write ONE validation_report +
    one validation_issue per problem — same shape as a parameter_set
    validation, just scope=UPLOAD and every issue stamped with its
    row_number (BR-18)."""
    data = storage.get_object(upload.storage_key)

    try:
        rows = parse_rows(data, upload.file_format)
    except ParseError as exc:
        upload.status = UploadStatus.REJECTED
        upload.error_summary = exc.message
        upload.rows_total = 0
        upload.rows_accepted = 0
        upload.rows_rejected = 0
        upload.completed_at = datetime.now(timezone.utc)
        report = await _write_upload_report(
            db,
            upload,
            PipelineResult(
                issues=[Issue(Severity.ERROR, "STRUCTURAL_INVALID", "file", exc.message)]
            ),
        )
        await db.flush()
        return report

    definitions_by_key: dict[tuple[str, str], ParameterDefinition] = {
        (d.category, d.param_key): d for d in await db.scalars(select(ParameterDefinition))
    }

    result = PipelineResult()
    accepted_rows = 0
    for row in rows:
        definition = definitions_by_key.get((row.category, row.param_key))
        if definition is None:
            result.issues.append(
                Issue(
                    Severity.ERROR,
                    "UNKNOWN_FIELD",
                    f"{row.category}.{row.param_key}",
                    f"'{row.category}.{row.param_key}' is not a known parameter",
                    observed_value=str(row.raw_value),
                    category=row.category.upper(),
                    row_number=row.row_number,
                )
            )
            continue
        _value, issues = validate_and_normalize_field(definition, row.raw_value, row.row_number)
        result.issues.extend(issues)
        if not any(i.severity == Severity.ERROR and i.row_number == row.row_number for i in issues):
            accepted_rows += 1

    upload.rows_total = len(rows)
    upload.rows_accepted = accepted_rows
    upload.rows_rejected = len(rows) - accepted_rows
    upload.completed_at = datetime.now(timezone.utc)
    # BR-18: tabular is row-by-row, so a file with SOME bad rows is still
    # VALIDATED (the good rows can be ingested); only a file with nothing
    # usable at all is REJECTED outright.
    upload.status = UploadStatus.REJECTED if accepted_rows == 0 else UploadStatus.VALIDATED

    report = await _write_upload_report(db, upload, result)
    await db.flush()
    return report


async def _write_upload_report(db: AsyncSession, upload: DatasetUpload, result: PipelineResult) -> ValidationReport:
    outcome = (
        ValidationResult.FAIL
        if result.error_count > 0
        else (ValidationResult.PASS_WITH_WARNINGS if result.warning_count > 0 else ValidationResult.PASS)
    )
    report = ValidationReport(
        habitation_id=upload.habitation_id,
        upload_id=upload.id,
        scope=ValidationScope.UPLOAD,
        result=outcome,
        error_count=result.error_count,
        warning_count=result.warning_count,
        completeness_pct=0,  # an upload's own completeness is judged against the target parameter set at /validate, not here
        completeness_by_category={},
        triggered_by=upload.uploaded_by,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(report)
    await db.flush()
    for issue in result.issues:
        db.add(
            ValidationIssue(
                report_id=report.id,
                severity=issue.severity,
                code=issue.code,
                category=issue.category,
                field_path=issue.field_path,
                message=issue.message,
                observed_value=issue.observed_value,
                expected_range=issue.expected_range,
                suggested_fix=issue.suggested_fix,
                row_number=issue.row_number,
            )
        )
    await db.flush()
    return report


async def ingest_accepted_rows(db: AsyncSession, upload: DatasetUpload) -> Any:
    """API-37: BR-18's commit step. Re-derives the accepted rows by
    re-validating the stored original (no separate "staging" table — the
    original file in object storage already *is* the staged data, and
    re-running the same deterministic validation is cheap and guarantees
    the committed values are exactly the ones the /issues endpoint showed).
    """
    if upload.target != UploadTarget.PARAMETERS:
        raise AppError(
            "INGEST_NOT_APPLICABLE",
            "Only a PARAMETERS upload has a separate /ingest step — a GIS_LAYER upload "
            "loads all-or-nothing as part of processing (BR-18 is tabular-only)",
            409,
        )
    if upload.status != UploadStatus.VALIDATED:
        raise AppError(
            "UPLOAD_NOT_READY", f"Upload must be VALIDATED to ingest, is {upload.status.value}", 409
        )
    if upload.parameter_set_id is None:
        raise AppError(
            "UPLOAD_MISSING_PARAMETER_SET",
            "This upload was not linked to a parameter set at upload time",
            409,
        )

    ps = await get_parameter_set_or_404(db, upload.parameter_set_id)

    data = storage.get_object(upload.storage_key)
    rows = parse_rows(data, upload.file_format)
    definitions_by_key: dict[tuple[str, str], ParameterDefinition] = {
        (d.category, d.param_key): d for d in await db.scalars(select(ParameterDefinition))
    }

    accepted_by_category: dict[str, dict[str, Any]] = {}
    for row in rows:
        definition = definitions_by_key.get((row.category, row.param_key))
        if definition is None:
            continue
        value, issues = validate_and_normalize_field(definition, row.raw_value, row.row_number)
        if value is None or any(i.severity == Severity.ERROR for i in issues):
            continue
        accepted_by_category.setdefault(row.category, {})[row.param_key] = row.raw_value

    for category, payload in accepted_by_category.items():
        if category == "waste_baseline":
            await upsert_waste_baseline(db, ps.id, payload)
        else:
            await upsert_category(db, ps.id, category, payload)

    # Semi-automated formulations (automation module): fills household_count
    # / total_generation_tpd from what this upload just supplied, when the
    # target itself wasn't one of the ingested columns and the fields it's
    # derived from are now present.
    await derive_semi_automated_fields(db, ps.id)

    upload.status = UploadStatus.INGESTED
    await db.flush()
    return ps


async def retry_upload(db: AsyncSession, upload: DatasetUpload) -> DatasetUpload:
    if upload.status != UploadStatus.FAILED:
        raise AppError("UPLOAD_NOT_FAILED", f"Only a FAILED upload can be retried, is {upload.status.value}", 409)
    upload.status = UploadStatus.RECEIVED
    upload.retry_count += 1
    upload.error_summary = None
    await db.flush()
    return upload
