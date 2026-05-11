from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.library_lifecycle import LibraryLifecycleService
from backend.app.persistence import UploadRepository
from backend.app.presenters import to_annual_report_summary
from backend.app.schemas import (
    AnnualReportDeleteConfirmationResponse,
    AnnualReportDeleteResponse,
    AnnualReportListResponse,
    FileVersionDeleteConfirmationResponse,
    FileVersionDeleteResponse,
)


class AnnualReportLibrary:
    def __init__(
        self,
        *,
        source_pdf_dir: Path,
        library_lifecycle: LibraryLifecycleService,
    ):
        self.source_pdf_dir = source_pdf_dir
        self.library_lifecycle = library_lifecycle

    def list_annual_reports(self, session: Session) -> AnnualReportListResponse:
        repository = UploadRepository(session, self.source_pdf_dir)
        return AnnualReportListResponse(
            items=[
                to_annual_report_summary(report)
                for report in repository.list_annual_reports()
            ]
        )

    def file_version_delete_confirmation(
        self,
        session: Session,
        *,
        file_version_id: int,
    ) -> FileVersionDeleteConfirmationResponse:
        confirmation = self.library_lifecycle.file_version_delete_confirmation(
            session,
            file_version_id=file_version_id,
        )
        return FileVersionDeleteConfirmationResponse(
            file_version_id=confirmation.file_version_id,
            annual_report_id=confirmation.annual_report_id,
            original_filename=confirmation.original_filename,
            analysis_result_count=confirmation.analysis_result_count,
            will_delete_annual_report=confirmation.will_delete_annual_report,
        )

    def delete_file_version(
        self,
        session: Session,
        *,
        file_version_id: int,
    ) -> FileVersionDeleteResponse:
        outcome = self.library_lifecycle.delete_file_version(
            session,
            file_version_id=file_version_id,
        )
        return FileVersionDeleteResponse(
            file_version_id=outcome.file_version_id,
            annual_report_id=outcome.annual_report_id,
            deleted_analysis_result_count=outcome.deleted_analysis_result_count,
            deleted_annual_report_id=outcome.deleted_annual_report_id,
        )

    def annual_report_delete_confirmation(
        self,
        session: Session,
        *,
        annual_report_id: int,
    ) -> AnnualReportDeleteConfirmationResponse:
        confirmation = self.library_lifecycle.annual_report_delete_confirmation(
            session,
            annual_report_id=annual_report_id,
        )
        return AnnualReportDeleteConfirmationResponse(
            annual_report_id=confirmation.annual_report_id,
            file_version_count=confirmation.file_version_count,
            analysis_result_count=confirmation.analysis_result_count,
            file_versions=[
                {
                    "file_version_id": version.file_version_id,
                    "original_filename": version.original_filename,
                    "has_current_analysis_result": version.has_current_analysis_result,
                }
                for version in confirmation.file_versions
            ],
        )

    def delete_annual_report(
        self,
        session: Session,
        *,
        annual_report_id: int,
    ) -> AnnualReportDeleteResponse:
        outcome = self.library_lifecycle.delete_annual_report(
            session,
            annual_report_id=annual_report_id,
        )
        return AnnualReportDeleteResponse(
            annual_report_id=outcome.annual_report_id,
            deleted_file_version_count=outcome.deleted_file_version_count,
            deleted_analysis_result_count=outcome.deleted_analysis_result_count,
        )

    def cleanup_startup_state(self, session: Session) -> None:
        self.library_lifecycle.cleanup_startup_state(session)
