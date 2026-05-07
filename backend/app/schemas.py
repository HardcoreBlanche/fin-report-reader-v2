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
