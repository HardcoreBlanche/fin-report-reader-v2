from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AnnualReport(Base):
    __tablename__ = "annual_reports"
    __table_args__ = (UniqueConstraint("normalized_stock_code", "report_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(16), nullable=False)
    normalized_stock_code: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    report_year: Mapped[int] = mapped_column(Integer, nullable=False)
    company_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_short_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    file_versions: Mapped[list["FileVersion"]] = relationship(
        back_populates="annual_report",
        cascade="all, delete-orphan",
        order_by="FileVersion.id",
    )


class FileVersion(Base):
    __tablename__ = "file_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    annual_report_id: Mapped[int] = mapped_column(ForeignKey("annual_reports.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    annual_report: Mapped[AnnualReport] = relationship(back_populates="file_versions")
    active_content_hash: Mapped["ActiveContentHash"] = relationship(
        back_populates="file_version",
        cascade="all, delete-orphan",
        uselist=False,
    )
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="file_version",
        cascade="all, delete-orphan",
        order_by="AnalysisRun.id",
    )
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(
        back_populates="file_version",
        cascade="all, delete-orphan",
        order_by="AnalysisResult.id",
    )


class ActiveContentHash(Base):
    __tablename__ = "active_content_hashes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    file_version_id: Mapped[int] = mapped_column(ForeignKey("file_versions.id"), nullable=False)

    file_version: Mapped[FileVersion] = relationship(back_populates="active_content_hash")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_version_id: Mapped[int] = mapped_column(ForeignKey("file_versions.id"), nullable=False)
    implementation_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_history: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    file_version: Mapped[FileVersion] = relationship(back_populates="analysis_runs")
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(
        back_populates="analysis_run",
        cascade="all, delete-orphan",
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_version_id: Mapped[int] = mapped_column(ForeignKey("file_versions.id"), nullable=False)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_package: Mapped[dict] = mapped_column(JSON, nullable=False)
    structured_outline: Mapped[dict] = mapped_column(JSON, nullable=False)
    qa_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    qa_unavailable_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    file_version: Mapped[FileVersion] = relationship(back_populates="analysis_results")
    analysis_run: Mapped[AnalysisRun] = relationship(back_populates="analysis_results")
