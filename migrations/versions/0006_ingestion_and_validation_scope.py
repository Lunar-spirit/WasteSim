"""Module M5 (ingestion): the dataset_uploads table, and the
validation_reports/validation_issues extensions needed to report against an
upload instead of only a parameter_set — scope, upload_id, gis_layer_id,
completeness_by_category, rules_version, triggered_by, started_at/
completed_at, and the PASS_WITH_WARNINGS result value. See design section
4.2 (dataset_uploads, validation_reports, validation_issues) and 5.3.

Existing validation_reports rows (all PARAMETER_SET-scoped, from before this
migration) are backfilled rather than dropped: habitation_id from their
parameter_set, triggered_by from that parameter_set's creator, scope fixed
to 'PARAMETER_SET', completed_at copied from the old created_at.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. dataset_uploads --------------------------------------------
    op.execute("CREATE TYPE file_format AS ENUM ('CSV', 'XLSX', 'JSON', 'GEOJSON', 'SHAPEFILE_ZIP', 'KML')")
    op.execute("CREATE TYPE upload_target AS ENUM ('PARAMETERS', 'GIS_LAYER')")
    op.execute(
        "CREATE TYPE upload_status AS ENUM "
        "('RECEIVED', 'PROCESSING', 'VALIDATED', 'REJECTED', 'INGESTED', 'FAILED')"
    )

    op.create_table(
        "dataset_uploads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "habitation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("habitations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "parameter_set_id",
            UUID(as_uuid=True),
            sa.ForeignKey("parameter_sets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "uploaded_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("file_format", PG_ENUM(name="file_format", create_type=False), nullable=False),
        sa.Column("target", PG_ENUM(name="upload_target", create_type=False), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column(
            "status",
            PG_ENUM(name="upload_status", create_type=False),
            nullable=False,
            server_default="RECEIVED",
        ),
        sa.Column("rows_total", sa.Integer, nullable=True),
        sa.Column("rows_accepted", sa.Integer, nullable=True),
        sa.Column("rows_rejected", sa.Integer, nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("retry_count", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("size_bytes <= 52428800", name="ck_dataset_uploads_size_cap"),
    )
    op.create_index(
        "ix_dataset_uploads_dedup", "dataset_uploads", ["habitation_id", "checksum_sha256", "created_at"]
    )

    # gis_layers.upload_id: schema readiness for the GIS ingestion worker
    # (BG-01), built in the next session alongside the rest of M4.
    op.add_column(
        "gis_layers",
        sa.Column(
            "upload_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dataset_uploads.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # --- 2. validation_reports: parameter_set_id -> multi-scope ----------
    op.add_column(
        "validation_reports",
        sa.Column(
            "habitation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("habitations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE validation_reports vr SET habitation_id = ps.habitation_id "
        "FROM parameter_sets ps WHERE ps.id = vr.parameter_set_id"
    )
    op.alter_column("validation_reports", "habitation_id", nullable=False)
    op.alter_column("validation_reports", "parameter_set_id", nullable=True)

    op.add_column(
        "validation_reports",
        sa.Column(
            "upload_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dataset_uploads.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "validation_reports",
        sa.Column(
            "gis_layer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("gis_layers.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    op.execute(
        "CREATE TYPE validation_scope AS ENUM ('PARAMETER_SET', 'UPLOAD', 'GIS_LAYER', 'FULL_HABITATION')"
    )
    op.add_column(
        "validation_reports",
        sa.Column("scope", PG_ENUM(name="validation_scope", create_type=False), nullable=True),
    )
    op.execute("UPDATE validation_reports SET scope = 'PARAMETER_SET'")
    op.alter_column("validation_reports", "scope", nullable=False)

    # PASS_WITH_WARNINGS added to the existing enum type, not a new one — a
    # zero-error report with at least one WARNING; still commit-eligible
    # (BR-01 only cares about error_count), but visibly different from a
    # totally clean PASS. Safe inside this transaction on Postgres 12+ as
    # long as the new value isn't compared against until a later statement.
    op.execute("ALTER TYPE validation_result ADD VALUE IF NOT EXISTS 'PASS_WITH_WARNINGS'")

    op.add_column(
        "validation_reports",
        sa.Column("completeness_by_category", JSONB, nullable=False, server_default="{}"),
    )
    op.add_column(
        "validation_reports",
        sa.Column("rules_version", sa.String(20), nullable=False, server_default="v1"),
    )

    op.add_column(
        "validation_reports",
        sa.Column(
            "triggered_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE validation_reports vr SET triggered_by = ps.created_by "
        "FROM parameter_sets ps WHERE ps.id = vr.parameter_set_id AND vr.triggered_by IS NULL"
    )
    op.alter_column("validation_reports", "triggered_by", nullable=False)

    op.alter_column("validation_reports", "created_at", new_column_name="started_at")
    op.add_column(
        "validation_reports", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE validation_reports SET completed_at = started_at WHERE completed_at IS NULL")

    # --- 3. validation_issues --------------------------------------------
    op.add_column("validation_issues", sa.Column("category", sa.String(40), nullable=True))
    op.execute("ALTER TYPE issue_severity ADD VALUE IF NOT EXISTS 'INFO'")


def downgrade() -> None:
    op.drop_column("validation_issues", "category")
    # Postgres has no DROP VALUE for enums; 'INFO'/'PASS_WITH_WARNINGS'
    # simply become unused values on downgrade rather than removed types.

    op.drop_column("validation_reports", "completed_at")
    op.alter_column("validation_reports", "started_at", new_column_name="created_at")
    op.alter_column("validation_reports", "triggered_by", nullable=True)
    op.drop_column("validation_reports", "triggered_by")
    op.drop_column("validation_reports", "rules_version")
    op.drop_column("validation_reports", "completeness_by_category")
    op.drop_column("validation_reports", "scope")
    op.execute("DROP TYPE validation_scope")
    op.drop_column("validation_reports", "gis_layer_id")
    op.drop_column("validation_reports", "upload_id")
    op.alter_column("validation_reports", "parameter_set_id", nullable=False)
    op.drop_column("validation_reports", "habitation_id")

    op.drop_column("gis_layers", "upload_id")

    op.drop_index("ix_dataset_uploads_dedup", table_name="dataset_uploads")
    op.drop_table("dataset_uploads")
    op.execute("DROP TYPE upload_status")
    op.execute("DROP TYPE upload_target")
    op.execute("DROP TYPE file_format")
