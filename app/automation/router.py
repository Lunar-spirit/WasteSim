import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.automation import service
from app.automation.schemas import AutoPopulateIn, AutoPopulateOut
from app.core.db import get_db
from app.core.deps import get_current_user

router = APIRouter(tags=["automation"])


@router.post("/api/v1/habitations/{habitation_id}/auto-populate")
async def auto_populate_habitation(
    habitation_id: uuid.UUID,
    payload: AutoPopulateIn = AutoPopulateIn(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Not a 202 background job (unlike a simulation or optimization run):
    # each external call is capped at 15s and all three run concurrently, so
    # the whole request completes in one HTTP round trip — same reasoning a
    # single category PUT is synchronous. Nothing here skips /validate or
    # /commit; the caller still runs those explicitly afterward.
    result = await service.auto_populate(db, habitation_id, payload, current_user)
    await db.commit()
    return {"success": True, "data": AutoPopulateOut(**result).model_dump()}
