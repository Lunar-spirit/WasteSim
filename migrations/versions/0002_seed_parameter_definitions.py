"""seed parameter_definitions catalogue

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17

"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# (category, param_key, display_label, unit, data_type, min, max, is_required, normalization_rule)
DEFINITIONS = [
    ("demography", "population", "Population", "people", "INTEGER", 1, 10_000_000, True, None),
    ("demography", "annual_growth_rate_pct", "Annual population growth rate", "%", "NUMERIC", -5, 10, True, None),
    ("demography", "household_size_avg", "Average household size", "people/household", "NUMERIC", 1, 15, True, None),
    ("demography", "floating_population_pct", "Floating population", "%", "NUMERIC", 0, 100, False, None),
    ("community_infrastructure", "road_network_km", "Road network length", "km", "NUMERIC", 0, 5000, True, None),
    ("community_infrastructure", "collection_vehicles_count", "Collection vehicles", "vehicles", "INTEGER", 0, 1000, True, None),
    ("community_infrastructure", "collection_coverage_pct", "Collection coverage", "%", "NUMERIC", 0, 100, True, "percent_from_fraction"),
    ("community_infrastructure", "treatment_capacity_tpd", "Treatment capacity", "tonnes/day", "NUMERIC", 0, 10000, True, None),
    ("community_infrastructure", "landfill_capacity_tonnes", "Landfill capacity", "tonnes", "NUMERIC", 0, 10_000_000, True, None),
    ("community_infrastructure", "landfill_remaining_tonnes", "Landfill remaining capacity", "tonnes", "NUMERIC", 0, 10_000_000, False, None),
    ("industrial_activities", "industrial_waste_tpd", "Industrial waste generated", "tonnes/day", "NUMERIC", 0, 5000, True, None),
    ("natural_resources", "annual_rainfall_mm", "Annual rainfall", "mm", "NUMERIC", 0, 6000, True, None),
    ("terrain", "avg_slope_pct", "Average terrain slope", "%", "NUMERIC", 0, 100, True, None),
    ("economic_conditions", "swm_annual_budget", "Annual SWM budget", "INR", "NUMERIC", 0, 1_000_000_000, True, None),
    ("cultural_context", "segregation_practice_pct", "Source segregation practice", "%", "NUMERIC", 0, 100, True, None),
    ("waste_baseline", "per_capita_generation_kg_day", "Per-capita waste generation", "kg/day", "NUMERIC", 0.05, 5, True, None),
    ("waste_baseline", "total_generation_tpd", "Total waste generation", "tonnes/day", "NUMERIC", 0, 100000, False, None),
    ("waste_baseline", "composition", "Waste composition", None, "JSON", None, None, True, None),
]

parameter_definitions = sa.table(
    "parameter_definitions",
    sa.column("id", UUID(as_uuid=True)),
    sa.column("category", sa.String),
    sa.column("param_key", sa.String),
    sa.column("display_label", sa.String),
    sa.column("unit", sa.String),
    sa.column("data_type", sa.String),
    sa.column("min_value", sa.Numeric),
    sa.column("max_value", sa.Numeric),
    sa.column("is_required", sa.Boolean),
    sa.column("normalization_rule", sa.String),
)


def upgrade() -> None:
    op.bulk_insert(
        parameter_definitions,
        [
            {
                "id": uuid.uuid4(),
                "category": category,
                "param_key": param_key,
                "display_label": display_label,
                "unit": unit,
                "data_type": data_type,
                "min_value": min_value,
                "max_value": max_value,
                "is_required": is_required,
                "normalization_rule": normalization_rule,
            }
            for category, param_key, display_label, unit, data_type, min_value, max_value, is_required, normalization_rule in DEFINITIONS
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM parameter_definitions")
