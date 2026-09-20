"""Module M11: optimization_runs, optimization_objectives,
optimization_candidates (design section 4.3 / 5.6).

optimization_candidates is insert-only, same as the Drop 2 result tables
(BR-31) — every candidate the search evaluates, feasible or not, is kept
forever so the Pareto front and the "why the winner won" explanation can be
reconstructed later without re-running the search.

optimization_runs.best_candidate_id and optimization_candidates.optimization_id
point at each other, so best_candidate_id is added with ALTER TABLE after both
tables exist (the same circular-FK resolution pattern as
simulation_runs.parent_run_id being self-referential in migration 0008,
just across two tables instead of one).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- enums ---------------------------------------------------------
    op.execute("CREATE TYPE opt_strategy AS ENUM ('STAGED_SEARCH', 'LP_POLISH', 'GRID')")
    # Distinct from run_status (migration 0008): the design's own table for
    # optimization_runs.status lists PARTIAL in place of CANCELLED — a search
    # that ran out of budget with only some candidates evaluated is reported
    # as PARTIAL, not silently merged into COMPLETED or FAILED.
    op.execute("CREATE TYPE analysis_status AS ENUM ('QUEUED', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')")
    op.execute(
        "CREATE TYPE objective_kind AS ENUM "
        "('MIN_COST', 'MIN_LANDFILL', 'MAX_COVERAGE', 'MAX_RECOVERY', 'MIN_GHG', 'MAX_RESILIENCE')"
    )
    op.execute("CREATE TYPE opt_stage AS ENUM ('SAMPLING', 'REFINEMENT', 'LP_POLISH')")

    # --- optimization_runs ----------------------------------------------
    op.create_table(
        "optimization_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id", UUID(as_uuid=True), sa.ForeignKey("habitations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "base_run_id", UUID(as_uuid=True), sa.ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("decision_space", JSONB, nullable=False),
        sa.Column("constraints", JSONB, nullable=False),
        sa.Column(
            "strategy", PG_ENUM(name="opt_strategy", create_type=False), nullable=False, server_default="STAGED_SEARCH"
        ),
        sa.Column("candidates_evaluated", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status", PG_ENUM(name="analysis_status", create_type=False), nullable=False, server_default="QUEUED"
        ),
        # FK added below, once optimization_candidates exists.
        sa.Column("best_candidate_id", sa.BigInteger, nullable=True),
        sa.Column(
            "promoted_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("simulation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("infeasible_reason", sa.Text, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_optimization_runs_habitation", "optimization_runs", ["habitation_id"])
    op.create_index("ix_optimization_runs_base_run", "optimization_runs", ["base_run_id"])

    # --- optimization_objectives ------------------------------------------
    op.create_table(
        "optimization_objectives",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "optimization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("objective", PG_ENUM(name="objective_kind", create_type=False), nullable=False),
        sa.Column("weight", sa.Numeric(4, 3), nullable=False),
        sa.Column("normalisation_basis", sa.Numeric(18, 3), nullable=True),
        sa.CheckConstraint("weight >= 0 AND weight <= 1", name="ck_optimization_objectives_weight_range"),
        sa.UniqueConstraint("optimization_id", "objective", name="uq_optimization_objectives_one_per_kind"),
    )

    # --- optimization_candidates -------------------------------------------
    op.create_table(
        "optimization_candidates",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "optimization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", PG_ENUM(name="opt_stage", create_type=False), nullable=False),
        sa.Column("decision_values", JSONB, nullable=False),
        sa.Column("feasible", sa.Boolean, nullable=False),
        sa.Column("violated_constraints", JSONB, nullable=False, server_default="[]"),
        sa.Column("objective_values", JSONB, nullable=False, server_default="{}"),
        sa.Column("normalised_values", JSONB, nullable=False, server_default="{}"),
        sa.Column("score", sa.Numeric(10, 6), nullable=True),
        sa.Column("is_pareto", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("capex_total_inr", sa.Numeric(16, 2), nullable=True),
    )
    op.create_index(
        "ix_optimization_candidates_optimization_score", "optimization_candidates", ["optimization_id", "score"]
    )
    op.create_index(
        "ix_optimization_candidates_pareto",
        "optimization_candidates",
        ["optimization_id"],
        postgresql_where=sa.text("is_pareto = true"),
    )

    op.create_foreign_key(
        "fk_optimization_runs_best_candidate",
        "optimization_runs",
        "optimization_candidates",
        ["best_candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- insert-only enforcement (rule #2 / BR-31) ------------------------
    op.execute(
        """
        CREATE TRIGGER trg_insert_only_optimization_candidates
        BEFORE UPDATE ON optimization_candidates
        FOR EACH ROW EXECUTE FUNCTION swms_block_all_updates();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_insert_only_optimization_candidates ON optimization_candidates")

    op.drop_constraint("fk_optimization_runs_best_candidate", "optimization_runs", type_="foreignkey")
    op.drop_table("optimization_candidates")
    op.drop_table("optimization_objectives")
    op.drop_table("optimization_runs")

    op.execute("DROP TYPE opt_stage")
    op.execute("DROP TYPE objective_kind")
    op.execute("DROP TYPE analysis_status")
    op.execute("DROP TYPE opt_strategy")
