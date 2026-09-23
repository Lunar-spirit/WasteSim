"""Module M-automation (OSM Overpass / Open-Meteo / Open-Elevation
auto-populate). Three new nullable columns on two existing category tables
— additive only, no existing column touched:

  - demography.household_count: derivable (`population / household_size_avg`)
    but also settable directly, same as every other category field.
  - terrain.terrain_type (COASTAL_PLAINS / HILLY / PLAINS) and
    terrain.coastal_buffer_zone_meters: new outputs of the elevation-grid
    terrain classification the automation engine performs; the design's
    own terrain table only ever had avg_slope_pct/soil_type/flood_risk_level/
    landslide_risk_level, so these are new, not renamed, fields.

Per rule #4 ("adding a parameter means adding a seed row, not a code
change"), each gets a parameter_definitions row too — is_required=False,
same reasoning migration 0004 gives for every other optional field: marking
one required would break the existing demo/completeness flow. The upsert
SQL below is copied verbatim in shape from migration 0004's own seeding
approach (a raw parameterised INSERT ... ON CONFLICT DO UPDATE), not the
generic Table construct, since that one is already proven against this
schema.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-21

"""
import json as _json
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

NEW_DEFINITIONS = [
    (
        "demography", "household_count", "Household count", "households", "INTEGER",
        1, 5_000_000, None, None,
        False, None, None, False,
        "Number of households. Auto-derived as population / household_size_avg when left "
        "blank and both inputs are present; can also be entered directly.",
    ),
    (
        "terrain", "terrain_type", "Terrain type", None, "STRING",
        None, None, None, None,
        False, None, ["COASTAL_PLAINS", "HILLY", "PLAINS"], False,
        "Broad terrain classification, used to scale collection efficiency (design 5.4.6) "
        "and to decide whether a coastal buffer zone applies.",
    ),
    (
        "terrain", "coastal_buffer_zone_meters", "Coastal buffer zone", "metres", "NUMERIC",
        0, 5000, None, None,
        False, None, None, False,
        "Setback distance from the coastline where siting a landfill or treatment facility "
        "is restricted. Set automatically to 500m when terrain_type is COASTAL_PLAINS.",
    ),
]


def upgrade() -> None:
    op.add_column("demography", sa.Column("household_count", sa.Integer(), nullable=True))
    op.add_column("terrain", sa.Column("terrain_type", sa.String(32), nullable=True))
    op.add_column("terrain", sa.Column("coastal_buffer_zone_meters", sa.Numeric(8, 2), nullable=True))

    bind = op.get_bind()
    upsert = sa.text(
        """
        INSERT INTO parameter_definitions (
            id, category, param_key, display_label, unit, data_type,
            min_value, max_value, warn_min, warn_max,
            is_required, normalization_rule, allowed_values, is_sweepable, help_text, rules_version
        ) VALUES (
            :id, :category, :param_key, :display_label, :unit, CAST(:data_type AS parameter_data_type),
            :min_value, :max_value, :warn_min, :warn_max,
            :is_required, :normalization_rule, CAST(:allowed_values AS jsonb), :is_sweepable, :help_text, 'v1'
        )
        ON CONFLICT (category, param_key) DO UPDATE SET
            display_label = EXCLUDED.display_label,
            unit = EXCLUDED.unit,
            data_type = EXCLUDED.data_type,
            min_value = EXCLUDED.min_value,
            max_value = EXCLUDED.max_value,
            warn_min = EXCLUDED.warn_min,
            warn_max = EXCLUDED.warn_max,
            is_required = EXCLUDED.is_required,
            normalization_rule = EXCLUDED.normalization_rule,
            allowed_values = EXCLUDED.allowed_values,
            is_sweepable = EXCLUDED.is_sweepable,
            help_text = EXCLUDED.help_text
        """
    )
    for (
        category, param_key, display_label, unit, data_type,
        min_value, max_value, warn_min, warn_max,
        is_required, normalization_rule, allowed_values, is_sweepable, help_text,
    ) in NEW_DEFINITIONS:
        bind.execute(
            upsert,
            {
                "id": uuid.uuid4(),
                "category": category,
                "param_key": param_key,
                "display_label": display_label,
                "unit": unit,
                "data_type": data_type,
                "min_value": min_value,
                "max_value": max_value,
                "warn_min": warn_min,
                "warn_max": warn_max,
                "is_required": is_required,
                "normalization_rule": normalization_rule,
                "allowed_values": _json.dumps(allowed_values) if allowed_values is not None else None,
                "is_sweepable": is_sweepable,
                "help_text": help_text,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for category, param_key, *_ in NEW_DEFINITIONS:
        bind.execute(
            sa.text("DELETE FROM parameter_definitions WHERE category = :category AND param_key = :param_key"),
            {"category": category, "param_key": param_key},
        )
    op.drop_column("terrain", "coastal_buffer_zone_meters")
    op.drop_column("terrain", "terrain_type")
    op.drop_column("demography", "household_count")
