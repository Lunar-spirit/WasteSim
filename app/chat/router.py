import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.chat import service
from app.chat.schemas import ChatMessageOut, ChatQueryIn, ChatSessionCreateIn, ChatSessionOut, ChatToolCallOut
from app.core.db import get_db
from app.core.deps import get_current_user

router = APIRouter(tags=["chat"])


@router.post("/api/v1/chat/sessions", status_code=201)
async def create_chat_session(
    payload: ChatSessionCreateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await service.create_session(db, payload.habitation_id, current_user)
    await db.commit()
    return {"success": True, "data": ChatSessionOut.model_validate(session).model_dump(mode="json")}


@router.get("/api/v1/chat/sessions")
async def list_chat_sessions(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sessions = await service.list_sessions(db, current_user)
    return {"success": True, "data": [ChatSessionOut.model_validate(s).model_dump(mode="json") for s in sessions]}


@router.post("/api/v1/chat/sessions/{sid}/query")
async def query_chat_session(
    sid: uuid.UUID,
    payload: ChatQueryIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await service.get_session_or_404(db, sid)
    service.ensure_session_owner(session, current_user)

    assistant = await service.handle_query(db, session, payload.message, payload.run_id, current_user)
    out = ChatMessageOut.model_validate(assistant)
    return {"success": True, "data": out.model_dump(mode="json")}


@router.get("/api/v1/chat/sessions/{sid}/messages")
async def get_chat_messages(
    sid: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    session = await service.get_session_or_404(db, sid)
    service.ensure_session_owner(session, current_user)
    messages = await service.get_messages(db, session)
    return {"success": True, "data": [ChatMessageOut.model_validate(m).model_dump(mode="json") for m in messages]}


@router.get("/api/v1/chat/sessions/{sid}/messages/{mid}/tool-calls")
async def get_chat_tool_calls(
    sid: uuid.UUID, mid: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    session = await service.get_session_or_404(db, sid)
    service.ensure_session_owner(session, current_user)
    tool_calls = await service.get_tool_calls(db, mid)
    return {"success": True, "data": [ChatToolCallOut.model_validate(t).model_dump(mode="json") for t in tool_calls]}
