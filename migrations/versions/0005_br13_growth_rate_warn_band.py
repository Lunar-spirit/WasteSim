"""Fix demography.annual_growth_rate_pct's warn band to match BR-13 exactly:
"outside -5..+10 is an ERROR; above +4 is a WARNING." Migration 0004 seeded
a symmetric warn band [-2, 8] before this exact business-rule wording was
found in the design document — this corrects it to the design's own number
(warn_max=4, no warn_min).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE parameter_definitions SET warn_min = NULL, warn_max = 4 "
            "WHERE category = 'demography' AND param_key = 'annual_growth_rate_pct'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE parameter_definitions SET warn_min = -2, warn_max = 8 "
            "WHERE category = 'demography' AND param_key = 'annual_growth_rate_pct'"
        )
    )
