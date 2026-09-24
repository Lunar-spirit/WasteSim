"""BG-05: runs an optimization search on its own "optimize" queue (design
AD-18) — a several-hundred-evaluation search must never queue behind, or
make a user's single simulation wait behind, unrelated work on "simulate"
or "ingest".

Same shape as BG-01/BG-04: the real logic (`run_search`, in
app/optimization/service.py) is a plain async function that knows nothing
about Celery, so a test can call `run_optimization` directly with the test
suite's own NullPool session maker.
"""

import asyncio
import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, WorkerSessionLocal
from app.optimization.models import AnalysisStatus, OptimizationRun
from app.optimization.service import run_search
from app.workers.celery_app import celery_app


async def run_optimization(
    optimization_id: str, session_factory: Callable[[], AsyncSession] = AsyncSessionLocal
) -> None:
    async with session_factory() as db:
        run = await db.get(OptimizationRun, uuid.UUID(optimization_id))
        if run is None:
            return
        try:
            await run_search(db, run)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            async with session_factory() as failure_db:
                failed = await failure_db.get(OptimizationRun, uuid.UUID(optimization_id))
                if failed is not None:
                    failed.status = AnalysisStatus.FAILED
                    failed.infeasible_reason = f"{type(exc).__name__}: {exc}"
                    await failure_db.commit()
            raise


@celery_app.task(bind=True, max_retries=0, name="app.workers.tasks_optimize.optimize")
def optimize(self, optimization_id: str) -> None:
    asyncio.run(run_optimization(optimization_id, session_factory=WorkerSessionLocal))
