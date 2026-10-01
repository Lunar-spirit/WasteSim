"""Default VIEWER onboarding + Admin-moderated RESEARCHER upgrade workflow.

1. Renames the `user_role` enum's POLICY_VIEWER member to VIEWER (same slot,
   every existing POLICY_VIEWER row becomes VIEWER automatically — Postgres'
   ALTER TYPE ... RENAME VALUE is an in-place catalog rename, no data
   migration needed) and repoints the column default at it, since
   self-registration now lands here instead of RESEARCHER
   (app/auth/service.py's register_user).
2. role_upgrade_requests: a VIEWER's application to be promoted to
   RESEARCHER, reviewed by an ADMIN. The partial unique index is the same
   "at most one X per Y" technique migration 0003 used for parameter_sets'
   one-VALIDATED-set-per-habitation rule.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME VALUE 'POLICY_VIEWER' TO 'VIEWER'")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'VIEWER'")

    op.execute("CREATE TYPE role_upgrade_status AS ENUM ('PENDING', 'APPROVED', 'REJECTED')")

    op.create_table(
        "role_upgrade_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "target_role", PG_ENUM(name="user_role", create_type=False), nullable=False, server_default="RESEARCHER"
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("institution_or_department", sa.String(255), nullable=True),
        sa.Column(
            "status", PG_ENUM(name="role_upgrade_status", create_type=False), nullable=False, server_default="PENDING"
        ),
        sa.Column("review_notes", sa.Text, nullable=True),
        sa.Column("reviewed_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("length(reason) >= 20", name="ck_role_upgrade_requests_reason_min_length"),
    )
    op.create_index("ix_role_upgrade_requests_user", "role_upgrade_requests", ["user_id"])
    op.create_index("ix_role_upgrade_requests_status", "role_upgrade_requests", ["status"])
    op.create_index(
        "uq_one_pending_upgrade_request_per_user",
        "role_upgrade_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_table("role_upgrade_requests")
    op.execute("DROP TYPE role_upgrade_status")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'RESEARCHER'")
    op.execute("ALTER TYPE user_role RENAME VALUE 'VIEWER' TO 'POLICY_VIEWER'")
