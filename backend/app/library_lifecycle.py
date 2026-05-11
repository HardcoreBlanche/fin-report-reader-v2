from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.analysis_run_lifecycle import AnalysisRunLifecycle
from backend.app.errors import BusinessError
from backend.app.mda_analysis import (
    AnalysisResourceCleaner,
    FigureAssetStore,
)
from backend.app.models import AnalysisResult, AnalysisRun, AnnualReport, FileVersion


@dataclass(frozen=True)
class FileVersionDeleteConfirmation:
    file_version_id: int
    annual_report_id: int
    original_filename: str
    analysis_result_count: int
    will_delete_annual_report: bool


@dataclass(frozen=True)
class FileVersionDeleteOutcome:
    file_version_id: int
    annual_report_id: int
    deleted_analysis_result_count: int
    deleted_annual_report_id: int | None


@dataclass(frozen=True)
class AnnualReportDeleteFileVersionPreview:
    file_version_id: int
    original_filename: str
    has_current_analysis_result: bool


@dataclass(frozen=True)
class AnnualReportDeleteConfirmation:
    annual_report_id: int
    file_version_count: int
    analysis_result_count: int
    file_versions: list[AnnualReportDeleteFileVersionPreview]


@dataclass(frozen=True)
class AnnualReportDeleteOutcome:
    annual_report_id: int
    deleted_file_version_count: int
    deleted_analysis_result_count: int


class LibraryLifecycleService:
    def __init__(
        self,
        *,
        source_pdf_dir: Path,
        resource_cleaner: AnalysisResourceCleaner,
        figure_asset_store: FigureAssetStore,
        analysis_run_lifecycle: AnalysisRunLifecycle | None = None,
    ):
        self.source_pdf_dir = source_pdf_dir
        self.resource_cleaner = resource_cleaner
        self.figure_asset_store = figure_asset_store
        self.analysis_run_lifecycle = analysis_run_lifecycle or AnalysisRunLifecycle(
            resource_cleaner=resource_cleaner,
            figure_asset_store=figure_asset_store,
        )

    def file_version_delete_confirmation(
        self,
        session: Session,
        *,
        file_version_id: int,
    ) -> FileVersionDeleteConfirmation:
        file_version = self._require_active_file_version(session, file_version_id)
        report = file_version.annual_report
        has_analysis_result = self._lifecycle().current_analysis_result_exists(
            session,
            file_version.id,
        )
        will_delete_annual_report = not any(
            version.id != file_version.id and not version.is_deleted
            for version in report.file_versions
        )
        return FileVersionDeleteConfirmation(
            file_version_id=file_version.id,
            annual_report_id=report.id,
            original_filename=file_version.original_filename,
            analysis_result_count=1 if has_analysis_result else 0,
            will_delete_annual_report=will_delete_annual_report,
        )

    def delete_file_version(
        self,
        session: Session,
        *,
        file_version_id: int,
    ) -> FileVersionDeleteOutcome:
        file_version = self._require_active_file_version(session, file_version_id)
        outcome = self._delete_file_version_internal(
            session,
            file_version=file_version,
            mark_empty_annual_report=True,
        )
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            if outcome.deleted_annual_report_id is not None:
                raise BusinessError("DELETE_EMPTY_ANNUAL_REPORT_FAILED") from exc
            raise BusinessError("DELETE_FILE_VERSION_FAILED") from exc
        return outcome

    def annual_report_delete_confirmation(
        self,
        session: Session,
        *,
        annual_report_id: int,
    ) -> AnnualReportDeleteConfirmation:
        report = self._require_active_annual_report(session, annual_report_id)
        file_versions = [
            version for version in report.file_versions if not version.is_deleted
        ]
        previews: list[AnnualReportDeleteFileVersionPreview] = []
        analysis_result_count = 0
        for version in file_versions:
            has_result = self._lifecycle().current_analysis_result_exists(
                session,
                version.id,
            )
            if has_result:
                analysis_result_count += 1
            previews.append(
                AnnualReportDeleteFileVersionPreview(
                    file_version_id=version.id,
                    original_filename=version.original_filename,
                    has_current_analysis_result=has_result,
                )
            )
        return AnnualReportDeleteConfirmation(
            annual_report_id=report.id,
            file_version_count=len(file_versions),
            analysis_result_count=analysis_result_count,
            file_versions=previews,
        )

    def delete_annual_report(
        self,
        session: Session,
        *,
        annual_report_id: int,
    ) -> AnnualReportDeleteOutcome:
        report = self._require_active_annual_report(session, annual_report_id)
        file_versions = [
            version for version in report.file_versions if not version.is_deleted
        ]
        if any(self._has_active_analysis_run(session, version.id) for version in file_versions):
            raise BusinessError("ANNUAL_REPORT_HAS_ANALYSIS_IN_PROGRESS")

        deleted_analysis_result_count = 0
        for version in file_versions:
            try:
                outcome = self._delete_file_version_internal(
                    session,
                    file_version=version,
                    mark_empty_annual_report=False,
                )
            except BusinessError as exc:
                session.rollback()
                raise BusinessError("DELETE_ANNUAL_REPORT_FILE_VERSIONS_FAILED") from exc
            deleted_analysis_result_count += outcome.deleted_analysis_result_count

        report.is_deleted = True
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise BusinessError("DELETE_ANNUAL_REPORT_FAILED") from exc

        return AnnualReportDeleteOutcome(
            annual_report_id=report.id,
            deleted_file_version_count=len(file_versions),
            deleted_analysis_result_count=deleted_analysis_result_count,
        )

    def cleanup_startup_state(self, session: Session) -> None:
        reports = list(
            session.scalars(
                select(AnnualReport).where(AnnualReport.is_deleted.is_(False))
            )
        )
        for report in reports:
            for file_version in [version for version in report.file_versions if not version.is_deleted]:
                if not Path(file_version.storage_path).exists():
                    self._lifecycle().cleanup_missing_source_file_version(
                        session,
                        file_version,
                    )
            if not any(not version.is_deleted for version in report.file_versions):
                report.is_deleted = True

        self._lifecycle().cleanup_orphan_report_asset_dirs(session)
        try:
            session.commit()
        except Exception:
            session.rollback()

    def _delete_file_version_internal(
        self,
        session: Session,
        *,
        file_version: FileVersion,
        mark_empty_annual_report: bool,
    ) -> FileVersionDeleteOutcome:
        self._lifecycle().require_no_active_analysis_run(session, file_version.id)

        deleted_analysis_result_count = 0
        run = self._lifecycle().delete_current_result(
            session,
            file_version_id=file_version.id,
            missing_ok=True,
        )
        if run is not None:
            deleted_analysis_result_count = 1

        self._delete_source_pdf(file_version.storage_path)
        if file_version.active_content_hash is not None:
            session.delete(file_version.active_content_hash)
        file_version.is_deleted = True

        deleted_annual_report_id: int | None = None
        if mark_empty_annual_report and not any(
            not version.is_deleted for version in file_version.annual_report.file_versions
        ):
            file_version.annual_report.is_deleted = True
            deleted_annual_report_id = file_version.annual_report.id

        return FileVersionDeleteOutcome(
            file_version_id=file_version.id,
            annual_report_id=file_version.annual_report_id,
            deleted_analysis_result_count=deleted_analysis_result_count,
            deleted_annual_report_id=deleted_annual_report_id,
        )

    def _delete_source_pdf(self, storage_path: str) -> None:
        source_path = Path(storage_path)
        try:
            resolved = source_path.resolve()
            root = self.source_pdf_dir.resolve()
        except OSError as exc:
            raise BusinessError("DELETE_SOURCE_PDF_FAILED") from exc

        if resolved != root and root not in resolved.parents:
            raise BusinessError("DELETE_SOURCE_PDF_FAILED")
        if not resolved.exists():
            return

        try:
            resolved.unlink()
        except OSError as exc:
            raise BusinessError("DELETE_SOURCE_PDF_FAILED") from exc

    def _require_active_file_version(self, session: Session, file_version_id: int) -> FileVersion:
        file_version = session.get(FileVersion, file_version_id)
        if file_version is None or file_version.is_deleted:
            raise BusinessError("FILE_VERSION_NOT_FOUND")
        if file_version.annual_report.is_deleted:
            raise BusinessError("FILE_VERSION_NOT_FOUND")
        return file_version

    def _require_active_annual_report(self, session: Session, annual_report_id: int) -> AnnualReport:
        annual_report = session.get(AnnualReport, annual_report_id)
        if annual_report is None or annual_report.is_deleted:
            raise BusinessError("ANNUAL_REPORT_NOT_FOUND")
        return annual_report

    def _has_active_analysis_run(self, session: Session, file_version_id: int) -> bool:
        return self._lifecycle().has_active_analysis_run(session, file_version_id)

    def _current_result(self, session: Session, file_version_id: int) -> AnalysisResult | None:
        return session.scalar(
            select(AnalysisResult).where(
                AnalysisResult.file_version_id == file_version_id,
                AnalysisResult.is_current.is_(True),
            )
        )

    def _lifecycle(self) -> AnalysisRunLifecycle:
        if (
            self.analysis_run_lifecycle.resource_cleaner is not self.resource_cleaner
            or self.analysis_run_lifecycle.figure_asset_store is not self.figure_asset_store
        ):
            self.analysis_run_lifecycle = AnalysisRunLifecycle(
                resource_cleaner=self.resource_cleaner,
                figure_asset_store=self.figure_asset_store,
            )
        return self.analysis_run_lifecycle
