"""BG-04: runs a simulation on the "simulate" queue — its own queue,
separate from "ingest" (design AD-18), so a multi-second engine run never
queues behind a file upload or vice versa.

Same shape as BG-01/BG-02: the real logic (`execute_run`, in
app/simulation/service.py) is a plain async function that knows nothing
about Celery, so a test can call `run_simulation` directly with the test
suite's own NullPool session maker.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.engine.invariants import MassBalanceError
from app.simulation.models import RunStatus, SimulationRun
from app.simulation.service import execute_run
from app.workers.celery_app import celery_app


async def run_simulation(
    run_id: str, session_factory: Callable[[], AsyncSession] = AsyncSessionLocal
) -> None:
    async with session_factory() as db:
        run = await db.get(SimulationRun, uuid.UUID(run_id))
        if run is None:
            return

        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        await db.flush()
        try:
            await execute_run(db, run)
            await db.commit()
        except MassBalanceError as exc:
            await db.rollback()
            async with session_factory() as failure_db:
                failed = await failure_db.get(SimulationRun, uuid.UUID(run_id))
                if failed is not None:
                    failed.status = RunStatus.FAILED
                    failed.error_detail = f"mass balance violated at month {exc.month}: {exc.message}"
                    await failure_db.commit()
            raise
        except Exception as exc:
            await db.rollback()
            async with session_factory() as failure_db:
                failed = await failure_db.get(SimulationRun, uuid.UUID(run_id))
                if failed is not None:
                    failed.status = RunStatus.FAILED
                    failed.error_detail = f"{type(exc).__name__}: {exc}"
                    await failure_db.commit()
            raise


@celery_app.task(bind=True, max_retries=0, name="app.workers.tasks_simulate.simulate")
def simulate(self, run_id: str) -> None:
    # No automatic retry: a run that fails (a mass-balance violation, a bad
    # override slipping past validation) failed because of its inputs, not
    # a transient infra hiccup — retrying would just fail again identically.
    asyncio.run(run_simulation(run_id))
