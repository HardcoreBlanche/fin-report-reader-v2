from datetime import timezone
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse

from backend.app.admission import UploadAdmissionService
from backend.app.errors import BusinessError, error_response_payload
from backend.app.pdf_extraction import PdfTextExtractor, PyMuPdfTextExtractor
from backend.app.persistence import UploadRepository, create_session_factory
from backend.app.persistence import DuplicateActiveFileVersionError
from backend.app.schemas import (
    AnnualReportBriefSummary,
    AnnualReportListResponse,
    AnnualReportSummary,
    FileVersionSummary,
    UploadSuccessResponse,
)


def create_app(
    *,
    database_url: str = "sqlite:///backend/data/app.db",
    source_pdf_dir: Path | str = Path("backend/data/source_pdfs"),
    extractor: PdfTextExtractor | None = None,
) -> FastAPI:
    app = FastAPI(title="Fin Report Reader API")
    app.state.session_factory = create_session_factory(database_url)
    app.state.source_pdf_dir = Path(source_pdf_dir)
    app.state.admission = UploadAdmissionService(extractor or PyMuPdfTextExtractor())

    @app.exception_handler(BusinessError)
    async def business_error_handler(_request: Request, exc: BusinessError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.spec.status_code,
            content=error_response_payload(exc),
        )

    @app.post("/api/uploads/annual-reports", response_model=UploadSuccessResponse, status_code=201)
    async def upload_annual_report(file: UploadFile = File(...)) -> UploadSuccessResponse:
        content = await file.read()
        filename = file.filename or ""
        admitted = app.state.admission.admit(filename, content)
        content_hash = sha256(content).hexdigest()

        session = app.state.session_factory()
        try:
            repository = UploadRepository(session, app.state.source_pdf_dir)
            annual_report, file_version, already_exists = repository.persist_upload(
                filename=filename,
                content=content,
                content_hash=content_hash,
                admitted=admitted,
            )
            return UploadSuccessResponse(
                annual_report=to_annual_report_brief_summary(annual_report),
                file_version=to_file_version_summary(file_version),
                annual_report_already_exists=already_exists,
            )
        except DuplicateActiveFileVersionError as exc:
            raise BusinessError(
                "DUPLICATE_FILE_VERSION",
                details={
                    "annual_report": to_annual_report_brief_summary(
                        exc.file_version.annual_report
                    ).model_dump(mode="json"),
                    "file_version": to_file_version_summary(exc.file_version).model_dump(
                        mode="json"
                    ),
                },
            ) from exc
        finally:
            session.close()

    @app.get("/api/annual-reports", response_model=AnnualReportListResponse)
    async def list_annual_reports() -> AnnualReportListResponse:
        session = app.state.session_factory()
        try:
            repository = UploadRepository(session, app.state.source_pdf_dir)
            return AnnualReportListResponse(
                items=[to_annual_report_summary(report) for report in repository.list_annual_reports()]
            )
        finally:
            session.close()

    return app


def to_file_version_summary(file_version) -> FileVersionSummary:
    uploaded_at = file_version.uploaded_at
    if uploaded_at.tzinfo is None:
        uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
    display_status, display_status_message = infer_file_version_display_state(file_version)
    return FileVersionSummary(
        id=file_version.id,
        original_filename=file_version.original_filename,
        content_hash=file_version.content_hash,
        uploaded_at=uploaded_at,
        display_status=display_status,
        display_status_message=display_status_message,
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
        summary_status=infer_annual_report_summary_status(active_versions),
        file_versions=active_versions,
    )


def infer_file_version_display_state(file_version) -> tuple[str, str | None]:
    current_result = next(
        (result for result in file_version.analysis_results if result.is_current),
        None,
    )
    if current_result is not None:
        return "analyzed", None

    latest_run = max(
        file_version.analysis_runs,
        key=lambda run: (run.created_at, run.id),
        default=None,
    )
    if latest_run is None or latest_run.status == "result_deleted":
        return "not_analyzed", None
    if latest_run.status in {"parsing", "generating"}:
        return "analyzing", None
    if latest_run.status == "ready":
        return "analysis_failed", "分析结果缺失"
    if latest_run.status == "failed":
        return "analysis_failed", latest_run.error_message
    if latest_run.status == "stopped":
        return "stopped", None
    return "not_analyzed", None


def infer_annual_report_summary_status(file_versions: list[FileVersionSummary]) -> str:
    statuses = {file_version.display_status for file_version in file_versions}
    if "analyzing" in statuses:
        return "分析中"
    if "analyzed" in statuses:
        return "有报告"
    if "analysis_failed" in statuses:
        return "有失败"
    if "stopped" in statuses:
        return "已停止"
    return "未分析"
