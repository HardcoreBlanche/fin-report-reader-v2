"""upload admission baseline

Revision ID: 0001_upload_admission_baseline
Revises:
Create Date: 2026-05-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_upload_admission_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annual_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_code", sa.String(length=16), nullable=False),
        sa.Column("normalized_stock_code", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("report_year", sa.Integer(), nullable=False),
        sa.Column("company_full_name", sa.String(length=255), nullable=False),
        sa.Column("company_short_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_stock_code", "report_year"),
    )
    op.create_table(
        "file_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("annual_report_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annual_report_id"], ["annual_reports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_versions_content_hash",
        "file_versions",
        ["content_hash"],
        unique=False,
    )
    op.create_table(
        "active_content_hashes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_version_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["file_version_id"], ["file_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
    )


def downgrade() -> None:
    op.drop_table("active_content_hashes")
    op.drop_index("ix_file_versions_content_hash", table_name="file_versions")
    op.drop_table("file_versions")
    op.drop_table("annual_reports")
