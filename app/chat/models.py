import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatRole(str, enum.Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"


class ToolStatus(str, enum.Enum):
    OK = "OK"
    DENIED = "DENIED"
    ERROR = "ERROR"
    NOT_FOUND = "NOT_FOUND"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habitation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("habitations.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole, name="chat_role"))
    content: Mapped[str] = mapped_column(Text)
    # [{"run_id": "...", "year_index": 11, "indicator": "landfill_remaining_tonnes"}]
    # — every number an answer states (BR-30).
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatToolCall(Base):
    __tablename__ = "chat_tool_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chat_messages.id", ondelete="CASCADE"))
    tool_name: Mapped[str] = mapped_column(String(60))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[ToolStatus] = mapped_column(Enum(ToolStatus, name="tool_status"))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = ["ChatSession", "ChatMessage", "ChatToolCall", "ChatRole", "ToolStatus"]
