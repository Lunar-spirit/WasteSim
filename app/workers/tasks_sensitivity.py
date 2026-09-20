"""BG-06: runs a sensitivity sweep on the "simulate" queue — the design's
own words for this job ("Celery simulate queue (chord)"), since each point
is itself a simulation run and belongs with the rest of that work, not with
ingestion or optimization.

Same shape as every other worker in this project: `run_sweep_task` is a
plain async function (the real logic lives in app/sensitivity/service.py's
`run_sweep`) so a test can call it directly with the test suite's own
NullPool session maker.
"""

import asyncio
import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.optimization.models import AnalysisStatus
from app.sensitivity.models import SensitivityAnalysis
from app.sensitivity.service import run_sweep
from app.workers.celery_app import celery_app


async def run_sweep_task(
    analysis_id: str, session_factory: Callable[[], AsyncSession] = AsyncSessionLocal
) -> None:
    async with session_factory() as db:
        analysis = await db.get(SensitivityAnalysis, uuid.UUID(analysis_id))
        if analysis is None:
            return
        try:
            await run_sweep(db, analysis, session_factory)
        except Exception:
            async with session_factory() as failure_db:
                failed = await failure_db.get(SensitivityAnalysis, uuid.UUID(analysis_id))
                if failed is not None and failed.status != AnalysisStatus.COMPLETED:
                    failed.status = AnalysisStatus.FAILED
                    await failure_db.commit()
            raise


@celery_app.task(bind=True, max_retries=0, name="app.workers.tasks_sensitivity.sweep")
def sweep(self, analysis_id: str) -> None:
    asyncio.run(run_sweep_task(analysis_id))
