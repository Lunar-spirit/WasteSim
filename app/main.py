from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.budget.router import router as budget_router
from app.chat.router import router as chat_router
from app.comparison.router import router as comparison_router
from app.core.errors import register_exception_handlers
from app.core.logging import RequestContextMiddleware
from app.gis.router import router as gis_router
from app.habitation.router import router as habitation_router
from app.ingestion.router import router as ingestion_router
from app.optimization.router import router as optimization_router
from app.parameters.router import router as parameters_router
from app.reports.router import router as reports_router
from app.sensitivity.router import router as sensitivity_router
from app.scenario.router import router as scenario_router
from app.simulation.router import router as simulation_router
from app.validation.router import router as validation_router

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Best-effort: a dev machine that hasn't started MinIO yet shouldn't
    # crash the whole API on boot — the upload endpoint itself still
    # returns a clean 503 STORAGE_UNAVAILABLE per request if it's down.
    try:
        from app.core import storage

        storage.ensure_bucket()
    except Exception as exc:
        structlog.get_logger("swms").warning("minio_bucket_check_failed", error=str(exc))
    yield


app = FastAPI(
    title="SWMS Backend",
    description="Smart Waste Management Simulator — Drop 1 (Evaluation 1)",
    version="0.1.0",
    lifespan=_lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(RequestContextMiddleware)

register_exception_handlers(app)

app.include_router(auth_router)
app.include_router(habitation_router)
app.include_router(parameters_router)
app.include_router(validation_router)
app.include_router(gis_router)
app.include_router(ingestion_router)
app.include_router(simulation_router)
app.include_router(budget_router)
app.include_router(scenario_router)
app.include_router(optimization_router)
app.include_router(sensitivity_router)
app.include_router(comparison_router)
app.include_router(reports_router)
app.include_router(chat_router)
app.include_router(audit_router)


@app.get("/health")
async def health():
    return {"success": True, "data": {"status": "ok"}}


@app.get("/ready")
async def ready():
    # API-89: liveness (/health) says the process is up; readiness also
    # checks the database is actually reachable, since a process that is
    # running but can't reach Postgres shouldn't receive traffic.
    from sqlalchemy import text

    from app.core.db import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(status_code=503, content={"success": False, "error": {"code": "NOT_READY", "message": str(exc)}})
    return {"success": True, "data": {"status": "ready"}}
