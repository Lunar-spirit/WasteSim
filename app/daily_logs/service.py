"""Daily Waste Collection & Operational Logging — see app/daily_logs/models.py
for why this is a plain upsert table, not insert-only.

Bulk CSV import runs synchronously in the request (unlike app/ingestion/'s
Celery-backed pipeline for PARAMETERS/GIS uploads): a daily-log sheet is at
most a few hundred rows (a year of daily entries), parses and upserts in
well under a second, so there is no "long job" here for rule 9 to apply to.
"""

from __future__ import annotations

import calendar
import csv
import io
import re
import uuid
from datetime import date
from typing import Any

import pandas as pd
from openpyxl import Workbook
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.errors import AppError
from app.daily_logs.models import DailyWasteLog
from app.daily_logs.schemas import BulkImportResult, BulkImportRowError, DailyLogIn
from app.habitation.service import get_habitation_or_404

# log_date is the only column every row must have on its own — the three
# tonnage/count fields can still fail DailyLogIn's own required-ness check
# per row (reported like any other bad value), but a CSV missing the column
# entirely is a structural problem worth rejecting up front, same as
# app/ingestion/parsers.py does for its own required columns.
REQUIRED_CSV_COLUMNS = {"log_date", "organic_tonnes", "dry_recyclable_tonnes", "vehicles_deployed", "trips_completed"}


async def upsert_daily_log(
    db: AsyncSession, habitation_id: uuid.UUID, payload: DailyLogIn, user: User
) -> tuple[DailyWasteLog, bool]:
    """Returns (row, created) — created=False means an existing row for
    this (habitation_id, log_date) was updated in place."""
    existing = await db.scalar(
        select(DailyWasteLog).where(
            DailyWasteLog.habitation_id == habitation_id,
            DailyWasteLog.log_date == payload.log_date,
        )
    )
    if existing is not None:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)
        existing.logged_by = user.id
        await db.flush()
        # updated_at is a server-side onupdate (func.now()), not something
        # this code ever sets — without an explicit refresh here, the ORM
        # object's cached value is stale post-UPDATE, and a later *sync*
        # Pydantic model_validate() touching it triggers a lazy DB load
        # with no async context to run in (MissingGreenlet), not just a
        # wrong value.
        await db.refresh(existing, ["updated_at"])
        return existing, False

    log = DailyWasteLog(habitation_id=habitation_id, logged_by=user.id, **payload.model_dump())
    db.add(log)
    await db.flush()
    return log, True


async def list_daily_logs(
    db: AsyncSession,
    habitation_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
    page: int,
    page_size: int,
) -> tuple[list[DailyWasteLog], int]:
    stmt = select(DailyWasteLog).where(DailyWasteLog.habitation_id == habitation_id)
    if from_date is not None:
        stmt = stmt.where(DailyWasteLog.log_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(DailyWasteLog.log_date <= to_date)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(DailyWasteLog.log_date.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list(await db.scalars(stmt))
    return items, total


EXPORT_COLUMNS = (
    "Date",
    "Habitation Name",
    "Logged By (Email)",
    "Total Collected (t)",
    "Organic (t)",
    "Dry Recyclable (t)",
    "Hazardous (t)",
    "Vehicles Deployed",
    "Trips Completed",
    "Diesel Consumed (L)",
    "Observed Coverage (%)",
    "Anomaly / Notes",
)


def resolve_export_date_range(
    period_type: str,
    year: int | None,
    month: int | None,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    """period_type -> (from_date, to_date), or an AppError naming exactly
    which parameter is missing for the chosen period_type — never a bare
    422 the caller has to guess the reason for."""
    if period_type == "yearly":
        if year is None:
            raise AppError("EXPORT_YEAR_REQUIRED", "year is required when period_type is 'yearly'", 400)
        return date(year, 1, 1), date(year, 12, 31)

    if period_type == "monthly":
        if year is None or month is None:
            raise AppError(
                "EXPORT_YEAR_MONTH_REQUIRED", "year and month are both required when period_type is 'monthly'", 400
            )
        if not 1 <= month <= 12:
            raise AppError("EXPORT_MONTH_INVALID", "month must be between 1 and 12", 400)
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)

    if period_type == "custom":
        if start_date is None or end_date is None:
            raise AppError(
                "EXPORT_RANGE_REQUIRED", "start_date and end_date are both required when period_type is 'custom'", 400
            )
        if start_date > end_date:
            raise AppError("EXPORT_RANGE_INVALID", "start_date must be on or before end_date", 400)
        return start_date, end_date

    raise AppError("EXPORT_PERIOD_TYPE_INVALID", "period_type must be 'monthly', 'yearly', or 'custom'", 400)


def _export_filename(habitation_name: str, period_type: str, year: int | None, month: int | None, from_date: date, to_date: date, ext: str) -> str:
    # Only letters/digits/underscore survive into the filename — a
    # habitation name is free-text and could otherwise carry characters a
    # Content-Disposition header (or a downstream filesystem) mishandles.
    slug = re.sub(r"[^A-Za-z0-9]+", "_", habitation_name).strip("_") or "habitation"
    if period_type == "yearly" and year is not None:
        period = str(year)
    elif period_type == "monthly" and year is not None and month is not None:
        period = f"{year}_{month:02d}"
    else:
        period = f"{from_date.isoformat()}_to_{to_date.isoformat()}"
    return f"daily_logs_{slug}_{period}.{ext}"


async def export_daily_logs(
    db: AsyncSession,
    habitation_id: uuid.UUID,
    period_type: str,
    year: int | None,
    month: int | None,
    start_date: date | None,
    end_date: date | None,
    export_format: str,
) -> tuple[bytes, str, str, str]:
    """Returns (file_bytes, media_type, filename, content_disposition)."""
    habitation = await get_habitation_or_404(db, habitation_id)
    from_date, to_date = resolve_export_date_range(period_type, year, month, start_date, end_date)

    rows = (
        await db.execute(
            select(DailyWasteLog, User.email)
            .join(User, User.id == DailyWasteLog.logged_by)
            .where(
                DailyWasteLog.habitation_id == habitation_id,
                DailyWasteLog.log_date >= from_date,
                DailyWasteLog.log_date <= to_date,
            )
            .order_by(DailyWasteLog.log_date.asc())
        )
    ).all()

    table: list[list[Any]] = []
    sum_total = sum_organic = sum_dry = sum_hazardous = sum_diesel = 0.0
    coverage_values: list[float] = []
    for log, email in rows:
        total = float(log.total_collected_tonnes)
        organic = float(log.organic_tonnes)
        dry = float(log.dry_recyclable_tonnes)
        hazardous = float(log.hazardous_tonnes) if log.hazardous_tonnes is not None else 0.0
        diesel = float(log.diesel_consumed_litres) if log.diesel_consumed_litres is not None else 0.0
        sum_total += total
        sum_organic += organic
        sum_dry += dry
        sum_hazardous += hazardous
        sum_diesel += diesel
        if log.collection_coverage_pct_observed is not None:
            coverage_values.append(float(log.collection_coverage_pct_observed))

        # One combined column, per the spec's own "Anomaly / Notes" header:
        # the flag when it's not NORMAL, the free-text notes, or both.
        if log.anomaly_flag.value == "NORMAL":
            anomaly_or_notes = log.notes or ""
        elif log.notes:
            anomaly_or_notes = f"{log.anomaly_flag.value}: {log.notes}"
        else:
            anomaly_or_notes = log.anomaly_flag.value

        table.append(
            [
                log.log_date.isoformat(),
                habitation.name,
                email,
                total,
                organic,
                dry,
                float(log.hazardous_tonnes) if log.hazardous_tonnes is not None else "",
                log.vehicles_deployed,
                log.trips_completed,
                float(log.diesel_consumed_litres) if log.diesel_consumed_litres is not None else "",
                float(log.collection_coverage_pct_observed) if log.collection_coverage_pct_observed is not None else "",
                anomaly_or_notes or "",
            ]
        )

    # Summary row: sums for tonnage/fuel, average for coverage — exactly the
    # spec's own wording. Vehicles/trips/anomaly are left blank rather than
    # guessing whether a sum or an average would be more meaningful there.
    avg_coverage = sum(coverage_values) / len(coverage_values) if coverage_values else ""
    table.append(
        [
            "TOTAL / AVERAGE",
            habitation.name,
            "",
            round(sum_total, 3),
            round(sum_organic, 3),
            round(sum_dry, 3),
            round(sum_hazardous, 3),
            "",
            "",
            round(sum_diesel, 2),
            round(avg_coverage, 2) if avg_coverage != "" else "",
            "",
        ]
    )

    if export_format == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = "Daily Logs"
        ws.append(list(EXPORT_COLUMNS))
        for data_row in table:
            ws.append(data_row)
        buffer = io.BytesIO()
        wb.save(buffer)
        file_bytes = buffer.getvalue()
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        text_buffer = io.StringIO()
        writer = csv.writer(text_buffer)
        writer.writerow(EXPORT_COLUMNS)
        writer.writerows(table)
        file_bytes = text_buffer.getvalue().encode()
        media_type = "text/csv"

    ext = "xlsx" if export_format == "xlsx" else "csv"
    filename = _export_filename(habitation.name, period_type, year, month, from_date, to_date, ext)
    return file_bytes, media_type, filename, f'attachment; filename="{filename}"'


def _blank(record: dict[str, Any], key: str) -> bool:
    return key not in record or record[key] is None or str(record[key]).strip() == ""


def _row_to_payload_dict(record: dict[str, Any]) -> dict[str, Any]:
    """Builds the dict handed to DailyLogIn.model_validate() for one CSV
    row, deriving total_collected_tonnes from its components when the
    column is blank or missing — the "automatic summary derivation" a bulk
    sheet gets that a single manual entry (which must state its own total
    explicitly) doesn't."""
    organic = float(record["organic_tonnes"]) if not _blank(record, "organic_tonnes") else None
    dry = float(record["dry_recyclable_tonnes"]) if not _blank(record, "dry_recyclable_tonnes") else None
    hazardous = float(record["hazardous_tonnes"]) if not _blank(record, "hazardous_tonnes") else None

    if _blank(record, "total_collected_tonnes"):
        total = None if organic is None or dry is None else organic + dry + (hazardous or 0.0)
    else:
        total = float(record["total_collected_tonnes"])

    payload: dict[str, Any] = {
        "log_date": record.get("log_date") or None,
        "total_collected_tonnes": total,
        "organic_tonnes": organic,
        "dry_recyclable_tonnes": dry,
        "hazardous_tonnes": hazardous,
        "vehicles_deployed": record.get("vehicles_deployed") or None,
        "trips_completed": record.get("trips_completed") or None,
        "diesel_consumed_litres": record.get("diesel_consumed_litres") or None,
        "collection_coverage_pct_observed": record.get("collection_coverage_pct_observed") or None,
        "notes": record.get("notes") or None,
    }
    if not _blank(record, "anomaly_flag"):
        payload["anomaly_flag"] = str(record["anomaly_flag"]).strip().upper()
    return payload


def _format_row_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return "; ".join(parts)
    return str(exc)


async def bulk_import_csv(db: AsyncSession, habitation_id: uuid.UUID, data: bytes, user: User) -> BulkImportResult:
    await get_habitation_or_404(db, habitation_id)

    try:
        df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
    except Exception as exc:  # pandas raises several different error types on a corrupt file
        raise AppError("DAILY_LOG_CSV_UNREADABLE", f"Could not read CSV: {exc}", 422) from exc

    normalized_columns = {str(c).strip().lower() for c in df.columns}
    missing = REQUIRED_CSV_COLUMNS - normalized_columns
    if missing:
        raise AppError(
            "DAILY_LOG_CSV_MISSING_COLUMNS",
            f"CSV is missing required column(s): {', '.join(sorted(missing))}",
            422,
        )
    df.columns = [str(c).strip().lower() for c in df.columns]

    created_count = 0
    updated_count = 0
    errors: list[BulkImportRowError] = []

    for row_number, record in enumerate(df.to_dict(orient="records"), start=1):
        try:
            payload = DailyLogIn.model_validate(_row_to_payload_dict(record))
        except (ValueError, ValidationError) as exc:
            errors.append(BulkImportRowError(row_number=row_number, message=_format_row_error(exc)))
            continue

        try:
            _, created = await upsert_daily_log(db, habitation_id, payload, user)
        except AppError as exc:
            errors.append(BulkImportRowError(row_number=row_number, message=exc.message))
            continue

        if created:
            created_count += 1
        else:
            updated_count += 1

    return BulkImportResult(
        total_rows=len(df),
        created_count=created_count,
        updated_count=updated_count,
        error_count=len(errors),
        errors=errors,
    )
