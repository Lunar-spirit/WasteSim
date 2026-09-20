"""Drop 1 hardening: native enum types, CHECK constraints, the parameter-set
immutability trigger, the one-VALIDATED-set-per-habitation partial unique
index, and catalogue/GIS columns the models already declare.

This migration exists because migrations 0001-0002 built the Drop 1 tables
correctly in shape but left several CLAUDE.md non-negotiable rules enforced
only in Python (the service layer), not in the database itself:

  - rule #1: "Parameter values are never updated in place. VALIDATED and
    ARCHIVED sets are read-only." -> enforced only by service.py's
    _assert_editable(), not by the database -> added a BEFORE UPDATE trigger.
  - rule #4: "Validation thresholds live in parameter_definitions" -> the
    catalogue was missing warn_min/warn_max/allowed_values/is_sweepable/
    severity_on_fail/help_text, so Stage 2 of the pipeline could only ever
    produce hard ERROR-or-nothing range checks.
  - the design's explicit CHECK constraints (population > 0, landfill_
    remaining <= landfill_capacity, composition sums to 100, etc.) did not
    exist at all.
  - enum-like columns (role, status, ...) were plain VARCHAR with no
    constraint whatsoever restricting their values.

See app/parameters/models.py for the SQLAlchemy-side mirror of the trigger
and CHECK constraints (Base.metadata.create_all(), used by the test suite,
needs them expressed there too — this migration is the same DDL for a real
`alembic upgrade head` deployment).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


# (enum type name, column's current table.column, member values, default to
# restore afterwards or None). ALTER COLUMN ... TYPE requires an explicit
# USING clause to cast the existing VARCHAR data into the new enum type, and
# changing a column's type drops any DEFAULT that depends on the old type —
# so each default is re-applied once the column is the new type.
ENUM_COLUMNS = [
    ("user_role", "users", "role", ["ADMIN", "PLANNER", "RESEARCHER", "POLICY_VIEWER"], "RESEARCHER"),
    ("habitation_type", "habitations", "habitation_type", ["VILLAGE", "WARD", "TOWN", "CITY"], None),
    ("habitation_status", "habitations", "status", ["DRAFT", "READY", "ARCHIVED"], "DRAFT"),
    ("access_level", "habitation_members", "access_level", ["OWNER", "EDITOR", "VIEWER"], None),
    (
        "parameter_set_status",
        "parameter_sets",
        "status",
        ["DRAFT", "VALIDATING", "VALIDATED", "INVALID", "ARCHIVED"],
        "DRAFT",
    ),
    (
        "parameter_data_type",
        "parameter_definitions",
        "data_type",
        ["INTEGER", "NUMERIC", "STRING", "BOOLEAN", "JSON"],
        None,
    ),
    ("validation_result", "validation_reports", "result", ["PASS", "FAIL"], None),
    ("issue_severity", "validation_issues", "severity", ["ERROR", "WARNING"], None),
    (
        "gis_layer_type",
        "gis_layers",
        "layer_type",
        ["ROAD", "WATER_BODY", "SETTLEMENT", "LANDFILL", "TREATMENT_FACILITY", "OTHER"],
        None,
    ),
    ("gis_layer_status", "gis_layers", "status", ["PROCESSING", "READY", "REJECTED"], "PROCESSING"),
]

# The 8 tables that hang 1:1 off parameter_sets and must become read-only
# the moment their parent set is VALIDATED or ARCHIVED.
CATEGORY_TABLES = [
    "demography",
    "community_infrastructure",
    "industrial_activities",
    "natural_resources",
    "terrain",
    "economic_conditions",
    "cultural_context",
    "waste_baseline",
]


def upgrade() -> None:
    # --- 1. Native enum types -------------------------------------------
    # Every "%s" below is a Postgres enum literal list, not a Python enum —
    # this loop just saves retyping the same CREATE TYPE / ALTER COLUMN /
    # SET DEFAULT boilerplate ten times.
    for type_name, table, column, values, default in ENUM_COLUMNS:
        labels = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {type_name} AS ENUM ({labels})")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {type_name} "
            f"USING {column}::text::{type_name}"
        )
        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}'")

    # --- 2. The two SQL functions the trigger and a CHECK constraint need -
    op.execute(
        """
        CREATE OR REPLACE FUNCTION swms_block_locked_parameter_set_edit() RETURNS trigger AS $$
        DECLARE
            ps_status varchar;
        BEGIN
            SELECT status::text INTO ps_status FROM parameter_sets WHERE id = NEW.parameter_set_id;
            IF ps_status IN ('VALIDATED', 'ARCHIVED') THEN
                RAISE EXCEPTION
                    'parameter_set % is % and is read-only (VALIDATED/ARCHIVED sets are immutable)',
                    NEW.parameter_set_id, ps_status
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION swms_composition_sums_to_100(comp jsonb) RETURNS boolean AS $$
            SELECT comp IS NULL OR (
                SELECT abs(sum((value)::numeric) - 100) <= 0.5
                FROM jsonb_each_text(comp)
            );
        $$ LANGUAGE sql IMMUTABLE;
        """
    )

    # --- 3. The immutability trigger, on all 8 category tables -----------
    for table in CATEGORY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_block_locked_edit_{table}
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION swms_block_locked_parameter_set_edit();
            """
        )

    # --- 4. CHECK constraints --------------------------------------------
    # Deliberately much wider than the -5..10 business range a planner sees
    # via parameter_definitions + Stage 2 of the validation pipeline: this
    # is a physical sanity backstop (rejects a typo like 1400), not the real
    # business rule, so a planner can still PUT an out-of-range value like
    # 14 and get a graceful FAIL from /validate instead of a 500 on the PUT
    # itself. See app/parameters/models.py's Demography.__table_args__.
    op.execute(
        "ALTER TABLE demography ADD CONSTRAINT ck_demography_population_positive "
        "CHECK (population IS NULL OR population > 0)"
    )
    op.execute(
        "ALTER TABLE demography ADD CONSTRAINT ck_demography_growth_rate_sane "
        "CHECK (annual_growth_rate_pct IS NULL OR annual_growth_rate_pct BETWEEN -100 AND 1000)"
    )
    op.execute(
        "ALTER TABLE community_infrastructure ADD CONSTRAINT ck_community_infra_landfill_remaining_le_capacity "
        "CHECK (landfill_remaining_tonnes IS NULL OR landfill_capacity_tonnes IS NULL "
        "OR landfill_remaining_tonnes <= landfill_capacity_tonnes)"
    )
    op.execute(
        "ALTER TABLE waste_baseline ADD CONSTRAINT ck_waste_baseline_generation_present "
        "CHECK (per_capita_generation_kg_day IS NOT NULL OR total_generation_tpd IS NOT NULL)"
    )
    op.execute(
        "ALTER TABLE waste_baseline ADD CONSTRAINT ck_waste_baseline_composition_sum "
        "CHECK (swms_composition_sums_to_100(composition))"
    )

    # --- 5. Partial unique index: at most one VALIDATED set per habitation
    op.execute(
        "CREATE UNIQUE INDEX uq_one_validated_parameter_set_per_habitation "
        "ON parameter_sets (habitation_id) WHERE status = 'VALIDATED'"
    )

    # --- 6. parameter_definitions catalogue columns -----------------------
    op.add_column("parameter_definitions", sa.Column("warn_min", sa.Numeric(14, 4), nullable=True))
    op.add_column("parameter_definitions", sa.Column("warn_max", sa.Numeric(14, 4), nullable=True))
    op.add_column(
        "parameter_definitions",
        sa.Column("allowed_values", JSONB, nullable=True),
    )
    op.add_column(
        "parameter_definitions",
        sa.Column("is_sweepable", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "parameter_definitions",
        sa.Column("severity_on_fail", sa.String(8), nullable=False, server_default="ERROR"),
    )
    op.execute(
        "ALTER TABLE parameter_definitions ADD CONSTRAINT ck_parameter_definitions_severity "
        "CHECK (severity_on_fail IN ('ERROR', 'WARNING'))"
    )
    op.add_column("parameter_definitions", sa.Column("help_text", sa.Text, nullable=True))
    op.add_column(
        "parameter_definitions",
        sa.Column("rules_version", sa.String(8), nullable=False, server_default="v1"),
    )

    # --- 7. validation_issues.row_number (for M5 tabular ingestion) ------
    op.add_column("validation_issues", sa.Column("row_number", sa.Integer, nullable=True))

    # --- 8. gis_layers columns (schema readiness for the full M4 build) --
    op.add_column("gis_layers", sa.Column("srid_original", sa.Integer, nullable=True))
    op.add_column(
        "gis_layers", sa.Column("z_index", sa.Integer, nullable=False, server_default="0")
    )
    op.add_column("gis_layers", sa.Column("style", JSONB, nullable=True))
    op.add_column("gis_layers", sa.Column("feature_count", sa.Integer, nullable=True))
    op.add_column("gis_layers", sa.Column("total_length_km", sa.Numeric(12, 3), nullable=True))
    # Typmod-style geometry column (matches how gis_features.geom was added
    # in 0001 via geoalchemy2's Geometry type) rather than the legacy
    # AddGeometryColumn() function — the two produce subtly different
    # catalogue metadata, and only the typmod style matches what
    # Base.metadata.create_all() generates for the same column in
    # app/gis/models.py, which the test suite relies on.
    op.execute("ALTER TABLE gis_layers ADD COLUMN bbox geometry(POLYGON, 4326)")


def downgrade() -> None:
    op.execute("ALTER TABLE gis_layers DROP COLUMN bbox")
    op.drop_column("gis_layers", "total_length_km")
    op.drop_column("gis_layers", "feature_count")
    op.drop_column("gis_layers", "style")
    op.drop_column("gis_layers", "z_index")
    op.drop_column("gis_layers", "srid_original")

    op.drop_column("validation_issues", "row_number")

    op.drop_column("parameter_definitions", "rules_version")
    op.drop_column("parameter_definitions", "help_text")
    op.execute("ALTER TABLE parameter_definitions DROP CONSTRAINT ck_parameter_definitions_severity")
    op.drop_column("parameter_definitions", "severity_on_fail")
    op.drop_column("parameter_definitions", "is_sweepable")
    op.drop_column("parameter_definitions", "allowed_values")
    op.drop_column("parameter_definitions", "warn_max")
    op.drop_column("parameter_definitions", "warn_min")

    op.execute("DROP INDEX uq_one_validated_parameter_set_per_habitation")

    op.execute("ALTER TABLE waste_baseline DROP CONSTRAINT ck_waste_baseline_composition_sum")
    op.execute("ALTER TABLE waste_baseline DROP CONSTRAINT ck_waste_baseline_generation_present")
    op.execute(
        "ALTER TABLE community_infrastructure DROP CONSTRAINT ck_community_infra_landfill_remaining_le_capacity"
    )
    op.execute("ALTER TABLE demography DROP CONSTRAINT ck_demography_growth_rate_sane")
    op.execute("ALTER TABLE demography DROP CONSTRAINT ck_demography_population_positive")

    for table in CATEGORY_TABLES:
        op.execute(f"DROP TRIGGER trg_block_locked_edit_{table} ON {table}")

    op.execute("DROP FUNCTION swms_composition_sums_to_100(jsonb)")
    op.execute("DROP FUNCTION swms_block_locked_parameter_set_edit()")

    for type_name, table, column, _values, default in ENUM_COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE varchar USING {column}::text")
        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}'")
        op.execute(f"DROP TYPE {type_name}")
