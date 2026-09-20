"""Module M10: sensitivity_analyses, sensitivity_points (design section 4.3
/ table comments). Reuses the `analysis_status` enum migration 0010 already
created for optimization_runs — the design's own table gives
sensitivity_analyses.status the identical ENUM analysis_status type and
value set (QUEUED/RUNNING/COMPLETED/PARTIAL/FAILED), so a second enum with
the same values would just be a duplicate type.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sensitivity_analyses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "base_run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("param_path", sa.String(160), nullable=False),
        sa.Column("swept_values", JSONB, nullable=False),
        sa.Column("indicators", JSONB, nullable=False),
        sa.Column(
            "status", PG_ENUM(name="analysis_status", create_type=False), nullable=False, server_default="QUEUED"
        ),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sensitivity_analyses_habitation", "sensitivity_analyses", ["habitation_id"])

    op.create_table(
        "sensitivity_points",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "analysis_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("swept_value", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "child_run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("indicator_values", JSONB, nullable=False, server_default="{}"),
        sa.Column("elasticity", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("ix_sensitivity_points_analysis", "sensitivity_points", ["analysis_id"])

    # Insert-only, like optimization_candidates (migration 0010): a point row
    # is only ever written once the child run has finished (or failed) and
    # every column is already known — never created empty and filled in
    # later — so there is no legitimate UPDATE to allow for.
    op.execute(
        """
        CREATE TRIGGER trg_insert_only_sensitivity_points
        BEFORE UPDATE ON sensitivity_points
        FOR EACH ROW EXECUTE FUNCTION swms_block_all_updates();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_insert_only_sensitivity_points ON sensitivity_points")
    op.drop_table("sensitivity_points")
    op.drop_table("sensitivity_analyses")
