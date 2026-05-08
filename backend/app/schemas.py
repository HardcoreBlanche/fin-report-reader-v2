from datetime import datetime

from pydantic import BaseModel


class FileVersionSummary(BaseModel):
    id: int
    original_filename: str
    content_hash: str
    uploaded_at: datetime
    display_status: str = "not_analyzed"
    display_status_message: str | None = None


class AnnualReportBriefSummary(BaseModel):
    id: int
    normalized_stock_code: str
    stock_code: str
    report_year: int
    company_full_name: str
    company_short_name: str | None
    summary_status: str = "未分析"


class AnnualReportSummary(AnnualReportBriefSummary):
    file_versions: list[FileVersionSummary]


class AnnualReportListResponse(BaseModel):
    items: list[AnnualReportSummary]


class UploadSuccessResponse(BaseModel):
    annual_report: AnnualReportBriefSummary
    file_version: FileVersionSummary
    annual_report_already_exists: bool


class FileVersionDeleteConfirmationResponse(BaseModel):
    file_version_id: int
    annual_report_id: int
    original_filename: str
    analysis_result_count: int
    will_delete_annual_report: bool


class FileVersionDeleteResponse(BaseModel):
    file_version_id: int
    annual_report_id: int
    deleted_analysis_result_count: int
    deleted_annual_report_id: int | None


class AnnualReportDeleteFileVersionPreview(BaseModel):
    file_version_id: int
    original_filename: str
    has_current_analysis_result: bool


class AnnualReportDeleteConfirmationResponse(BaseModel):
    annual_report_id: int
    file_version_count: int
    analysis_result_count: int
    file_versions: list[AnnualReportDeleteFileVersionPreview]


class AnnualReportDeleteResponse(BaseModel):
    annual_report_id: int
    deleted_file_version_count: int
    deleted_analysis_result_count: int


class AnalysisRunSummary(BaseModel):
    id: int
    file_version_id: int
    implementation_id: str
    status: str
    stage: str | None
    stages: list[str]
    prompt_version: str | None = None
    chroma_collection_name: str
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime


class ReportDetailResponse(BaseModel):
    file_version_id: int
    analysis_run_id: int
    title: str
    prompt_version: str
    summary: list[str]
    source_sections: list[dict]
    text_span_index: dict[str, dict]
    table_index: dict[str, dict]
    figure_index: dict[str, dict]
    other_figures: list[dict]
    analysis_sections: list[dict]
    qa_available: bool
    qa_unavailable_reason: str | None
    labels: dict[str, str]


class QaQuestionRequest(BaseModel):
    question: str


class QaAnswerResponse(BaseModel):
    status: str
    answer: str
    evidence: list[dict]
    prompt_version: str = "qa_answer_v1"


class TableAssetResponse(BaseModel):
    table_id: str
    title: str
    summary: str
    page: int
    page_label: str
    source_section_id: str
    columns: list[str]
    rows: list[dict[str, str]]
    notes: list[str]
    metadata: dict
    source_bbox: list[float] | None = None
