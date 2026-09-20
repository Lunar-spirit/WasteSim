"""Module M9 (scenario): scenario_events. A scenario run is just a
simulation_run with run_type=SCENARIO and its own rows here — no new run
lifecycle, no new worker task (BG-04/tasks_simulate.py already handles it,
now reading this table when present). See design section 5.5.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE event_type AS ENUM ("
        "'FLOOD', 'LANDSLIDE', 'HEAVY_MONSOON', 'ROAD_BLOCKAGE', 'POPULATION_SURGE', "
        "'VEHICLE_BREAKDOWN', 'TREATMENT_PLANT_OUTAGE', 'FESTIVAL', 'STRIKE'"
        ")"
    )
    op.execute("CREATE TYPE event_severity AS ENUM ('LOW', 'MODERATE', 'SEVERE')")

    op.create_table(
        "scenario_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "simulation_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", PG_ENUM(name="event_type", create_type=False), nullable=False),
        sa.Column("start_month", sa.SmallInteger, nullable=False),
        sa.Column("duration_months", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("recovery_months", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column(
            "severity", PG_ENUM(name="event_severity", create_type=False), nullable=False, server_default="MODERATE"
        ),
        sa.Column("impact_params", JSONB, nullable=False, server_default="{}"),
        sa.Column("derived_impacts", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("start_month BETWEEN 1 AND 240", name="ck_scenario_events_start_month"),
        sa.CheckConstraint("duration_months >= 1", name="ck_scenario_events_duration"),
    )
    # GEOGRAPHY(MultiPolygon, 4326) via raw SQL, added after the table
    # exists — typmod-style geography columns (matching gis_layers.bbox
    # elsewhere) don't have a first-class sa.Column(...) constructor.
    op.execute("ALTER TABLE scenario_events ADD COLUMN affected_area geography(MultiPolygon, 4326)")

    op.create_index("ix_scenario_events_run", "scenario_events", ["simulation_run_id"])


def downgrade() -> None:
    op.drop_table("scenario_events")
    op.execute("DROP TYPE event_severity")
    op.execute("DROP TYPE event_type")
