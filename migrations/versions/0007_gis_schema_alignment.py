"""Align gis_layers/gis_features with the design's actual schema (section
4.2), found to differ in several concrete ways from what migration 0001
shipped:

  - layer_type had 6 made-up-sounding values instead of the design's 10 —
    missing ECO_SENSITIVE in particular, which BR-26 (no landfill expansion
    in an eco-sensitive zone) has nothing to check against without it.
  - layer_status had a REJECTED value; the design only has three states
    (PROCESSING / READY / FAILED) — a layer that fails BR-06/BR-07 lands on
    FAILED, same as a crash, with the *reason* in the validation report.
  - gis_layers was missing source, source_ref, is_visible_default, updated_at,
    and the UNIQUE(habitation_id, layer_name) constraint BR-14 depends on.
  - bbox was GEOMETRY, not GEOGRAPHY as designed (matters for ST_DWithin
    doing real-metre distance checks, not raw-degree ones).
  - gis_features was missing feature_ref, length_m, and a GIN index on
    properties.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

NEW_LAYER_TYPES = [
    "ROAD",
    "SETTLEMENT",
    "INDUSTRIAL_ZONE",
    "WATER_BODY",
    "TERRAIN_CONTOUR",
    "ECO_SENSITIVE",
    "ADMIN_BOUNDARY",
    "FACILITY_TREATMENT",
    "FACILITY_LANDFILL",
    "COLLECTION_ZONE",
]


def upgrade() -> None:
    # --- layer_type: recreate (values changed and were removed, not just
    # added, so a straight ADD VALUE isn't enough) --------------------
    labels = ", ".join(f"'{v}'" for v in NEW_LAYER_TYPES)
    op.execute(f"CREATE TYPE gis_layer_type_new AS ENUM ({labels})")
    op.execute(
        """
        ALTER TABLE gis_layers ALTER COLUMN layer_type TYPE gis_layer_type_new USING (
            CASE layer_type::text
                WHEN 'LANDFILL' THEN 'FACILITY_LANDFILL'
                WHEN 'TREATMENT_FACILITY' THEN 'FACILITY_TREATMENT'
                WHEN 'OTHER' THEN 'COLLECTION_ZONE'
                ELSE layer_type::text
            END
        )::gis_layer_type_new
        """
    )
    op.execute("DROP TYPE gis_layer_type")
    op.execute("ALTER TYPE gis_layer_type_new RENAME TO gis_layer_type")

    # --- layer_status: REJECTED -> FAILED, a plain rename -----------------
    op.execute("ALTER TYPE gis_layer_status RENAME VALUE 'REJECTED' TO 'FAILED'")

    # --- gis_layers: new columns ------------------------------------------
    op.execute("CREATE TYPE gis_layer_source AS ENUM ('UPLOAD', 'OSM_OVERPASS', 'MANUAL_DRAW', 'DERIVED')")
    op.add_column(
        "gis_layers",
        sa.Column(
            "source",
            PG_ENUM(name="gis_layer_source", create_type=False),
            nullable=False,
            server_default="UPLOAD",
        ),
    )
    op.add_column("gis_layers", sa.Column("source_ref", sa.String(512), nullable=True))
    op.add_column(
        "gis_layers", sa.Column("is_visible_default", sa.Boolean, nullable=False, server_default=sa.true())
    )
    op.add_column("gis_layers", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE gis_layers SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column("gis_layers", "updated_at", nullable=False, server_default=sa.func.now())

    op.create_unique_constraint("uq_gis_layer_name", "gis_layers", ["habitation_id", "layer_name"])

    op.execute("UPDATE gis_layers SET style = '{}'::jsonb WHERE style IS NULL")
    op.alter_column("gis_layers", "style", nullable=False, server_default="{}")
    op.execute("UPDATE gis_layers SET feature_count = 0 WHERE feature_count IS NULL")
    op.alter_column("gis_layers", "feature_count", nullable=False, server_default="0")
    op.alter_column("gis_layers", "z_index", type_=sa.SmallInteger)

    # GEOMETRY -> GEOGRAPHY: matters for ST_DWithin-based cheap out-of-area
    # rejection on /map, which needs real metres, not raw degrees.
    op.execute("ALTER TABLE gis_layers ALTER COLUMN bbox TYPE geography(POLYGON, 4326) USING bbox::geography")

    # --- gis_features: new columns ----------------------------------------
    op.add_column("gis_features", sa.Column("feature_ref", sa.String(80), nullable=True))
    op.add_column("gis_features", sa.Column("length_m", sa.Numeric(12, 2), nullable=True))
    op.execute("UPDATE gis_features SET properties = '{}'::jsonb WHERE properties IS NULL")
    op.alter_column("gis_features", "properties", nullable=False, server_default="{}")
    op.create_index(
        "ix_gis_features_properties", "gis_features", ["properties"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_gis_features_properties", table_name="gis_features")
    op.alter_column("gis_features", "properties", nullable=True, server_default=None)
    op.drop_column("gis_features", "length_m")
    op.drop_column("gis_features", "feature_ref")

    op.execute("ALTER TABLE gis_layers ALTER COLUMN bbox TYPE geometry(POLYGON, 4326) USING bbox::geometry")
    op.alter_column("gis_layers", "z_index", type_=sa.Integer)
    op.alter_column("gis_layers", "feature_count", nullable=True, server_default=None)
    op.alter_column("gis_layers", "style", nullable=True, server_default=None)
    op.drop_constraint("uq_gis_layer_name", "gis_layers", type_="unique")
    op.drop_column("gis_layers", "updated_at")
    op.drop_column("gis_layers", "is_visible_default")
    op.drop_column("gis_layers", "source_ref")
    op.drop_column("gis_layers", "source")
    op.execute("DROP TYPE gis_layer_source")

    op.execute("ALTER TYPE gis_layer_status RENAME VALUE 'FAILED' TO 'REJECTED'")

    op.execute("CREATE TYPE gis_layer_type_old AS ENUM ('ROAD', 'WATER_BODY', 'SETTLEMENT', 'LANDFILL', 'TREATMENT_FACILITY', 'OTHER')")
    op.execute(
        """
        ALTER TABLE gis_layers ALTER COLUMN layer_type TYPE gis_layer_type_old USING (
            CASE layer_type::text
                WHEN 'FACILITY_LANDFILL' THEN 'LANDFILL'
                WHEN 'FACILITY_TREATMENT' THEN 'TREATMENT_FACILITY'
                WHEN 'COLLECTION_ZONE' THEN 'OTHER'
                WHEN 'INDUSTRIAL_ZONE' THEN 'OTHER'
                WHEN 'TERRAIN_CONTOUR' THEN 'OTHER'
                WHEN 'ECO_SENSITIVE' THEN 'OTHER'
                WHEN 'ADMIN_BOUNDARY' THEN 'OTHER'
                ELSE layer_type::text
            END
        )::gis_layer_type_old
        """
    )
    op.execute("DROP TYPE gis_layer_type")
    op.execute("ALTER TYPE gis_layer_type_old RENAME TO gis_layer_type")
