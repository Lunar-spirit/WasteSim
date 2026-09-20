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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.chat.grounding import build_grounded_answer, polish_prose
from app.chat.models import ChatMessage, ChatRole, ChatSession, ChatToolCall, ToolStatus
from app.chat.router_llm import extract_intent
from app.chat.tools import TOOL_REGISTRY
from app.core.errors import AppError
from app.habitation.service import ensure_read_access, get_habitation_or_404
from app.simulation.models import RunStatus, SimulationRun

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
