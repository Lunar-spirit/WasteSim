"""BG-07: renders a report on the "ingest" queue — the design's own choice,
grouping it with the other file-producing/consuming jobs (uploads) rather
than with simulate/optimize.
"""

import asyncio
import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.reports.models import Report, ReportStatus
from app.reports.service import generate_report
from app.workers.celery_app import celery_app


async def run_report_generation(
    report_id: str, session_factory: Callable[[], AsyncSession] = AsyncSessionLocal
) -> None:
    async with session_factory() as db:
        report = await db.get(Report, uuid.UUID(report_id))
        if report is None:
            return
        try:
            await generate_report(db, report)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            async with session_factory() as failure_db:
                failed = await failure_db.get(Report, uuid.UUID(report_id))
                if failed is not None:
                    failed.status = ReportStatus.FAILED
                    failed.error_detail = f"{type(exc).__name__}: {exc}"
                    await failure_db.commit()
            raise


@celery_app.task(bind=True, max_retries=2, name="app.workers.tasks_reports.generate")
def generate(self, report_id: str) -> None:
    # 2 retries, matching BG-07's own stated failure policy.
    asyncio.run(run_report_generation(report_id))
