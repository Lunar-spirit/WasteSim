"""Static + DB-aware answers for dashboard-usage questions ("why is this
blocked", "how do I fix X") — distinct from app/chat/tools.py's fixed tool
set, which only answers grounded DATA questions (a run's budget, findings,
etc). Checked before the tool-intent matcher in app/chat/service.py's
answer_chat_message() for one concrete reason: "why can't I run
optimization?" contains the word "optimization", which is exactly what
router_llm.py's own deterministic matcher uses to trigger
create_optimization — without this layer running first, a question would
get silently misrouted into actually *starting* a real optimization run.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

_OPTIMIZATION_BLOCKED_RE = re.compile(
    r"why.*(can'?t|cannot|won'?t).*optimi[sz]|optimi[sz]ation.*(not running|blocked|disabled|greyed|grayed|stuck)"
    r"|can'?t run optimi[sz]ation",
    re.I,
)
_FIX_PARAMETERS_RE = re.compile(
    r"fix.*parameter|parameter.*(error|invalid|wrong)|how.*(commit|validate).*parameter"
    r"|how.*(fix|calibrate).*(parameter|waste)",
    re.I,
)
_TORNADO_RE = re.compile(r"tornado", re.I)


async def _optimization_blocked_answer(db: AsyncSession, habitation_id: uuid.UUID | None) -> str:
    if habitation_id is None:
        return (
            "Optimization needs a completed BASE simulation run and a VALIDATED (committed) parameter set "
            "first. Select a habitation, then check its Simulations tab."
        )
    from app.optimization.service import get_optimization_readiness

    readiness = await get_optimization_readiness(db, habitation_id)
    if readiness["can_run"]:
        return "You're all set — parameters are validated and a base simulation is complete. Click Start Optimization Search."
    reason = readiness["blocking_reason"] or "a prerequisite is missing"
    action = f" {readiness['action_label']}." if readiness["action_label"] else ""
    return f"{reason}{action}"


def _fix_parameters_answer() -> str:
    return (
        "On the Parameters tab, open the Waste Baseline category and make sure the waste composition "
        "percentages (organic, plastic, paper, glass, metal, other) sum to exactly 100%. Fill in every "
        "required field across all 7 categories, then click Validate — once it passes with zero errors, "
        "click Commit to lock that version in as VALIDATED so it's ready to simulate."
    )


def _tornado_answer() -> str:
    return (
        "The Tornado chart (Sensitivity tab) ranks parameters by how much they move a chosen outcome — "
        "usually landfill exhaustion year — when swept across their own range. The longest bar is the "
        "parameter your result is most sensitive to (highest elasticity); a short bar means changing that "
        "parameter barely moves the outcome."
    )


async def match_faq(db: AsyncSession, message: str, habitation_id: uuid.UUID | None) -> str | None:
    if _OPTIMIZATION_BLOCKED_RE.search(message):
        return await _optimization_blocked_answer(db, habitation_id)
    if _FIX_PARAMETERS_RE.search(message):
        return _fix_parameters_answer()
    if _TORNADO_RE.search(message):
        return _tornado_answer()
    return None


__all__ = ["match_faq"]
