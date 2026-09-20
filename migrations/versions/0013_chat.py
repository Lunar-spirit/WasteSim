"""Module M15 (conversational interface) — design section 4.4 / 5.8.
chat_sessions -> chat_messages -> chat_tool_calls, each scoped by
ON DELETE CASCADE so deleting a session cleans up its whole history.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE chat_role AS ENUM ('USER', 'ASSISTANT', 'SYSTEM')")
    op.execute("CREATE TYPE tool_status AS ENUM ('OK', 'DENIED', 'ERROR', 'NOT_FOUND')")

    op.create_table(
        "chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_chat_sessions_user", "chat_sessions", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id", UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", PG_ENUM(name="chat_role", create_type=False), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations", JSONB, nullable=False, server_default="[]"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_chat_messages_session", "chat_messages", ["session_id"])

    op.create_table(
        "chat_tool_calls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "message_id", sa.BigInteger, sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("tool_name", sa.String(60), nullable=False),
        sa.Column("arguments", JSONB, nullable=False),
        sa.Column("result_summary", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", PG_ENUM(name="tool_status", create_type=False), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_chat_tool_calls_message", "chat_tool_calls", ["message_id"])

    # chat_messages/chat_tool_calls are the audit trail behind an answer
    # (design's own words) — insert-only, same reasoning as every other
    # append-only log in this project (BR-31's spirit, not its literal list).
    for table in ("chat_messages", "chat_tool_calls"):
        op.execute(
            f"""
            CREATE TRIGGER trg_insert_only_{table}
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION swms_block_all_updates();
            """
        )


def downgrade() -> None:
    for table in ("chat_messages", "chat_tool_calls"):
        op.execute(f"DROP TRIGGER trg_insert_only_{table} ON {table}")
    op.drop_table("chat_tool_calls")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.execute("DROP TYPE tool_status")
    op.execute("DROP TYPE chat_role")
