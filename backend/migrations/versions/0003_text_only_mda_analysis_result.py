"""text only mda analysis result

Revision ID: 0003_text_only_mda_analysis_result
Revises: 0002_analysis_state_for_file_versions
Create Date: 2026-05-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_text_only_mda_analysis_result"
down_revision: str | None = "0002_analysis_state_for_file_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("implementation_id", sa.String(length=64), nullable=False, server_default="pending"),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("stage_history", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("analysis_runs", sa.Column("error_code", sa.String(length=64), nullable=True))
    op.execute(
        "update analysis_runs set implementation_id = 'analysis_run_' || id where implementation_id = 'pending'"
    )
    op.create_index(
        "ix_analysis_runs_implementation_id",
        "analysis_runs",
        ["implementation_id"],
        unique=True,
    )
    op.add_column(
        "analysis_results",
        sa.Column("prompt_version", sa.String(length=64), nullable=False, server_default="mda_outline_v1"),
    )
    op.add_column(
        "analysis_results",
        sa.Column("evidence_package", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "analysis_results",
        sa.Column("structured_outline", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "analysis_results",
        sa.Column("qa_unavailable_reason", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_results", "qa_unavailable_reason")
    op.drop_column("analysis_results", "structured_outline")
    op.drop_column("analysis_results", "evidence_package")
    op.drop_column("analysis_results", "prompt_version")
    op.drop_index("ix_analysis_runs_implementation_id", table_name="analysis_runs")
    op.drop_column("analysis_runs", "error_code")
    op.drop_column("analysis_runs", "stage_history")
    op.drop_column("analysis_runs", "implementation_id")
