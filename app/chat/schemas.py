import uuid
from datetime import datetime
from typing import Any

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


class ChatToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_name: str
    arguments: dict[str, Any]
    result_summary: dict[str, Any]
    status: ToolStatus
    duration_ms: int | None
    created_at: datetime
