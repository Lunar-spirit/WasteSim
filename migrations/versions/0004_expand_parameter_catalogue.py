"""Expand the parameter_definitions catalogue to cover every column of the
seven categories plus the waste baseline, and populate the new warn_min/
warn_max/allowed_values/is_sweepable/help_text columns added in 0003.

Uses INSERT ... ON CONFLICT (category, param_key) DO UPDATE so this migration
is idempotent and works uniformly for both:
  - the 18 rows 0002 already seeded (their metadata gets filled in), and
  - the columns 0002 never had a row for at all (a plain insert).

Design choice worth calling out: the columns scripts/seed_demo.py does NOT
supply a value for (industrial_units_count, hazardous_waste_present,
water_bodies_count, forest_cover_pct, soil_type, flood_risk_level,
landslide_risk_level, avg_household_income_monthly, unemployment_rate_pct,
festival_days_count, dietary_organic_pct) are seeded with is_required=False.
Marking any of them required would silently break the demo script's
`assert report["result"] == "PASS"` / completeness == 100 checks, which is
exactly the kind of already-working flow this migration must not disturb.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18

"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# One row per column of the 8 tables (demography ... waste_baseline).
# Fields: category, param_key, display_label, unit, data_type,
#         min_value, max_value, warn_min, warn_max,
#         is_required, normalization_rule, allowed_values, is_sweepable,
#         help_text
DEFINITIONS = [
    # --- demography ------------------------------------------------------
    (
        "demography", "population", "Population", "people", "INTEGER",
        1, 10_000_000, None, None,
        True, None, None, False,
        "Total residents from the latest census or municipal estimate.",
    ),
    (
        "demography", "annual_growth_rate_pct", "Annual population growth rate", "%", "NUMERIC",
        -5, 10, -2, 8,
        True, None, None, True,
        "Compound annual growth rate. Most Indian villages/towns fall between -2% and 8%; "
        "values outside -5..10 are rejected outright as almost certainly a data-entry error "
        "(e.g. typing 14 for 1.4).",
    ),
    (
        "demography", "household_size_avg", "Average household size", "people/household", "NUMERIC",
        1, 15, 2, 8,
        True, None, None, False,
        "Average number of people per household. Used to cross-check population against "
        "housing-unit counts where available.",
    ),
    (
        "demography", "floating_population_pct", "Floating population", "%", "NUMERIC",
        0, 100, 0, 30,
        True, None, None, False,
        "Share of the daytime population that commutes in but does not live in the "
        "habitation (workers, students, market visitors) — they still generate waste.",
    ),
    # --- community_infrastructure -----------------------------------------
    (
        "community_infrastructure", "road_network_km", "Road network length", "km", "NUMERIC",
        0, 5000, None, None,
        True, None, None, False,
        "Total length of motorable road the collection fleet can use, from the GIS road "
        "layer or a municipal record.",
    ),
    (
        "community_infrastructure", "collection_vehicles_count", "Collection vehicles", "vehicles", "INTEGER",
        0, 1000, None, None,
        True, None, None, True,
        "Number of vehicles (any type) currently used for waste collection.",
    ),
    (
        "community_infrastructure", "collection_coverage_pct", "Collection coverage", "%", "NUMERIC",
        0, 100, 60, None,
        True, "percent_from_fraction", None, True,
        "Share of the habitation's waste that is actually collected, door-to-door or via "
        "community bins. Below 60% is unusually low and worth double-checking.",
    ),
    (
        "community_infrastructure", "treatment_capacity_tpd", "Treatment capacity", "tonnes/day", "NUMERIC",
        0, 10000, None, None,
        True, None, None, True,
        "Combined daily processing capacity of composting, biomethanation and any other "
        "treatment facilities serving this habitation.",
    ),
    (
        "community_infrastructure", "landfill_capacity_tonnes", "Landfill capacity", "tonnes", "NUMERIC",
        0, 10_000_000, None, None,
        True, None, None, False,
        "Total design capacity of the landfill/dumpsite this habitation sends waste to.",
    ),
    (
        "community_infrastructure", "landfill_remaining_tonnes", "Landfill remaining capacity", "tonnes", "NUMERIC",
        0, 10_000_000, None, None,
        False, None, None, False,
        "Remaining airspace at the landfill today. Left blank, the engine assumes the "
        "landfill starts full (remaining = capacity).",
    ),
    # --- industrial_activities ---------------------------------------------
    (
        "industrial_activities", "industrial_units_count", "Industrial units", "units", "INTEGER",
        0, 100000, None, None,
        False, None, None, False,
        "Number of registered industrial units (factories, workshops) in the habitation.",
    ),
    (
        "industrial_activities", "industrial_waste_tpd", "Industrial waste generated", "tonnes/day", "NUMERIC",
        0, 5000, None, None,
        True, None, None, False,
        "Solid waste generated by industry, separate from household waste — enters the "
        "engine as its own generation stream (design section 5.4, part 3).",
    ),
    (
        "industrial_activities", "hazardous_waste_present", "Hazardous waste present", None, "BOOLEAN",
        None, None, None, None,
        False, None, None, False,
        "Whether any industry here produces hazardous waste requiring separate handling "
        "(not modelled by the engine yet, but tracked for future rules).",
    ),
    # --- natural_resources ---------------------------------------------
    (
        "natural_resources", "annual_rainfall_mm", "Annual rainfall", "mm", "NUMERIC",
        0, 6000, 800, 4000,
        True, None, None, True,
        "Total annual rainfall — drives the monsoon seasonality factor on wet-waste mass "
        "(design section 5.4, part 3).",
    ),
    (
        "natural_resources", "water_bodies_count", "Water bodies", "count", "INTEGER",
        0, 10000, None, None,
        False, None, None, False,
        "Number of lakes, ponds, rivers or tanks — used to flag waste dumping risk near "
        "water bodies during spatial validation (Stage 4).",
    ),
    (
        "natural_resources", "forest_cover_pct", "Forest cover", "%", "NUMERIC",
        0, 100, None, None,
        False, None, None, False,
        "Share of the habitation's area under forest cover.",
    ),
    # --- terrain ------------------------------------------------------
    (
        "terrain", "avg_slope_pct", "Average terrain slope", "%", "NUMERIC",
        0, 100, None, 40,
        True, None, None, False,
        "Average ground slope — steeper terrain lowers collection efficiency (design "
        "section 5.4, part 5). Above 40% is unusually steep for a collection route.",
    ),
    (
        "terrain", "soil_type", "Soil type", None, "STRING",
        None, None, None, None,
        False, None, ["SANDY", "CLAY", "LOAMY", "ROCKY", "SILTY"], False,
        "Dominant soil type — affects landfill leachate risk and composting suitability.",
    ),
    (
        "terrain", "flood_risk_level", "Flood risk level", None, "STRING",
        None, None, None, None,
        False, None, ["LOW", "MODERATE", "HIGH"], False,
        "How exposed this habitation is to flooding — scales the severity of a FLOOD "
        "scenario event for this specific habitation (design section 5.5).",
    ),
    (
        "terrain", "landslide_risk_level", "Landslide risk level", None, "STRING",
        None, None, None, None,
        False, None, ["LOW", "MODERATE", "HIGH"], False,
        "How exposed this habitation is to landslides — scales the severity of a "
        "LANDSLIDE scenario event for this specific habitation (design section 5.5).",
    ),
    # --- economic_conditions ---------------------------------------------
    (
        "economic_conditions", "avg_household_income_monthly", "Average household income", "INR/month", "NUMERIC",
        0, 10_000_000, None, None,
        False, None, None, False,
        "Average monthly household income — a rough proxy for willingness/ability to pay "
        "for improved waste services.",
    ),
    (
        "economic_conditions", "swm_annual_budget", "Annual SWM budget", "INR", "NUMERIC",
        0, 1_000_000_000, None, None,
        True, None, None, False,
        "Annual budget allocated to solid waste management — the ceiling the budget "
        "module (M12) checks opex/capex against for a breach.",
    ),
    (
        "economic_conditions", "unemployment_rate_pct", "Unemployment rate", "%", "NUMERIC",
        0, 100, None, None,
        False, None, None, False,
        "Local unemployment rate — informal-sector waste picking tends to rise with it.",
    ),
    # --- cultural_context -----------------------------------------------
    (
        "cultural_context", "segregation_practice_pct", "Source segregation practice", "%", "NUMERIC",
        0, 100, 20, None,
        True, "percent_from_fraction", None, True,
        "Share of households already segregating waste at source. Below 20% is unusually "
        "low even for a habitation with no formal segregation programme.",
    ),
    (
        "cultural_context", "festival_days_count", "Festival days per year", "days", "INTEGER",
        0, 365, None, None,
        False, None, None, False,
        "Number of major festival days per year — drives the festival waste-generation "
        "surge (design section 5.4, parts 1 and 3).",
    ),
    (
        "cultural_context", "dietary_organic_pct", "Dietary organic share", "%", "NUMERIC",
        0, 100, None, None,
        False, None, None, False,
        "Share of the local diet that is fresh/organic (vs. packaged) — shifts the organic "
        "fraction of waste composition (design section 5.4, part 4).",
    ),
    # --- waste_baseline ---------------------------------------------
    (
        "waste_baseline", "per_capita_generation_kg_day", "Per-capita waste generation", "kg/day", "NUMERIC",
        0.05, 5, 0.2, 1.0,
        True, None, None, True,
        "Starting per-capita generation rate — the engine's q0 (design section 5.4, part "
        "2). Either this or total_generation_tpd is required, not necessarily both.",
    ),
    (
        "waste_baseline", "total_generation_tpd", "Total waste generation", "tonnes/day", "NUMERIC",
        0, 100000, None, None,
        False, None, None, False,
        "Starting total generation rate, as an alternative to per_capita_generation_kg_day "
        "when a habitation-wide figure is known but per-capita is not.",
    ),
    (
        "waste_baseline", "composition", "Waste composition", None, "JSON",
        None, None, None, None,
        True, None, None, False,
        "Waste composition as {\"organic\": .., \"plastic\": .., ...} — fractions must sum "
        "to 100 (+/- 0.5).",
    ),
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
    sa.column("warn_min", sa.Numeric),
    sa.column("warn_max", sa.Numeric),
    sa.column("is_required", sa.Boolean),
    sa.column("normalization_rule", sa.String),
    sa.column("allowed_values", JSONB),
    sa.column("is_sweepable", sa.Boolean),
    sa.column("help_text", sa.Text),
)


def upgrade() -> None:
    bind = op.get_bind()
    upsert = sa.text(
        """
        INSERT INTO parameter_definitions (
            id, category, param_key, display_label, unit, data_type,
            min_value, max_value, warn_min, warn_max,
            is_required, normalization_rule, allowed_values, is_sweepable, help_text
        ) VALUES (
            :id, :category, :param_key, :display_label, :unit, CAST(:data_type AS parameter_data_type),
            :min_value, :max_value, :warn_min, :warn_max,
            :is_required, :normalization_rule, CAST(:allowed_values AS jsonb), :is_sweepable, :help_text
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
    import json as _json

    for (
        category, param_key, display_label, unit, data_type,
        min_value, max_value, warn_min, warn_max,
        is_required, normalization_rule, allowed_values, is_sweepable, help_text,
    ) in DEFINITIONS:
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
    # Only remove the 13 rows this migration introduced that 0002 never had;
    # the original 18 rows' metadata columns are simply left populated
    # (harmless — 0003's downgrade already drops those columns entirely).
    original_keys = {
        ("demography", "population"),
        ("demography", "annual_growth_rate_pct"),
        ("demography", "household_size_avg"),
        ("demography", "floating_population_pct"),
        ("community_infrastructure", "road_network_km"),
        ("community_infrastructure", "collection_vehicles_count"),
        ("community_infrastructure", "collection_coverage_pct"),
        ("community_infrastructure", "treatment_capacity_tpd"),
        ("community_infrastructure", "landfill_capacity_tonnes"),
        ("community_infrastructure", "landfill_remaining_tonnes"),
        ("industrial_activities", "industrial_waste_tpd"),
        ("natural_resources", "annual_rainfall_mm"),
        ("terrain", "avg_slope_pct"),
        ("economic_conditions", "swm_annual_budget"),
        ("cultural_context", "segregation_practice_pct"),
        ("waste_baseline", "per_capita_generation_kg_day"),
        ("waste_baseline", "total_generation_tpd"),
        ("waste_baseline", "composition"),
    }
    bind = op.get_bind()
    for category, param_key, *_rest in DEFINITIONS:
        if (category, param_key) not in original_keys:
            bind.execute(
                sa.text(
                    "DELETE FROM parameter_definitions WHERE category = :c AND param_key = :k"
                ),
                {"c": category, "k": param_key},
            )
