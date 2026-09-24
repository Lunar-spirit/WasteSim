"""BG-08 (design section 8, BR-32): "A run left in RUNNING for longer than
its timeout is marked FAILED by the janitor job, never left hanging."
Celery Beat fires `janitor_sweep` every 10 minutes (registered in
celery_app.py's beat_schedule); the real work is a plain async function so
a test can call it directly, same pattern as every other worker task.

BG-09 (expired-token cleanup) and BG-10 (overlay cache warmer) are small,
optional hygiene jobs the design also lists under Celery Beat; out of scope
for this pass — nothing in the API or the ten CLAUDE.md rules depends on
either running, unlike BG-08's BR-32.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, WorkerSessionLocal
from app.optimization.models import AnalysisStatus, OptimizationRun
from app.reports.models import Report, ReportStatus
from app.sensitivity.models import SensitivityAnalysis
from app.simulation.models import RunStatus, SimulationRun
from app.workers.celery_app import celery_app

# Generous relative to each job's own hard timeout (BG-04: 10 minutes;
# BG-05/BG-06 run many engine calls so are allowed longer) — the janitor is
# a backstop for a genuinely stuck job, not a race against normal runtime.
SIMULATION_TIMEOUT = timedelta(minutes=20)
OPTIMIZATION_TIMEOUT = timedelta(minutes=45)
SENSITIVITY_TIMEOUT = timedelta(minutes=45)
REPORT_TIMEOUT = timedelta(minutes=10)


async def run_janitor_sweep(session_factory: Callable[[], AsyncSession] = AsyncSessionLocal) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    swept = {"simulation_runs": 0, "optimization_runs": 0, "sensitivity_analyses": 0, "reports": 0}

    async with session_factory() as db:
        stuck_runs = await db.scalars(
            select(SimulationRun).where(
                SimulationRun.status == RunStatus.RUNNING,
                SimulationRun.started_at < now - SIMULATION_TIMEOUT,
            )
        )
        for run in stuck_runs:
            run.status = RunStatus.FAILED
            run.error_detail = "stuck in RUNNING past timeout, marked FAILED by the janitor job (BR-32)"
            swept["simulation_runs"] += 1

        stuck_optimizations = await db.scalars(
            select(OptimizationRun).where(
                OptimizationRun.status == AnalysisStatus.RUNNING,
                OptimizationRun.created_at < now - OPTIMIZATION_TIMEOUT,
            )
        )
        for run in stuck_optimizations:
            run.status = AnalysisStatus.FAILED
            run.infeasible_reason = "stuck in RUNNING past timeout, marked FAILED by the janitor job (BR-32)"
            swept["optimization_runs"] += 1

        stuck_analyses = await db.scalars(
            select(SensitivityAnalysis).where(
                SensitivityAnalysis.status == AnalysisStatus.RUNNING,
                SensitivityAnalysis.created_at < now - SENSITIVITY_TIMEOUT,
            )
        )
        for analysis in stuck_analyses:
            analysis.status = AnalysisStatus.FAILED
            swept["sensitivity_analyses"] += 1

        stuck_reports = await db.scalars(
            select(Report).where(
                Report.status == ReportStatus.GENERATING,
                Report.created_at < now - REPORT_TIMEOUT,
            )
        )
        for report in stuck_reports:
            report.status = ReportStatus.FAILED
            report.error_detail = "stuck in GENERATING past timeout, marked FAILED by the janitor job (BR-32)"
            swept["reports"] += 1

        await db.commit()

    return swept


@celery_app.task(name="app.workers.beat.janitor_sweep")
def janitor_sweep() -> dict[str, int]:
    import asyncio

    return asyncio.run(run_janitor_sweep(session_factory=WorkerSessionLocal))


celery_app.conf.beat_schedule = {
    "janitor-sweep-every-10-minutes": {
        "task": "app.workers.beat.janitor_sweep",
        "schedule": 600.0,
    },
}
