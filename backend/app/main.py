from datetime import timezone
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.app.admission import UploadAdmissionService
from backend.app.errors import BusinessError, error_response_payload
from backend.app.mda_analysis import (
    ANALYSIS_STAGES,
    FigureAssetStore,
    FigureVisualAnalyzer,
    FilesystemFigureAssetStore,
    AnalysisResourceCleaner,
    FilesystemAnalysisResourceCleaner,
    MdaAnalysisService,
    MdaOutlineGenerator,
    QaIndexer,
    figure_asset_from_result,
    report_detail_from_result,
    table_asset_from_result,
)
from backend.app.models import AnalysisResult
from backend.app.pdf_extraction import PdfTextExtractor, PyMuPdfTextExtractor
from backend.app.persistence import UploadRepository, create_session_factory
from backend.app.persistence import DuplicateActiveFileVersionError
from backend.app.qa import AnalysisResultQaService, QaAnswerGenerator
from backend.app.report_downloads import AnalysisResultDownloadService
from backend.app.schemas import (
    AnalysisRunSummary,
    AnnualReportBriefSummary,
    AnnualReportListResponse,
    AnnualReportSummary,
    FileVersionSummary,
    QaAnswerResponse,
    QaQuestionRequest,
    ReportDetailResponse,
    TableAssetResponse,
    UploadSuccessResponse,
)
from sqlalchemy import select


def create_app(
    *,
    database_url: str = "sqlite:///backend/data/app.db",
    source_pdf_dir: Path | str = Path("backend/data/source_pdfs"),
    extractor: PdfTextExtractor | None = None,
    outline_generator: MdaOutlineGenerator | None = None,
    qa_indexer: QaIndexer | None = None,
    figure_visual_analyzer: FigureVisualAnalyzer | None = None,
    figure_asset_store: FigureAssetStore | None = None,
    resource_cleaner: AnalysisResourceCleaner | None = None,
    qa_answer_generator: QaAnswerGenerator | None = None,
    analysis_artifact_dir: Path | str = Path("backend/data/analysis_artifacts"),
    report_asset_dir: Path | str = Path("backend/data/report_assets"),
    analysis_concurrency_limit: int = 2,
) -> FastAPI:
    app = FastAPI(title="Fin Report Reader API")
    text_extractor = extractor or PyMuPdfTextExtractor()
    app.state.session_factory = create_session_factory(database_url)
    app.state.source_pdf_dir = Path(source_pdf_dir)
    app.state.admission = UploadAdmissionService(text_extractor)
    app.state.figure_asset_store = figure_asset_store or FilesystemFigureAssetStore(
        Path(report_asset_dir)
    )
    app.state.mda_analysis = MdaAnalysisService(
        extractor=text_extractor,
        outline_generator=outline_generator,
        qa_indexer=qa_indexer,
        figure_visual_analyzer=figure_visual_analyzer,
        figure_asset_store=app.state.figure_asset_store,
        resource_cleaner=resource_cleaner
        or FilesystemAnalysisResourceCleaner(Path(analysis_artifact_dir)),
    )
    app.state.report_downloads = AnalysisResultDownloadService(app.state.figure_asset_store)
    app.state.qa = AnalysisResultQaService(qa_answer_generator)
    app.state.analysis_concurrency_limit = analysis_concurrency_limit

    @app.exception_handler(BusinessError)
    async def business_error_handler(_request: Request, exc: BusinessError) -> JSONResponse:
        headers = {"Retry-After": "30"} if exc.spec.error_code == "ANALYSIS_CONCURRENCY_LIMIT_REACHED" else None
        return JSONResponse(
            status_code=exc.spec.status_code,
            content=error_response_payload(exc),
            headers=headers,
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

    @app.post(
        "/api/file-versions/{file_version_id}/analysis-runs",
        response_model=AnalysisRunSummary,
        status_code=201,
    )
    async def start_analysis(file_version_id: int) -> AnalysisRunSummary:
        session = app.state.session_factory()
        try:
            started = app.state.mda_analysis.start_analysis(
                session,
                file_version_id=file_version_id,
                concurrency_limit=app.state.analysis_concurrency_limit,
            )
            return to_analysis_run_summary(started.run, started.result)
        finally:
            session.close()

    @app.post(
        "/api/file-versions/{file_version_id}/analysis-runs/stop",
        response_model=AnalysisRunSummary,
    )
    async def stop_analysis(file_version_id: int) -> AnalysisRunSummary:
        session = app.state.session_factory()
        try:
            run = app.state.mda_analysis.stop_analysis(
                session,
                file_version_id=file_version_id,
            )
            return to_analysis_run_summary(run)
        finally:
            session.close()

    @app.get(
        "/api/file-versions/{file_version_id}/analysis-result",
        response_model=ReportDetailResponse,
    )
    async def get_analysis_result(file_version_id: int) -> ReportDetailResponse:
        session = app.state.session_factory()
        try:
            result = session.scalar(
                select(AnalysisResult).where(
                    AnalysisResult.file_version_id == file_version_id,
                    AnalysisResult.is_current.is_(True),
                )
            )
            if result is None:
                raise BusinessError("ANALYSIS_RESULT_NOT_FOUND")
            return ReportDetailResponse(**report_detail_from_result(result))
        finally:
            session.close()

    @app.post(
        "/api/file-versions/{file_version_id}/analysis-result/qa",
        response_model=QaAnswerResponse,
    )
    async def answer_analysis_result_question(
        file_version_id: int,
        request: QaQuestionRequest,
    ) -> QaAnswerResponse:
        if not request.question.strip():
            raise BusinessError("EMPTY_QUESTION")

        session = app.state.session_factory()
        try:
            result = session.scalar(
                select(AnalysisResult).where(
                    AnalysisResult.file_version_id == file_version_id,
                    AnalysisResult.is_current.is_(True),
                )
            )
            if result is None:
                raise BusinessError("ANALYSIS_RESULT_NOT_FOUND")
            return QaAnswerResponse(**app.state.qa.answer(result, request.question))
        finally:
            session.close()

    @app.get("/api/file-versions/{file_version_id}/analysis-result/download")
    async def download_analysis_result(
        file_version_id: int,
        format: str = "markdown",
    ) -> Response:
        if format not in {"markdown", "zip"}:
            raise BusinessError("UNSUPPORTED_REPORT_DOWNLOAD_FORMAT")

        session = app.state.session_factory()
        try:
            result = session.scalar(
                select(AnalysisResult).where(
                    AnalysisResult.file_version_id == file_version_id,
                    AnalysisResult.is_current.is_(True),
                )
            )
            if result is None:
                raise BusinessError("ANALYSIS_RESULT_NOT_FOUND")
            if format == "markdown":
                try:
                    markdown = app.state.report_downloads.render_markdown(result)
                except Exception as exc:
                    raise BusinessError("REPORT_MARKDOWN_GENERATION_FAILED") from exc
                return Response(
                    content=markdown,
                    media_type="text/markdown; charset=utf-8",
                    headers={
                        "Content-Disposition": (
                            f'attachment; filename="analysis-result-{file_version_id}.md"'
                        )
                    },
                )
            try:
                zip_content = app.state.report_downloads.build_zip(result)
            except Exception as exc:
                raise BusinessError("REPORT_ZIP_GENERATION_FAILED") from exc
            return Response(
                content=zip_content,
                media_type="application/zip",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="analysis-result-{file_version_id}.zip"'
                    )
                },
            )
        finally:
            session.close()

    @app.get(
        "/api/file-versions/{file_version_id}/analysis-result/tables/{table_id}",
        response_model=TableAssetResponse,
    )
    async def get_analysis_result_table(
        file_version_id: int,
        table_id: str,
    ) -> TableAssetResponse:
        session = app.state.session_factory()
        try:
            result = session.scalar(
                select(AnalysisResult).where(
                    AnalysisResult.file_version_id == file_version_id,
                    AnalysisResult.is_current.is_(True),
                )
            )
            if result is None:
                raise BusinessError("ANALYSIS_RESULT_NOT_FOUND")
            table = table_asset_from_result(result, table_id)
            if table is None:
                raise BusinessError("TABLE_ASSET_NOT_FOUND")
            return TableAssetResponse(**table)
        finally:
            session.close()

    @app.get("/api/file-versions/{file_version_id}/analysis-result/figures/{image_id}")
    async def get_analysis_result_figure(
        file_version_id: int,
        image_id: str,
        variant: str = "thumb",
    ) -> FileResponse:
        session = app.state.session_factory()
        try:
            result = session.scalar(
                select(AnalysisResult).where(
                    AnalysisResult.file_version_id == file_version_id,
                    AnalysisResult.is_current.is_(True),
                )
            )
            if result is None:
                raise BusinessError("ANALYSIS_RESULT_NOT_FOUND")
            figure = figure_asset_from_result(result, image_id)
            if figure is None:
                raise BusinessError("FIGURE_ASSET_NOT_FOUND")
            if variant not in {"thumb", "original"}:
                raise BusinessError("FIGURE_ASSET_NOT_FOUND")
            asset = figure["original"] if variant == "original" else figure.get("thumbnail")
            if asset is None:
                asset = figure["original"]
            asset_path = app.state.figure_asset_store.resolve_asset(
                result.analysis_run.implementation_id,
                asset["storage_key"],
            )
            if not asset_path.exists():
                raise BusinessError("FIGURE_ASSET_NOT_FOUND")
            return FileResponse(asset_path, media_type=asset["content_type"])
        finally:
            session.close()

    @app.delete(
        "/api/file-versions/{file_version_id}/analysis-result",
        response_model=AnalysisRunSummary,
    )
    async def delete_analysis_result(file_version_id: int) -> AnalysisRunSummary:
        session = app.state.session_factory()
        try:
            run = app.state.mda_analysis.delete_analysis_result(
                session,
                file_version_id=file_version_id,
            )
            return to_analysis_run_summary(run)
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
