import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.budget import service
from app.budget.models import BudgetLine
from app.core.db import get_db
from app.core.deps import get_current_user
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.simulation.service import get_run_or_404

router = APIRouter(tags=["budget"])


async def _ensure_run_access(db: AsyncSession, run_id: uuid.UUID, user: User):
    run = await get_run_or_404(db, run_id)
    habitation = await get_habitation_or_404(db, run.habitation_id)
    await ensure_read_access(db, user, habitation)
    return run


@router.get("/api/v1/simulations/{run_id}/budget/lines")
async def get_budget_lines(
    run_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _ensure_run_access(db, run_id, current_user)
    rows = list(await db.scalars(select(BudgetLine).where(BudgetLine.run_id == run_id).order_by(BudgetLine.year_index)))
    return {
        "success": True,
        "data": [
            {
                "year_index": r.year_index,
                "kind": r.kind.value,
                "category": r.category.value,
                "amount_inr": float(r.amount_inr),
                "discounted_inr": float(r.discounted_inr),
                "note": r.note,
            }
            for r in rows
        ],
    }


@router.get("/api/v1/simulations/{run_id}/budget/summary")
async def get_budget_summary(
    run_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _ensure_run_access(db, run_id, current_user)
    summary = await service.get_budget_summary(db, run_id)
    return {
        "success": True,
        "data": {
            "run_id": summary["run_id"],
            "total_opex_inr": summary["total_opex_inr"],
            "total_capex_inr": summary["total_capex_inr"],
            "total_cost_inr": summary["total_cost_inr"],
            "npv_total_cost_inr": summary["npv_total_cost_inr"],
            "by_category": summary["by_category"],
        },
    }
