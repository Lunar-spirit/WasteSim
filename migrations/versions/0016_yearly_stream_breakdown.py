"""Multi-decadal projection: per-material yearly breakdown + fleet
replacement CAPEX.

Adds four columns to simulation_yearly: organic_tpy, dry_recyclable_tpy,
inert_tpy (the year's total generation split three ways, matching
app/engine/step.py's new organic_tpd/dry_recyclable_tpd/inert_tpd monthly
fields) and cumulative_landfill_tonnes (the year-end running total, already
tracked monthly as landfill_cumulative_tonnes but not previously surfaced at
the yearly grain).

All four are nullable, unlike every other column on this table: simulation_
yearly is insert-only (rule #2 — a BEFORE UPDATE trigger already blocks any
UPDATE against it), so a run completed before this migration can never be
backfilled after the fact even though the raw material exists in that run's
own simulation_results rows (organic_pct/plastic_pct/.../landfill_cumulative_
tonnes are stored per month). NULL on an old run's yearly rows means "not
computed for this run," not zero; every run simulated after this migration
populates real values, since app/engine/run.py's aggregate_by_year() always
sets them now.

No engine coefficient changes need a migration: vehicle_replacement_cycle_
months (7-year fleet replacement cycle) lives in Python defaults
(app/engine/coefficients.py), read the same way every other uncalibrated
coefficient already is — coefficient_sets rows don't need a matching column
change to pick it up.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("simulation_yearly", sa.Column("organic_tpy", sa.Numeric(14, 2), nullable=True))
    op.add_column("simulation_yearly", sa.Column("dry_recyclable_tpy", sa.Numeric(14, 2), nullable=True))
    op.add_column("simulation_yearly", sa.Column("inert_tpy", sa.Numeric(14, 2), nullable=True))
    op.add_column("simulation_yearly", sa.Column("cumulative_landfill_tonnes", sa.Numeric(16, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("simulation_yearly", "cumulative_landfill_tonnes")
    op.drop_column("simulation_yearly", "inert_tpy")
    op.drop_column("simulation_yearly", "dry_recyclable_tpy")
    op.drop_column("simulation_yearly", "organic_tpy")
