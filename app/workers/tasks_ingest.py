"""BG-02: the tabular ingestion worker. Runs on the Celery "ingest" queue so
a slow parse/validate never blocks the upload endpoint's own response
(rule #9 — long jobs return 202 + job_id, nothing blocks).

The actual logic (`validate_upload_rows`, in app/ingestion/service.py) is a
plain async function, independent of Celery. This module is only the thin
sync-process wrapper: open a fresh DB session (a Celery worker is a separate
process from the API, so it cannot reuse FastAPI's connection pool), run the
async logic to completion with asyncio.run(), and translate a failure into
Celery's own retry mechanism. Keeping the logic itself Celery-agnostic means
a test can call `run_ingest_tabular_upload` directly with no broker, no
worker process, and no event loop juggling.
"""

import asyncio
import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, WorkerSessionLocal
from app.ingestion.models import DatasetUpload, UploadStatus
from app.ingestion.service import validate_upload_rows
from app.workers.celery_app import celery_app

# 10s / 40s / 160s — same backoff as BG-01 (the future GIS worker), so both
# ingestion paths behave identically to someone watching a stuck upload.
_BACKOFF_SECONDS = [10, 40, 160]


async def run_ingest_tabular_upload(
    upload_id: str, session_factory: Callable[[], AsyncSession] = AsyncSessionLocal
) -> None:
    """`session_factory` defaults to the app's real (pooled) session maker —
    correct for a live Celery worker, which is its own process with its own
    event loop. Tests instead pass the test suite's NullPool session maker
    so this can be called directly, in-process, from inside a test's own
    event loop without reusing a pooled connection across loops (see
    tests/conftest.py's NullPool comment for why that combination crashes).
    """
    async with session_factory() as db:
        upload = await db.get(DatasetUpload, uuid.UUID(upload_id))
        if upload is None:
            return  # deleted between enqueue and execution; nothing to do

        upload.status = UploadStatus.PROCESSING
        await db.flush()
        try:
            await validate_upload_rows(db, upload)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            async with session_factory() as failure_db:
                failed = await failure_db.get(DatasetUpload, uuid.UUID(upload_id))
                if failed is not None:
                    failed.status = UploadStatus.FAILED
                    failed.error_summary = f"{type(exc).__name__}: {exc}"
                    await failure_db.commit()
            raise


@celery_app.task(bind=True, max_retries=3, name="app.workers.tasks_ingest.ingest_tabular_upload")
def ingest_tabular_upload(self, upload_id: str) -> None:
    try:
        asyncio.run(run_ingest_tabular_upload(upload_id, session_factory=WorkerSessionLocal))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            # Final failure already recorded FAILED status inside
            # run_ingest_tabular_upload's except block — nothing more to do
            # here except stop retrying and surface the error to Celery.
            raise
        delay = _BACKOFF_SECONDS[min(self.request.retries, len(_BACKOFF_SECONDS) - 1)]
        raise self.retry(exc=exc, countdown=delay)
