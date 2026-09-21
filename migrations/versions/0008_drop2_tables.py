"""Create Drop 2 tables: simulation, scenario, budget, sensitivity, optimization.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. coefficient_sets
    op.create_table(
        "coefficient_sets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(80), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("habitation_type_scope", sa.String(32), nullable=True),
        sa.Column("coefficients", JSONB(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 2. simulation_runs
    op.create_table(
        "simulation_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id"), nullable=False, index=True),
        sa.Column("parameter_set_id", UUID(as_uuid=True), sa.ForeignKey("parameter_sets.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("coefficient_set_id", UUID(as_uuid=True), sa.ForeignKey("coefficient_sets.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("engine_version", sa.String(20), nullable=False, server_default="1.0.0"),
        sa.Column("run_type", sa.String(32), nullable=False, server_default="BASE", index=True),
        sa.Column("parent_run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id"), nullable=True, index=True),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("horizon_years", sa.SmallInteger(), nullable=False, server_default="20"),
        sa.Column("step_granularity", sa.String(20), nullable=False, server_default="MONTHLY"),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED", index=True),
        sa.Column("param_overrides", JSONB(), nullable=False, server_default="{}"),
        sa.Column("config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("progress_pct", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 3. simulation_results
    op.create_table(
        "simulation_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("month_index", sa.SmallInteger(), nullable=False),
        sa.Column("year_index", sa.SmallInteger(), nullable=False, index=True),
        sa.Column("calendar_month", sa.SmallInteger(), nullable=False),
        sa.Column("population", sa.Integer(), nullable=False),
        sa.Column("population_effective", sa.Integer(), nullable=False),
        sa.Column("per_capita_kg_day", sa.Numeric(6, 3), nullable=False),
        sa.Column("waste_domestic_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("waste_bulk_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("waste_industrial_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("waste_total_tpd", sa.Numeric(12, 3), nullable=False),
        sa.Column("composition", JSONB(), nullable=False),
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
        sa.Column("vehicles_required", sa.SmallInteger(), nullable=False),
        sa.Column("vehicles_have", sa.SmallInteger(), nullable=False),
        sa.Column("vehicle_shortfall", sa.SmallInteger(), nullable=False),
        sa.Column("opex_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("capex_inr", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("ghg_tco2e", sa.Numeric(14, 3), nullable=False),
        sa.Column("active_event_codes", JSONB(), nullable=False, server_default="[]"),
        sa.Column("extra", JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("run_id", "month_index", name="uq_simulation_results_run_month"),
    )

    # 4. simulation_yearly
    op.create_table(
        "simulation_yearly",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("year_index", sa.SmallInteger(), nullable=False),
        sa.Column("population_end", sa.Integer(), nullable=False),
        sa.Column("waste_total_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("waste_collected_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("waste_uncollected_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("treated_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("recovered_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("landfilled_tpy", sa.Numeric(14, 2), nullable=False),
        sa.Column("landfill_remaining_tonnes", sa.Numeric(16, 2), nullable=False),
        sa.Column("avg_coverage_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("peak_vehicle_shortfall", sa.SmallInteger(), nullable=False),
        sa.Column("opex_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("capex_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("total_cost_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("discounted_cost_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("ghg_tco2e", sa.Numeric(14, 3), nullable=False),
        sa.Column("recovery_rate_pct", sa.Numeric(5, 2), nullable=False),
        sa.UniqueConstraint("run_id", "year_index", name="uq_simulation_yearly_run_year"),
    )

    # 5. run_findings
    op.create_table(
        "run_findings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="INFO"),
        sa.Column("numeric_value", sa.Numeric(18, 3), nullable=True),
        sa.Column("year_index", sa.SmallInteger(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
    )

    # 6. scenario_events
    op.create_table(
        "scenario_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("simulation_run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("start_month", sa.SmallInteger(), nullable=False),
        sa.Column("duration_months", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("recovery_months", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("severity", sa.String(20), nullable=False, server_default="MODERATE"),
        sa.Column("impact_params", JSONB(), nullable=False, server_default="{}"),
        sa.Column("derived_impacts", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE scenario_events ADD COLUMN affected_area geography(MULTIPOLYGON, 4326)")

    # 7. budget_lines
    op.create_table(
        "budget_lines",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("year_index", sa.SmallInteger(), nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("amount_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("discounted_inr", sa.Numeric(16, 2), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
    )

    # 8. sensitivity_analyses
    op.create_table(
        "sensitivity_analyses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id"), nullable=False, index=True),
        sa.Column("base_run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id"), nullable=False, index=True),
        sa.Column("param_path", sa.String(160), nullable=False),
        sa.Column("swept_values", JSONB(), nullable=False),
        sa.Column("indicators", JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 9. sensitivity_points
    op.create_table(
        "sensitivity_points",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", UUID(as_uuid=True), sa.ForeignKey("sensitivity_analyses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("swept_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("child_run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id"), nullable=True),
        sa.Column("indicator_values", JSONB(), nullable=False, server_default="{}"),
        sa.Column("elasticity", sa.Numeric(10, 4), nullable=True),
    )

    # 10. optimization_runs
    op.create_table(
        "optimization_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id"), nullable=False, index=True),
        sa.Column("base_run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id"), nullable=False, index=True),
        sa.Column("decision_space", JSONB(), nullable=False, server_default="{}"),
        sa.Column("constraints", JSONB(), nullable=False, server_default="{}"),
        sa.Column("strategy", sa.String(40), nullable=False, server_default="STAGED_SEARCH"),
        sa.Column("candidates_evaluated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED", index=True),
        sa.Column("best_candidate_id", sa.BigInteger(), nullable=True),
        sa.Column("promoted_run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id"), nullable=True),
        sa.Column("infeasible_reason", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 11. optimization_objectives
    op.create_table(
        "optimization_objectives",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("optimization_id", UUID(as_uuid=True), sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("objective", sa.String(40), nullable=False),
        sa.Column("weight", sa.Numeric(4, 3), nullable=False),
        sa.Column("normalisation_basis", sa.Numeric(18, 3), nullable=True),
    )

    # 12. optimization_candidates
    op.create_table(
        "optimization_candidates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("optimization_id", UUID(as_uuid=True), sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("decision_values", JSONB(), nullable=False),
        sa.Column("feasible", sa.Boolean(), nullable=False),
        sa.Column("violated_constraints", JSONB(), nullable=False, server_default="[]"),
        sa.Column("objective_values", JSONB(), nullable=False, server_default="{}"),
        sa.Column("normalised_values", JSONB(), nullable=False, server_default="{}"),
        sa.Column("score", sa.Numeric(10, 6), nullable=True),
        sa.Column("is_pareto", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("capex_total_inr", sa.Numeric(16, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("optimization_candidates")
    op.drop_table("optimization_objectives")
    op.drop_table("optimization_runs")
    op.drop_table("sensitivity_points")
    op.drop_table("sensitivity_analyses")
    op.drop_table("budget_lines")
    op.drop_table("scenario_events")
    op.drop_table("run_findings")
    op.drop_table("simulation_yearly")
    op.drop_table("simulation_results")
    op.drop_table("simulation_runs")
    op.drop_table("coefficient_sets")
