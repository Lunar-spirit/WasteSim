import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.auth.models import User, UserRole
from app.core.db import get_db
from app.core.deps import require_role
from app.habitation.service import get_habitation_or_404

router = APIRouter(tags=["audit"])


@router.get("/api/v1/habitations/{habitation_id}/audit-logs")
async def get_habitation_audit_logs(
    habitation_id: uuid.UUID,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.POLICY_VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    await get_habitation_or_404(db, habitation_id)
    # Scoped to actions logged directly against the habitation entity itself
    # — audit_logs has no habitation_id column (design's own table doesn't
    # give it one), so an action against e.g. one of its parameter sets or
    # runs is filed under that entity's own type/id, not reachable from
    # here without a schema change out of scope for this pass.
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == "habitation", AuditLog.entity_id == str(habitation_id))
        .order_by(AuditLog.created_at.desc())
    )
    rows = list(await db.scalars(stmt))
    return {
        "success": True,
        "data": [
            {
                "id": str(r.id),
                "request_id": r.request_id,
                "user_id": str(r.user_id) if r.user_id else None,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "details": r.details,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }
