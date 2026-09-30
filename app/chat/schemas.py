import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.chat.models import ChatRole, ToolStatus


class ChatSessionCreateIn(BaseModel):
    habitation_id: uuid.UUID


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habitation_id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    created_at: datetime
    last_active_at: datetime


class ChatQueryIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    run_id: uuid.UUID | None = None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: ChatRole
    content: str
    citations: list[dict[str, Any]]
    latency_ms: int | None
    created_at: datetime


class ChatHistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatMessageIn(BaseModel):
    """The stateless POST /api/v1/chat/message request — unlike
    ChatQueryIn (bound to an existing chat_sessions row), the caller carries
    its own running `history` each call; nothing is persisted server-side."""

    habitation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatHistoryTurn] = Field(default_factory=list)


class ChatMessageReplyOut(BaseModel):
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    # Which layer produced this answer — surfaced mainly for debugging/UI
    # affordances (e.g. a "grounded" badge), not load-bearing for the client.
    source: Literal["faq", "tool", "llm", "fallback"]


class ChatToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_name: str
    arguments: dict[str, Any]
    result_summary: dict[str, Any]
    status: ToolStatus
    duration_ms: int | None
    created_at: datetime
