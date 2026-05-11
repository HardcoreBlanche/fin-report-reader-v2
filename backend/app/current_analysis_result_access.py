from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.evidence_package_projection import projection_from_result
from backend.app.errors import BusinessError
from backend.app.mda_analysis import FigureAssetStore
from backend.app.models import AnalysisResult, FileVersion
from backend.app.qa import AnalysisResultQaService
from backend.app.report_downloads import AnalysisResultDownloadService


@dataclass(frozen=True)
class DownloadedAnalysisResult:
    content: str | bytes
    media_type: str
    filename: str


@dataclass(frozen=True)
class ResolvedFigureAsset:
    path: Path
    content_type: str


class CurrentAnalysisResultAccess:
    def __init__(
        self,
        *,
        report_downloads: AnalysisResultDownloadService,
        qa_service: AnalysisResultQaService,
        figure_asset_store: FigureAssetStore,
    ):
        self.report_downloads = report_downloads
        self.qa_service = qa_service
        self.figure_asset_store = figure_asset_store

    def report_detail(self, session: Session, *, file_version_id: int) -> dict:
        result = self._require_current_result(session, file_version_id=file_version_id)
        return projection_from_result(result).report_detail(
            file_version_id=result.file_version_id,
            analysis_run_id=result.analysis_run_id,
            prompt_version=result.prompt_version,
            structured_outline=result.structured_outline,
            qa_available=result.qa_available,
            qa_unavailable_reason=result.qa_unavailable_reason,
        )

    def answer_question(
        self,
        session: Session,
        *,
        file_version_id: int,
        question: str,
    ) -> dict:
        result = self._require_current_result(session, file_version_id=file_version_id)
        return self.qa_service.answer(result, question)

    def download(
        self,
        session: Session,
        *,
        file_version_id: int,
        format: str,
    ) -> DownloadedAnalysisResult:
        if format not in {"markdown", "zip"}:
            raise BusinessError("UNSUPPORTED_REPORT_DOWNLOAD_FORMAT")

        result = self._require_current_result(session, file_version_id=file_version_id)
        if format == "markdown":
            try:
                markdown = self.report_downloads.render_markdown(result)
            except Exception as exc:
                raise BusinessError("REPORT_MARKDOWN_GENERATION_FAILED") from exc
            return DownloadedAnalysisResult(
                content=markdown,
                media_type="text/markdown; charset=utf-8",
                filename=f"analysis-result-{file_version_id}.md",
            )

        try:
            zip_content = self.report_downloads.build_zip(result)
        except Exception as exc:
            raise BusinessError("REPORT_ZIP_GENERATION_FAILED") from exc
        return DownloadedAnalysisResult(
            content=zip_content,
            media_type="application/zip",
            filename=f"analysis-result-{file_version_id}.zip",
        )

    def table_asset(
        self,
        session: Session,
        *,
        file_version_id: int,
        table_id: str,
    ) -> dict:
        result = self._require_current_result(session, file_version_id=file_version_id)
        table = projection_from_result(result).table_asset(table_id)
        if table is None:
            raise BusinessError("TABLE_ASSET_NOT_FOUND")
        return table

    def figure_asset(
        self,
        session: Session,
        *,
        file_version_id: int,
        image_id: str,
        variant: str,
    ) -> ResolvedFigureAsset:
        result = self._require_current_result(session, file_version_id=file_version_id)
        figure = projection_from_result(result).figure_asset(image_id)
        if figure is None:
            raise BusinessError("FIGURE_ASSET_NOT_FOUND")
        if variant not in {"thumb", "original"}:
            raise BusinessError("FIGURE_ASSET_NOT_FOUND")

        asset = figure["original"] if variant == "original" else figure.get("thumbnail")
        if asset is None:
            asset = figure["original"]
        asset_path = self.figure_asset_store.resolve_asset(
            result.analysis_run.implementation_id,
            asset["storage_key"],
        )
        if not asset_path.exists():
            raise BusinessError("FIGURE_ASSET_NOT_FOUND")
        return ResolvedFigureAsset(path=asset_path, content_type=asset["content_type"])

    def _require_current_result(
        self,
        session: Session,
        *,
        file_version_id: int,
    ) -> AnalysisResult:
        self._require_visible_file_version(session, file_version_id=file_version_id)
        result = session.scalar(
            select(AnalysisResult).where(
                AnalysisResult.file_version_id == file_version_id,
                AnalysisResult.is_current.is_(True),
            )
        )
        if result is None:
            raise BusinessError("ANALYSIS_RESULT_NOT_FOUND")
        return result

    def _require_visible_file_version(
        self,
        session: Session,
        *,
        file_version_id: int,
    ) -> FileVersion:
        file_version = session.get(FileVersion, file_version_id)
        if (
            file_version is None
            or file_version.is_deleted
            or file_version.annual_report.is_deleted
        ):
            raise BusinessError("FILE_VERSION_NOT_FOUND")
        return file_version
