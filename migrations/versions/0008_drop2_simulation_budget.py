"""Drop 2 core: the pure simulation engine's persistence layer.
coefficient_sets, simulation_runs, simulation_results, simulation_yearly,
run_findings (module M8), and budget_lines (module M12). See design section
4.3 and app/engine/ for the arithmetic these tables store the output of.

simulation_results/simulation_yearly/run_findings/budget_lines are
insert-only (rule #2 / BR-31) — enforced the same way as the Drop 1
immutability trigger: a function + a BEFORE UPDATE trigger per table.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_INSERT_ONLY_TABLES = ["simulation_results", "simulation_yearly", "run_findings", "budget_lines"]


def upgrade() -> None:
    # --- enums -------------------------------------------------------
    op.execute("CREATE TYPE run_type AS ENUM ('BASE', 'SCENARIO', 'SENSITIVITY', 'OPTIMIZED')")
    op.execute("CREATE TYPE run_status AS ENUM ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')")
    op.execute("CREATE TYPE step_granularity AS ENUM ('MONTHLY')")
    op.execute("CREATE TYPE finding_severity AS ENUM ('INFO', 'WATCH', 'CRITICAL')")
    op.execute("CREATE TYPE cost_kind AS ENUM ('CAPEX', 'OPEX')")
    op.execute(
        "CREATE TYPE cost_category AS ENUM "
        "('COLLECTION', 'TRANSPORT', 'TREATMENT', 'DISPOSAL', 'FLEET_PURCHASE', "
        "'INFRASTRUCTURE', 'ADMIN', 'AWARENESS')"
    )

    # --- coefficient_sets --------------------------------------------
    op.create_table(
        "coefficient_sets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "habitation_type_scope",
            PG_ENUM(name="habitation_type", create_type=False),
            nullable=True,
        ),
        sa.Column("coefficients", JSONB, nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "uq_one_default_coefficient_set",
        "coefficient_sets",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )

    # --- simulation_runs -----------------------------------------------
    op.create_table(
        "simulation_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "parameter_set_id",
            UUID(as_uuid=True),
            sa.ForeignKey("parameter_sets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "coefficient_set_id",
            UUID(as_uuid=True),
            sa.ForeignKey("coefficient_sets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("engine_version", sa.String(20), nullable=False),
        sa.Column("run_type", PG_ENUM(name="run_type", create_type=False), nullable=False, server_default="BASE"),
        sa.Column(
            "parent_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("simulation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("horizon_years", sa.SmallInteger, nullable=False, server_default="20"),
        sa.Column(
            "step_granularity",
            PG_ENUM(name="step_granularity", create_type=False),
            nullable=False,
            server_default="MONTHLY",
        ),
        sa.Column("status", PG_ENUM(name="run_status", create_type=False), nullable=False, server_default="QUEUED"),
        sa.Column("param_overrides", JSONB, nullable=False, server_default="{}"),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("progress_pct", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_simulation_runs_habitation_type_created",
        "simulation_runs",
        ["habitation_id", "run_type", "created_at"],
    )
    op.create_index("ix_simulation_runs_parent", "simulation_runs", ["parent_run_id"])

    # --- simulation_results (240 rows/run) --------------------------------
    composition_columns = [
        sa.Column(f"{fraction}_pct", sa.Numeric(5, 2), nullable=False)
        for fraction in ("organic", "plastic", "paper", "metal", "glass", "textile", "inert", "ewaste", "other")
    ]
    op.create_table(
        "simulation_results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("month_index", sa.SmallInteger, nullable=False),
        sa.Column("year_index", sa.SmallInteger, nullable=False),
        sa.Column("calendar_month", sa.SmallInteger, nullable=False),
        sa.Column("population", sa.Integer, nullable=False),
        sa.Column("population_effective", sa.Integer, nullable=False),
        sa.Column("per_capita_kg_day", sa.Numeric(6, 3), nullable=False),
        sa.Column("waste_domestic_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("waste_bulk_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("waste_industrial_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("waste_total_tpd", sa.Numeric(12, 3), nullable=False),
        *composition_columns,
        sa.Column("collection_coverage_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("accessibility_index", sa.Numeric(5, 4), nullable=False),
        sa.Column("waste_collected_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("waste_uncollected_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("segregation_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("organic_treated_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("recyclables_recovered_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("compost_output_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("treatment_capacity_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("treatment_utilization_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("to_landfill_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("landfill_cumulative_tonnes", sa.Numeric(16, 2), nullable=False),
        sa.Column("landfill_remaining_tonnes", sa.Numeric(16, 2), nullable=False),
        sa.Column("vehicles_required", sa.SmallInteger, nullable=False),
        sa.Column("vehicle_shortfall", sa.SmallInteger, nullable=False),
        sa.Column("opex_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("capex_inr", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("ghg_tco2e", sa.Numeric(14, 3), nullable=False),
        sa.Column("active_event_codes", JSONB, nullable=False, server_default="[]"),
        sa.Column("extra", JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("run_id", "month_index", name="uq_simulation_results_run_month"),
    )
    op.create_index("ix_simulation_results_run_year", "simulation_results", ["run_id", "year_index"])

    # --- simulation_yearly (20 rows/run) -----------------------------------
    op.create_table(
        "simulation_yearly",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("year_index", sa.SmallInteger, nullable=False),
        sa.Column("population_end", sa.Integer, nullable=False),
        sa.Column("waste_total_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("waste_collected_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("waste_uncollected_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("treated_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("recovered_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("landfilled_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("landfill_remaining_tonnes", sa.Numeric(16, 2), nullable=False),
        sa.Column("avg_coverage_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("peak_vehicle_shortfall", sa.SmallInteger, nullable=False),
        sa.Column("opex_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("capex_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("total_cost_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("discounted_cost_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("ghg_tco2e", sa.Numeric(14, 3), nullable=False),
        sa.Column("recovery_rate_pct", sa.Numeric(5, 2), nullable=False),
        sa.UniqueConstraint("run_id", "year_index", name="uq_simulation_yearly_run_year"),
    )

    # --- run_findings -------------------------------------------------
    op.create_table(
        "run_findings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column(
            "severity", PG_ENUM(name="finding_severity", create_type=False), nullable=False, server_default="INFO"
        ),
        sa.Column("numeric_value", sa.Numeric(18, 3), nullable=True),
        sa.Column("year_index", sa.SmallInteger, nullable=True),
        sa.Column("message", sa.Text, nullable=False),
    )

    # --- budget_lines ----------------------------------------------------
    op.create_table(
        "budget_lines",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("year_index", sa.SmallInteger, nullable=False),
        sa.Column("kind", PG_ENUM(name="cost_kind", create_type=False), nullable=False),
        sa.Column("category", PG_ENUM(name="cost_category", create_type=False), nullable=False),
        sa.Column("amount_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("discounted_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_budget_lines_run_year_kind", "budget_lines", ["run_id", "year_index", "kind"])

    # --- insert-only enforcement (rule #2 / BR-31) ------------------------
    # A single "%" here, not "%%": unlike sqlalchemy.schema.DDL (used in
    # app/simulation/models.py's mirror of this same function), op.execute()
    # sends this string straight to Postgres with no Python-side
    # %-substitution, so Postgres's own RAISE EXCEPTION placeholder needs
    # exactly one %.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION swms_block_all_updates() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'this table is insert-only (rule #2): % rows are never updated after insert', TG_TABLE_NAME
                USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in _INSERT_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_insert_only_{table}
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION swms_block_all_updates();
            """
        )


def downgrade() -> None:
    for table in _INSERT_ONLY_TABLES:
        op.execute(f"DROP TRIGGER trg_insert_only_{table} ON {table}")
    op.execute("DROP FUNCTION swms_block_all_updates()")

    op.drop_table("budget_lines")
    op.drop_table("run_findings")
    op.drop_table("simulation_yearly")
    op.drop_table("simulation_results")
    op.drop_table("simulation_runs")
    op.drop_index("uq_one_default_coefficient_set", table_name="coefficient_sets")
    op.drop_table("coefficient_sets")

    op.execute("DROP TYPE cost_category")
    op.execute("DROP TYPE cost_kind")
    op.execute("DROP TYPE finding_severity")
    op.execute("DROP TYPE step_granularity")
    op.execute("DROP TYPE run_status")
    op.execute("DROP TYPE run_type")
