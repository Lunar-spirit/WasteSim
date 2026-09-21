import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.auth.models import User, UserRole
from app.core.db import get_db
from app.core.deps import get_current_user, require_role

router = APIRouter(tags=["platform"])


@router.get("/api/v1/habitations/{habitation_id}/audit-logs")
async def get_habitation_audit_logs(
    habitation_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.POLICY_VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_id == str(habitation_id))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.scalars(stmt)
    logs = list(result)
    return {
        "success": True,
        "data": [
            {
                "id": log.id,
                "request_id": log.request_id,
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "created_at": log.created_at,
            }
            for log in logs
        ],
    }


@router.get("/ready")
async def readiness_probe(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text
    checks: dict[str, Any] = {"database": False, "redis": False, "storage": False}

    # DB check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:
        checks["database_error"] = str(exc)

    # Redis check
    try:
        from redis.asyncio import from_url
        from app.core.config import settings
        r = from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    # Storage check
    try:
        from app.core import storage
        storage.ensure_bucket()
        checks["storage"] = True
    except Exception:
        checks["storage"] = False

    is_ready = checks["database"]  # DB is the hard dependency
    return {
        "success": is_ready,
        "data": {
            "status": "ready" if is_ready else "degraded",
            "components": checks,
        },
    }
