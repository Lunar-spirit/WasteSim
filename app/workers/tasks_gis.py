"""BG-01: the GIS ingestion worker. Same shape as BG-02
(app/workers/tasks_ingest.py) — a thin sync-process Celery wrapper around a
plain async function, so a test can call `run_ingest_gis_layer` directly
with no broker and no worker process.

Unlike a tabular upload, a GIS layer has no separate "stage, then confirm"
step (BR-18 is tabular-only): the worker's own transaction either produces a
READY layer or nothing at all, so success goes straight to INGESTED.
"""

import asyncio
import uuid
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import AsyncSessionLocal
from app.gis.models import GISLayer, LayerStatus
from app.gis.service import process_gis_file_upload
from app.ingestion.models import DatasetUpload, UploadStatus
from app.validation.models import ValidationResult
from app.workers.celery_app import celery_app

_BACKOFF_SECONDS = [10, 40, 160]


async def run_ingest_gis_layer(
    upload_id: str, session_factory: Callable[[], AsyncSession] = AsyncSessionLocal
) -> None:
    async with session_factory() as db:
        upload = await db.get(DatasetUpload, uuid.UUID(upload_id))
        if upload is None:
            return

        upload.status = UploadStatus.PROCESSING
        await db.flush()
        try:
            data = storage.get_object(upload.storage_key)
            report = await process_gis_file_upload(db, upload, data)
            # "rows" doesn't apply to a GIS layer — feature_count lives on
            # gis_layers instead — and there is no separate /ingest step for
            # GIS (BR-18 is tabular-only), so success goes straight to
            # INGESTED.
            upload.status = (
                UploadStatus.INGESTED if report.result != ValidationResult.FAIL else UploadStatus.REJECTED
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            async with session_factory() as failure_db:
                failed_upload = await failure_db.get(DatasetUpload, uuid.UUID(upload_id))
                failed_layer = await failure_db.scalar(
                    select(GISLayer).where(GISLayer.upload_id == uuid.UUID(upload_id))
                )
                if failed_upload is not None:
                    failed_upload.status = UploadStatus.FAILED
                    failed_upload.error_summary = f"{type(exc).__name__}: {exc}"
                if failed_layer is not None:
                    failed_layer.status = LayerStatus.FAILED
                await failure_db.commit()
            raise


@celery_app.task(bind=True, max_retries=3, name="app.workers.tasks_gis.ingest_gis_layer")
def ingest_gis_layer(self, upload_id: str) -> None:
    try:
        asyncio.run(run_ingest_gis_layer(upload_id))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            raise
        delay = _BACKOFF_SECONDS[min(self.request.retries, len(_BACKOFF_SECONDS) - 1)]
        raise self.retry(exc=exc, countdown=delay)
