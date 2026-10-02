"""Daily Waste Collection & Operational Logging: daily_waste_logs.

Field-recorded reality for a habitation on a given day — what a crew
actually collected — not an input the simulation engine reads and not one
of the insert-only result tables (rule #2 only names simulation_results/
simulation_yearly/budget_lines/run_findings). A planner can correct a
day's entry after the fact, so this is a plain table with a normal UPDATE
path, keyed by the (habitation_id, log_date) unique constraint the create-
or-update endpoint upserts against.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE daily_log_anomaly_flag AS ENUM "
        "('NORMAL', 'MONSOON_FLOOD', 'FESTIVAL_SURGE', 'WORKER_STRIKE', 'BREAKDOWN')"
    )

    op.create_table(
        "daily_waste_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("logged_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("log_date", sa.Date, nullable=False),
        sa.Column("total_collected_tonnes", sa.Numeric(10, 3), nullable=False),
        sa.Column("organic_tonnes", sa.Numeric(10, 3), nullable=False),
        sa.Column("dry_recyclable_tonnes", sa.Numeric(10, 3), nullable=False),
        sa.Column("hazardous_tonnes", sa.Numeric(10, 3), nullable=True),
        sa.Column("vehicles_deployed", sa.Integer, nullable=False),
        sa.Column("trips_completed", sa.Integer, nullable=False),
        sa.Column("diesel_consumed_litres", sa.Numeric(10, 2), nullable=True),
        sa.Column("collection_coverage_pct_observed", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "anomaly_flag",
            PG_ENUM(name="daily_log_anomaly_flag", create_type=False),
            nullable=False,
            server_default="NORMAL",
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("habitation_id", "log_date", name="uq_daily_waste_log_habitation_date"),
        sa.CheckConstraint("total_collected_tonnes >= 0", name="ck_daily_log_total_collected_nonneg"),
        sa.CheckConstraint("organic_tonnes >= 0", name="ck_daily_log_organic_nonneg"),
        sa.CheckConstraint("dry_recyclable_tonnes >= 0", name="ck_daily_log_dry_recyclable_nonneg"),
        sa.CheckConstraint("hazardous_tonnes IS NULL OR hazardous_tonnes >= 0", name="ck_daily_log_hazardous_nonneg"),
        sa.CheckConstraint("vehicles_deployed >= 0", name="ck_daily_log_vehicles_nonneg"),
        sa.CheckConstraint("trips_completed >= 0", name="ck_daily_log_trips_nonneg"),
        sa.CheckConstraint(
            "diesel_consumed_litres IS NULL OR diesel_consumed_litres >= 0", name="ck_daily_log_diesel_nonneg"
        ),
        sa.CheckConstraint(
            "collection_coverage_pct_observed IS NULL OR collection_coverage_pct_observed BETWEEN 0 AND 100",
            name="ck_daily_log_coverage_pct_range",
        ),
    )
    op.create_index("ix_daily_waste_logs_log_date", "daily_waste_logs", ["log_date"])
    op.create_index("ix_daily_waste_logs_habitation", "daily_waste_logs", ["habitation_id"])


def downgrade() -> None:
    op.drop_table("daily_waste_logs")
    op.execute("DROP TYPE daily_log_anomaly_flag")
