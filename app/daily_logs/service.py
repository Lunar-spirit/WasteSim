"""Daily Waste Collection & Operational Logging — see app/daily_logs/models.py
for why this is a plain upsert table, not insert-only.

Bulk CSV import runs synchronously in the request (unlike app/ingestion/'s
Celery-backed pipeline for PARAMETERS/GIS uploads): a daily-log sheet is at
most a few hundred rows (a year of daily entries), parses and upserts in
well under a second, so there is no "long job" here for rule 9 to apply to.
"""

from __future__ import annotations

import io
import uuid
from datetime import date
from typing import Any

import pandas as pd
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
