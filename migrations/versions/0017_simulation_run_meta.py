"""Adds simulation_runs.meta: a free-form JSONB bag for facts about a run
that aren't part of its reproducible inputs (habitation_id/parameter_set_id/
coefficient_set_id/param_overrides already fully determine the engine's
output) — starting with whether/how it was calibrated against
daily_waste_logs field data. Deliberately separate from param_overrides:
overrides are inputs the engine consumes, meta is provenance about how
those inputs were chosen.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "simulation_runs",
        sa.Column("meta", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("simulation_runs", "meta")
