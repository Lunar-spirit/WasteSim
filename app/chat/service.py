"""Module M15 orchestration (design 5.8's pipeline): question -> intent
extraction -> permission check (inherited from the tool itself) -> tool
execution -> numeric grounding -> prose -> persistence of the message, its
citations and its tool call. A tool's own AppError becomes a normal
conversational outcome here, never an HTTP error for the /query endpoint
itself (design: "the answer explains the restriction").
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.budget.service import get_budget_summary
from app.chat.faq import match_faq
from app.chat.grounding import build_grounded_answer, polish_prose
from app.chat.llm_providers import call_llm
from app.chat.models import ChatMessage, ChatRole, ChatSession, ChatToolCall, ToolStatus
from app.chat.router_llm import extract_intent, extract_numbers
from app.chat.tools import TOOL_REGISTRY
from app.core.errors import AppError
from app.habitation.models import Habitation
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.optimization.models import AnalysisStatus, OptimizationRun
from app.parameters.models import ParameterSet
from app.parameters.service import get_parameter_set_full
from app.simulation.models import RunFinding, RunStatus, RunType, SimulationRun

_HISTORY_TURNS = 6


async def create_session(db: AsyncSession, habitation_id: uuid.UUID, user: User) -> ChatSession:
    habitation = await get_habitation_or_404(db, habitation_id)
    await ensure_read_access(db, user, habitation)
    session = ChatSession(habitation_id=habitation_id, user_id=user.id)
    db.add(session)
    await db.flush()
    return session


async def list_sessions(db: AsyncSession, user: User) -> list[ChatSession]:
    stmt = select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.last_active_at.desc())
    return list(await db.scalars(stmt))


async def get_session_or_404(db: AsyncSession, session_id: uuid.UUID) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise AppError("SESSION_NOT_FOUND", "Chat session not found", 404)
    return session


def ensure_session_owner(session: ChatSession, user: User) -> None:
    if session.user_id != user.id and user.role != UserRole.ADMIN:
        raise AppError("FORBIDDEN_RESOURCE", "Only the session owner (or ADMIN) may access this", 403)


async def get_messages(db: AsyncSession, session: ChatSession) -> list[ChatMessage]:
    stmt = select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.id)
    return list(await db.scalars(stmt))


async def get_tool_calls(db: AsyncSession, message_id: int) -> list[ChatToolCall]:
    stmt = select(ChatToolCall).where(ChatToolCall.message_id == message_id).order_by(ChatToolCall.id)
    return list(await db.scalars(stmt))


async def _most_recent_completed_run_id(db: AsyncSession, habitation_id: uuid.UUID) -> uuid.UUID | None:
    stmt = (
        select(SimulationRun.id)
        .where(SimulationRun.habitation_id == habitation_id, SimulationRun.status == RunStatus.COMPLETED)
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


def _status_for(exc: AppError) -> ToolStatus:
    if exc.status_code == 403:
        return ToolStatus.DENIED
    if exc.status_code == 404:
        return ToolStatus.NOT_FOUND
    return ToolStatus.ERROR


async def handle_query(db: AsyncSession, session: ChatSession, message: str, run_id_hint: uuid.UUID | None, user: User) -> ChatMessage:
    start = time.monotonic()
    db.add(ChatMessage(session_id=session.id, role=ChatRole.USER, content=message))
    await db.flush()

    history = await get_messages(db, session)
    history_payload = [
        {"role": m.role.value.lower(), "content": m.content} for m in history if m.role != ChatRole.SYSTEM
    ][-_HISTORY_TURNS:]

    default_run_id = run_id_hint or await _most_recent_completed_run_id(db, session.habitation_id)
    tool_name, arguments, used_llm = extract_intent(
        message, history_payload, str(default_run_id) if default_run_id else None
    )

    if tool_name is None or tool_name not in TOOL_REGISTRY:
        content = (
            "I'm not sure which of my tools answers that. Try asking about a run's findings, "
            "its budget, or ask me to compare two runs."
        )
        assistant = ChatMessage(
            session_id=session.id, role=ChatRole.ASSISTANT, content=content, citations=[],
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        db.add(assistant)
        session.last_active_at = datetime.now(timezone.utc)
        await db.commit()
        return assistant

    tool_fn, _is_write = TOOL_REGISTRY[tool_name]
    tool_start = time.monotonic()
    status = ToolStatus.OK
    result: dict = {}
    try:
        result = await tool_fn(db, user, session.habitation_id, **arguments)
    except AppError as exc:
        status = _status_for(exc)
        result = {"error": exc.message}
    except (TypeError, ValueError) as exc:
        status = ToolStatus.ERROR
        result = {"error": f"bad arguments: {exc}"}
    duration_ms = int((time.monotonic() - tool_start) * 1000)

    citations: list[dict] = []
    if status == ToolStatus.OK:
        deterministic_prose, citations = build_grounded_answer(
            tool_name, str(default_run_id) if default_run_id else None, arguments, result
        )
        content = polish_prose(message, deterministic_prose) if used_llm else deterministic_prose
    elif status == ToolStatus.DENIED:
        content = f"I can't do that — {result['error']}"
    elif status == ToolStatus.NOT_FOUND:
        content = f"I couldn't find that: {result['error']}"
    else:
        content = "Something went wrong running that; nothing was changed."

    assistant = ChatMessage(
        session_id=session.id, role=ChatRole.ASSISTANT, content=content, citations=citations,
        latency_ms=int((time.monotonic() - start) * 1000),
    )
    db.add(assistant)
    await db.flush()

    db.add(
        ChatToolCall(
            message_id=assistant.id,
            tool_name=tool_name,
            arguments=arguments,
            result_summary=result,
            status=status,
            duration_ms=duration_ms,
        )
    )
    session.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    return assistant


async def assemble_habitation_context(db: AsyncSession, habitation_id: uuid.UUID) -> dict[str, Any] | None:
    """A compact, cheap-to-query snapshot for the floating copilot's system
    prompt — deliberately not the same as tools.py's get_habitation_summary
    (that one is a chat *tool*, answering an explicit "tell me about this
    habitation" question; this one is background context injected into
    every turn)."""
    habitation = await db.get(Habitation, habitation_id)
    if habitation is None or habitation.deleted_at is not None:
        return None

    param_status: str | None = None
    waste_tpd: float | None = None
    if habitation.active_parameter_set_id is not None:
        ps = await db.get(ParameterSet, habitation.active_parameter_set_id)
        if ps is not None:
            param_status = ps.status.value
            full = await get_parameter_set_full(db, ps.id)
            population = full["categories"].get("demography", {}).get("population")
            per_capita = (full["waste_baseline"] or {}).get("per_capita_generation_kg_day")
            if population is not None and per_capita is not None:
                waste_tpd = round(float(population) * float(per_capita) / 1000.0, 2)
    else:
        draft = await db.scalar(
            select(ParameterSet)
            .where(ParameterSet.habitation_id == habitation_id)
            .order_by(ParameterSet.version_no.desc())
            .limit(1)
        )
        param_status = draft.status.value if draft is not None else None

    base_run = await db.scalar(
        select(SimulationRun)
        .where(
            SimulationRun.habitation_id == habitation_id,
            SimulationRun.run_type == RunType.BASE,
            SimulationRun.status == RunStatus.COMPLETED,
        )
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )
    landfill_exhaustion_year: float | None = None
    npv_total_cost_inr: float | None = None
    if base_run is not None:
        finding = await db.scalar(
            select(RunFinding).where(
                RunFinding.run_id == base_run.id, RunFinding.code == "LANDFILL_EXHAUSTION_YEAR"
            )
        )
        if finding is not None and finding.numeric_value is not None:
            landfill_exhaustion_year = float(finding.numeric_value)
        budget = await get_budget_summary(db, base_run.id)
        npv_total_cost_inr = budget["npv_total_cost_inr"]

    has_optimized = (
        await db.scalar(
            select(OptimizationRun.id)
            .where(OptimizationRun.habitation_id == habitation_id, OptimizationRun.status == AnalysisStatus.COMPLETED)
            .limit(1)
        )
    ) is not None

    return {
        "habitation_id": str(habitation_id),
        "name": habitation.name,
        "area_sqkm": float(habitation.area_sqkm) if habitation.area_sqkm is not None else None,
        "param_status": param_status,
        "waste_tpd": waste_tpd,
        "has_base_run": base_run is not None,
        "landfill_exhaustion_year": landfill_exhaustion_year,
        "npv_total_cost_inr": npv_total_cost_inr,
        "has_optimized": has_optimized,
    }


def build_system_prompt(context: dict[str, Any] | None) -> str:
    base = (
        "You are the SWMS Lite Copilot, an AI assistant for municipal solid waste planners in India. "
        "Keep answers concise, direct, and actionable. Guide the user on how to use the dashboard, "
        "resolve blocked runs, and interpret sensitivity charts."
    )
    if context is None:
        return f"{base}\nNo habitation is currently selected."

    def _fmt(value: float | None, decimals: int = 2) -> str:
        return f"{value:.{decimals}f}" if value is not None else "unknown"

    return (
        f"{base}\n\n"
        f"Current Active Habitation: {context['name']} (Area: {_fmt(context['area_sqkm'])} sq km).\n"
        f"Parameters: {context['param_status'] or 'not set up'}, Waste: {_fmt(context['waste_tpd'])} t/day.\n"
        f"Simulation Base Run: {'yes' if context['has_base_run'] else 'no'}, "
        f"Landfill Life: {_fmt(context['landfill_exhaustion_year'], 0)} years."
    )


async def answer_chat_message(
    db: AsyncSession,
    habitation_id: uuid.UUID | None,
    message: str,
    history: list[dict[str, str]],
    user: User,
) -> dict[str, Any]:
    """Stateless counterpart to handle_query() for POST /api/v1/chat/message
    — nothing is written to chat_sessions/chat_messages; the caller carries
    its own running `history` each call. Routing order: FAQ/guidance (fast,
    and must run before the tool matcher — see app/chat/faq.py's docstring)
    -> the existing grounded tool set (data questions, BR-30-safe) -> a real
    LLM free-chat reply (verified to introduce no unverified number) -> a
    safe static fallback. Only an AppError from the initial access check
    (habitation not found / no read access) escapes as an HTTP error —
    everything else always produces some answer, never a 500."""
    context = None
    if habitation_id is not None:
        habitation = await get_habitation_or_404(db, habitation_id)
        await ensure_read_access(db, user, habitation)
        context = await assemble_habitation_context(db, habitation_id)

    faq_answer = await match_faq(db, message, habitation_id)
    if faq_answer is not None:
        return {"content": faq_answer, "citations": [], "source": "faq"}

    if habitation_id is not None:
        default_run_id = await _most_recent_completed_run_id(db, habitation_id)
        tool_name, arguments, used_llm = extract_intent(
            message, history, str(default_run_id) if default_run_id else None
        )
        if tool_name is not None and tool_name in TOOL_REGISTRY:
            tool_fn, is_write = TOOL_REGISTRY[tool_name]
            if is_write:
                # This endpoint is read-only by design — no page-side
                # confirmation step exists here for a write, unlike the
                # button each write tool actually mirrors (e.g. "Start
                # Optimization Search"). Describe it instead of doing it.
                return {
                    "content": (
                        f"I can guide you there, but I won't start a {tool_name.replace('_', ' ')} from chat — "
                        "use the button on that tab so you can review the settings first."
                    ),
                    "citations": [],
                    "source": "faq",
                }
            try:
                result = await tool_fn(db, user, habitation_id, **arguments)
                deterministic_prose, citations = build_grounded_answer(
                    tool_name, str(default_run_id) if default_run_id else None, arguments, result
                )
                content = polish_prose(message, deterministic_prose) if used_llm else deterministic_prose
                return {"content": content, "citations": citations, "source": "tool"}
            except AppError as exc:
                return {"content": f"I couldn't do that: {exc.message}", "citations": [], "source": "tool"}

    system = build_system_prompt(context)
    llm_history = [
        {"role": h["role"], "content": h["content"]} for h in history if h["role"] in ("user", "assistant")
    ][-_HISTORY_TURNS:]
    llm_reply = await call_llm(system, llm_history, message)
    if llm_reply is not None and extract_numbers(llm_reply) <= extract_numbers(system):
        # The subset check is BR-30 applied to this fully-freeform path: the
        # model may only ever repeat a number it was actually given in the
        # system prompt, never introduce one of its own.
        return {"content": llm_reply, "citations": [], "source": "llm"}

    return {
        "content": (
            "I can help with parameter setup, simulation runs, and optimization. Try asking something like "
            "\"Why can't I run optimization?\", \"How do I fix parameters?\", or \"What is the Tornado chart?\""
        ),
        "citations": [],
        "source": "fallback",
    }
