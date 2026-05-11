from datetime import timezone

from backend.app.analysis_run_lifecycle import ANALYSIS_STAGES
from backend.app.analysis_run_lifecycle import infer_annual_report_summary_status
from backend.app.analysis_run_lifecycle import infer_file_version_state
from backend.app.schemas import (
    AnalysisRunSummary,
    AnnualReportBriefSummary,
    AnnualReportSummary,
    FileVersionSummary,
)


def to_file_version_summary(file_version) -> FileVersionSummary:
    uploaded_at = file_version.uploaded_at
    if uploaded_at.tzinfo is None:
        uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
    state = infer_file_version_state(file_version)
    return FileVersionSummary(
        id=file_version.id,
        original_filename=file_version.original_filename,
        content_hash=file_version.content_hash,
        uploaded_at=uploaded_at,
        display_status=state.display_status,
        display_status_message=state.display_status_message,
    )


def to_annual_report_brief_summary(annual_report) -> AnnualReportBriefSummary:
    return AnnualReportBriefSummary(
        id=annual_report.id,
        normalized_stock_code=annual_report.normalized_stock_code,
        stock_code=annual_report.stock_code,
        report_year=annual_report.report_year,
        company_full_name=annual_report.company_full_name,
        company_short_name=annual_report.company_short_name,
    )


def to_annual_report_summary(annual_report) -> AnnualReportSummary:
    active_versions = [
        to_file_version_summary(file_version)
        for file_version in annual_report.file_versions
        if not file_version.is_deleted
    ]
    return AnnualReportSummary(
        **to_annual_report_brief_summary(annual_report).model_dump(exclude={"summary_status"}),
        summary_status=infer_annual_report_summary_status(
            file_version.display_status for file_version in active_versions
        ),
        file_versions=active_versions,
    )


def to_analysis_run_summary(run, result=None) -> AnalysisRunSummary:
    created_at = run.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return AnalysisRunSummary(
        id=run.id,
        file_version_id=run.file_version_id,
        implementation_id=run.implementation_id,
        status=run.status,
        stage=run.stage,
        stages=list(run.stage_history or ANALYSIS_STAGES),
        prompt_version=result.prompt_version if result is not None else None,
        chroma_collection_name=run.implementation_id,
        error_code=run.error_code,
        error_message=run.error_message,
        created_at=created_at,
    )
