"""Module M13 (comparison) and M14 (reports) — design section 4.4.
run_comparisons is the input both a chart (API-77/78) and a report (API-79)
are built from, so it comes first; reports.comparison_id references it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE report_format AS ENUM ('PDF', 'XLSX', 'CSV')")
    op.execute("CREATE TYPE report_status AS ENUM ('QUEUED', 'GENERATING', 'READY', 'FAILED')")

    op.create_table(
        "run_comparisons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("run_ids", JSONB, nullable=False),
        sa.Column("indicators", JSONB, nullable=False),
        sa.Column("title", sa.String(160), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_run_comparisons_habitation", "run_comparisons", ["habitation_id"])

    op.create_table(
        "reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "comparison_id",
            UUID(as_uuid=True),
            sa.ForeignKey("run_comparisons.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("format", PG_ENUM(name="report_format", create_type=False), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=True),
        sa.Column(
            "status", PG_ENUM(name="report_status", create_type=False), nullable=False, server_default="QUEUED"
        ),
        # Not in the design's own table — BG-07's own text says a failed
        # report is "FAILED with a reason", and there is nowhere else to put
        # one. Same reasoning as simulation_runs.error_detail.
        sa.Column("error_detail", sa.String(500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "(run_id IS NOT NULL AND comparison_id IS NULL) OR (run_id IS NULL AND comparison_id IS NOT NULL)",
            name="ck_reports_exactly_one_subject",
        ),
    )
    op.create_index("ix_reports_habitation", "reports", ["habitation_id"])


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("run_comparisons")
    op.execute("DROP TYPE report_status")
    op.execute("DROP TYPE report_format")
