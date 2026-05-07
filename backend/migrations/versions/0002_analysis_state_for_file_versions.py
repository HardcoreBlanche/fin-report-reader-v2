"""analysis state for file versions

Revision ID: 0002_analysis_state_for_file_versions
Revises: 0001_upload_admission_baseline
Create Date: 2026-05-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_analysis_state_for_file_versions"
down_revision: str | None = "0001_upload_admission_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("annual_reports") as batch_op:
        batch_op.alter_column(
            "exchange",
            existing_type=sa.String(length=16),
            nullable=True,
        )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_version_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["file_version_id"], ["file_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_runs_file_version_id",
        "analysis_runs",
        ["file_version_id"],
        unique=False,
    )
    op.create_table(
        "analysis_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_version_id", sa.Integer(), nullable=False),
        sa.Column("analysis_run_id", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("qa_available", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"]),
        sa.ForeignKeyConstraint(["file_version_id"], ["file_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_results_file_version_id",
        "analysis_results",
        ["file_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_results_file_version_id", table_name="analysis_results")
    op.drop_table("analysis_results")
    op.drop_index("ix_analysis_runs_file_version_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    with op.batch_alter_table("annual_reports") as batch_op:
        batch_op.alter_column(
            "exchange",
            existing_type=sa.String(length=16),
            nullable=False,
        )
