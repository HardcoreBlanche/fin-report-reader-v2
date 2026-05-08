"""soft delete annual reports

Revision ID: 0004_soft_delete_annual_reports
Revises: 0003_text_only_mda_analysis_result
Create Date: 2026-05-08
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_soft_delete_annual_reports"
down_revision: str | None = "0003_text_only_mda_analysis_result"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "annual_reports",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("annual_reports", "is_deleted")
