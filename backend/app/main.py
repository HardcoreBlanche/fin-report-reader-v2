from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.app.admission import UploadAdmissionService
from backend.app.analysis_run_lifecycle import AnalysisRunLifecycle
from backend.app.annual_report_library import AnnualReportLibrary
from backend.app.annual_report_upload_intake import AnnualReportUploadIntake
from backend.app.current_analysis_result_access import CurrentAnalysisResultAccess
from backend.app.errors import BusinessError, error_response_payload
from backend.app.library_lifecycle import LibraryLifecycleService
from backend.app.mda_analysis import (
    FigureAssetStore,
    FigureVisualAnalyzer,
    FilesystemFigureAssetStore,
    AnalysisResourceCleaner,
    FilesystemAnalysisResourceCleaner,
    MdaAnalysisService,
    MdaOutlineGenerator,
    QaIndexer,
)
from backend.app.pdf_extraction import PdfTextExtractor, PyMuPdfTextExtractor
from backend.app.persistence import create_session_factory
from backend.app.presenters import to_analysis_run_summary
from backend.app.qa import AnalysisResultQaService, QaAnswerGenerator
from backend.app.report_downloads import AnalysisResultDownloadService
from backend.app.schemas import (
    AnalysisRunSummary,
    AnnualReportDeleteConfirmationResponse,
    AnnualReportDeleteResponse,
    AnnualReportListResponse,
    FileVersionDeleteConfirmationResponse,
    FileVersionDeleteResponse,
    QaAnswerResponse,
    QaQuestionRequest,
    ReportDetailResponse,
    TableAssetResponse,
    UploadSuccessResponse,
)
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
    app.state.upload_intake = AnnualReportUploadIntake(
        admission=app.state.admission,
        source_pdf_dir=app.state.source_pdf_dir,
    )
    app.state.figure_asset_store = figure_asset_store or FilesystemFigureAssetStore(
        Path(report_asset_dir)
    )
    resolved_resource_cleaner = resource_cleaner or FilesystemAnalysisResourceCleaner(
        Path(analysis_artifact_dir)
    )
    app.state.analysis_run_lifecycle = AnalysisRunLifecycle(
        resource_cleaner=resolved_resource_cleaner,
        figure_asset_store=app.state.figure_asset_store,
    )
    app.state.mda_analysis = MdaAnalysisService(
        extractor=text_extractor,
        outline_generator=outline_generator,
        qa_indexer=qa_indexer,
        figure_visual_analyzer=figure_visual_analyzer,
        figure_asset_store=app.state.figure_asset_store,
        resource_cleaner=resolved_resource_cleaner,
        analysis_run_lifecycle=app.state.analysis_run_lifecycle,
    )
    app.state.library_lifecycle = LibraryLifecycleService(
        source_pdf_dir=app.state.source_pdf_dir,
        resource_cleaner=resolved_resource_cleaner,
        figure_asset_store=app.state.figure_asset_store,
        analysis_run_lifecycle=app.state.analysis_run_lifecycle,
    )
    app.state.annual_report_library = AnnualReportLibrary(
        source_pdf_dir=app.state.source_pdf_dir,
        library_lifecycle=app.state.library_lifecycle,
    )
    app.state.report_downloads = AnalysisResultDownloadService(app.state.figure_asset_store)
    app.state.qa = AnalysisResultQaService(qa_answer_generator)
    app.state.current_analysis_result_access = CurrentAnalysisResultAccess(
        report_downloads=app.state.report_downloads,
        qa_service=app.state.qa,
        figure_asset_store=app.state.figure_asset_store,
    )
    app.state.analysis_concurrency_limit = analysis_concurrency_limit

    session = app.state.session_factory()
    try:
        app.state.annual_report_library.cleanup_startup_state(session)
    finally:
        session.close()

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

        session = app.state.session_factory()
        try:
            return app.state.upload_intake.upload(
                session,
                filename=filename,
                content=content,
            )
        finally:
            session.close()

    @app.get("/api/annual-reports", response_model=AnnualReportListResponse)
    async def list_annual_reports() -> AnnualReportListResponse:
        session = app.state.session_factory()
        try:
            return app.state.annual_report_library.list_annual_reports(session)
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
            report_detail = app.state.current_analysis_result_access.report_detail(
                session,
                file_version_id=file_version_id,
            )
            return ReportDetailResponse(**report_detail)
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
            answer = app.state.current_analysis_result_access.answer_question(
                session,
                file_version_id=file_version_id,
                question=request.question,
            )
            return QaAnswerResponse(**answer)
        finally:
            session.close()

    @app.get("/api/file-versions/{file_version_id}/analysis-result/download")
    async def download_analysis_result(
        file_version_id: int,
        format: str = "markdown",
    ) -> Response:
        session = app.state.session_factory()
        try:
            downloaded = app.state.current_analysis_result_access.download(
                session,
                file_version_id=file_version_id,
                format=format,
            )
            return Response(
                content=downloaded.content,
                media_type=downloaded.media_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{downloaded.filename}"'
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
            table = app.state.current_analysis_result_access.table_asset(
                session,
                file_version_id=file_version_id,
                table_id=table_id,
            )
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
            asset = app.state.current_analysis_result_access.figure_asset(
                session,
                file_version_id=file_version_id,
                image_id=image_id,
                variant=variant,
            )
            return FileResponse(asset.path, media_type=asset.content_type)
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

    @app.get(
        "/api/file-versions/{file_version_id}/delete-confirmation",
        response_model=FileVersionDeleteConfirmationResponse,
    )
    async def get_file_version_delete_confirmation(
        file_version_id: int,
    ) -> FileVersionDeleteConfirmationResponse:
        session = app.state.session_factory()
        try:
            return app.state.annual_report_library.file_version_delete_confirmation(
                session,
                file_version_id=file_version_id,
            )
        finally:
            session.close()

    @app.delete(
        "/api/file-versions/{file_version_id}",
        response_model=FileVersionDeleteResponse,
    )
    async def delete_file_version(
        file_version_id: int,
        confirm: bool = False,
    ) -> FileVersionDeleteResponse:
        if not confirm:
            raise BusinessError("DELETE_CONFIRMATION_REQUIRED")

        session = app.state.session_factory()
        try:
            return app.state.annual_report_library.delete_file_version(
                session,
                file_version_id=file_version_id,
            )
        finally:
            session.close()

    @app.get(
        "/api/annual-reports/{annual_report_id}/delete-confirmation",
        response_model=AnnualReportDeleteConfirmationResponse,
    )
    async def get_annual_report_delete_confirmation(
        annual_report_id: int,
    ) -> AnnualReportDeleteConfirmationResponse:
        session = app.state.session_factory()
        try:
            return app.state.annual_report_library.annual_report_delete_confirmation(
                session,
                annual_report_id=annual_report_id,
            )
        finally:
            session.close()

    @app.delete(
        "/api/annual-reports/{annual_report_id}",
        response_model=AnnualReportDeleteResponse,
    )
    async def delete_annual_report(
        annual_report_id: int,
        confirm: bool = False,
    ) -> AnnualReportDeleteResponse:
        if not confirm:
            raise BusinessError("DELETE_CONFIRMATION_REQUIRED")

        session = app.state.session_factory()
        try:
            return app.state.annual_report_library.delete_annual_report(
                session,
                annual_report_id=annual_report_id,
            )
        finally:
            session.close()

    return app
