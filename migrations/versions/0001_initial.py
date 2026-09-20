"""initial schema — Drop 1

Revision ID: 0001
Revises:
Create Date: 2026-09-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
import geoalchemy2

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "habitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("habitation_type", sa.String(16), nullable=False),
        sa.Column("state", sa.String(128), nullable=False),
        sa.Column("district", sa.String(128), nullable=False),
        sa.Column("country", sa.String(128), nullable=False, server_default="India"),
        sa.Column("centroid", geoalchemy2.Geography("POINT", srid=4326), nullable=True),
        sa.Column("boundary", geoalchemy2.Geography("MULTIPOLYGON", srid=4326), nullable=True),
        sa.Column("area_sqkm", sa.Numeric(12, 4), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("active_parameter_set_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("name", "district", "state", name="uq_habitation_location"),
    )

    op.create_table(
        "parameter_sets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("habitations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column(
            "cloned_from_id",
            UUID(as_uuid=True),
            sa.ForeignKey("parameter_sets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("change_note", sa.Text, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("habitation_id", "version_no", name="uq_parameter_set_version"),
    )

    op.create_foreign_key(
        "fk_habitations_active_parameter_set",
        "habitations",
        "parameter_sets",
        ["active_parameter_set_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
    )

    op.create_table(
        "habitation_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("habitations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("access_level", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("habitation_id", "user_id", name="uq_habitation_member"),
    )

    category_tables = {
        "demography": [
            sa.Column("population", sa.Integer, nullable=True),
            sa.Column("annual_growth_rate_pct", sa.Numeric(6, 3), nullable=True),
            sa.Column("household_size_avg", sa.Numeric(6, 2), nullable=True),
            sa.Column("floating_population_pct", sa.Numeric(6, 3), nullable=True),
        ],
        "community_infrastructure": [
            sa.Column("road_network_km", sa.Numeric(10, 3), nullable=True),
            sa.Column("collection_vehicles_count", sa.Integer, nullable=True),
            sa.Column("collection_coverage_pct", sa.Numeric(6, 3), nullable=True),
            sa.Column("treatment_capacity_tpd", sa.Numeric(10, 3), nullable=True),
            sa.Column("landfill_capacity_tonnes", sa.Numeric(14, 3), nullable=True),
            sa.Column("landfill_remaining_tonnes", sa.Numeric(14, 3), nullable=True),
        ],
        "industrial_activities": [
            sa.Column("industrial_units_count", sa.Integer, nullable=True),
            sa.Column("industrial_waste_tpd", sa.Numeric(10, 3), nullable=True),
            sa.Column("hazardous_waste_present", sa.Boolean, nullable=True),
        ],
        "natural_resources": [
            sa.Column("annual_rainfall_mm", sa.Numeric(8, 2), nullable=True),
            sa.Column("water_bodies_count", sa.Integer, nullable=True),
            sa.Column("forest_cover_pct", sa.Numeric(6, 3), nullable=True),
        ],
        "terrain": [
            sa.Column("avg_slope_pct", sa.Numeric(6, 3), nullable=True),
            sa.Column("soil_type", sa.String(64), nullable=True),
            sa.Column("flood_risk_level", sa.String(16), nullable=True),
            sa.Column("landslide_risk_level", sa.String(16), nullable=True),
        ],
        "economic_conditions": [
            sa.Column("avg_household_income_monthly", sa.Numeric(12, 2), nullable=True),
            sa.Column("swm_annual_budget", sa.Numeric(14, 2), nullable=True),
            sa.Column("unemployment_rate_pct", sa.Numeric(6, 3), nullable=True),
        ],
        "cultural_context": [
            sa.Column("segregation_practice_pct", sa.Numeric(6, 3), nullable=True),
            sa.Column("festival_days_count", sa.Integer, nullable=True),
            sa.Column("dietary_organic_pct", sa.Numeric(6, 3), nullable=True),
        ],
    }

    for table_name, extra_columns in category_tables.items():
        op.create_table(
            table_name,
            sa.Column(
                "parameter_set_id",
                UUID(as_uuid=True),
                sa.ForeignKey("parameter_sets.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            *extra_columns,
        )

    op.create_table(
        "waste_baseline",
        sa.Column(
            "parameter_set_id",
            UUID(as_uuid=True),
            sa.ForeignKey("parameter_sets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("per_capita_generation_kg_day", sa.Numeric(8, 4), nullable=True),
        sa.Column("total_generation_tpd", sa.Numeric(10, 3), nullable=True),
        sa.Column("composition", JSONB, nullable=True),
    )

    op.create_table(
        "parameter_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("param_key", sa.String(64), nullable=False),
        sa.Column("display_label", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("data_type", sa.String(16), nullable=False),
        sa.Column("min_value", sa.Numeric(14, 4), nullable=True),
        sa.Column("max_value", sa.Numeric(14, 4), nullable=True),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("normalization_rule", sa.String(64), nullable=True),
        sa.UniqueConstraint("category", "param_key", name="uq_parameter_definition"),
    )

    op.create_table(
        "validation_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "parameter_set_id",
            UUID(as_uuid=True),
            sa.ForeignKey("parameter_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("result", sa.String(8), nullable=False),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completeness_pct", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "validation_issues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            UUID(as_uuid=True),
            sa.ForeignKey("validation_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("field_path", sa.String(255), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("observed_value", sa.String(255), nullable=True),
        sa.Column("expected_range", sa.String(255), nullable=True),
        sa.Column("suggested_fix", sa.Text, nullable=True),
    )

    op.create_table(
        "gis_layers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("habitations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("layer_name", sa.String(255), nullable=False),
        sa.Column("layer_type", sa.String(32), nullable=False),
        sa.Column("geometry_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PROCESSING"),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "gis_features",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "layer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("gis_layers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("geom", geoalchemy2.Geometry("GEOMETRY", srid=4326), nullable=False),
        sa.Column("properties", JSONB, nullable=True),
    )
    op.create_index("ix_gis_features_geom", "gis_features", ["geom"], postgresql_using="gist")

    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column(
            "user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("details", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_index("ix_gis_features_geom", table_name="gis_features")
    op.drop_table("gis_features")
    op.drop_table("gis_layers")
    op.drop_table("validation_issues")
    op.drop_table("validation_reports")
    op.drop_table("parameter_definitions")
    op.drop_table("waste_baseline")
    for table_name in (
        "cultural_context",
        "economic_conditions",
        "terrain",
        "natural_resources",
        "industrial_activities",
        "community_infrastructure",
        "demography",
    ):
        op.drop_table(table_name)
    op.drop_table("habitation_members")
    op.drop_table("refresh_tokens")
    op.drop_constraint("fk_habitations_active_parameter_set", "habitations", type_="foreignkey")
    op.drop_table("parameter_sets")
    op.drop_table("habitations")
    op.drop_table("users")
