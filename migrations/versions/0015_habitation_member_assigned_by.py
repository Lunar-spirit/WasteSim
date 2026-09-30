"""Fine-grained access control: audit column for habitation_members.

Reuses the existing habitation_members/access_level machinery for the new
admin "assign a planner to a habitation" workflow instead of adding a
second, parallel assignment table — one authorization system stays the
source of truth everywhere it's already checked (app/core/deps.py's
check_habitation_access, used by nearly every module). The only new piece
the workflow actually needs is knowing *who* granted a row, for the admin
panel and the audit trail.

assigned_by is nullable: the OWNER row create_habitation() adds for its
creator is self-granted, not assigned by anyone.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "habitation_members",
        sa.Column("assigned_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("habitation_members", "assigned_by")
