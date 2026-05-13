from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Protocol

from sqlalchemy.orm import Session

from backend.app.analysis_run_lifecycle import AnalysisRunLifecycle
from backend.app.errors import BusinessError
from backend.app.management_discussion_analysis_execution import (
    FigureAssetStore,
    FigureVisualAnalyzer,
    ManagementDiscussionAnalysisExecution,
    MdaOutlineGenerator,
    QaIndexer,
)
from backend.app.models import AnalysisResult, AnalysisRun
from backend.app.openai_like_figure_visual_analyzer import build_default_figure_visual_analyzer
from backend.app.pdf_extraction import PdfFigureCandidate, PdfTextExtractor


class AnalysisStopped(Exception):
    """Raised inside the orchestrator when a stop request has reached the run."""


class AnalysisResourceCleaner(Protocol):
    def cleanup_run(self, implementation_id: str) -> None:
        """Remove run-scoped intermediate artifacts and generated resources."""


class ExtractiveMdaOutlineGenerator:
    prompt_version = "mda_outline_v1"

    def generate(
        self,
        evidence_package: dict,
        validation_errors: list[str] | None = None,
    ) -> dict:
        text_spans = evidence_package["text_spans"]
        summary_source = [span["text"] for span in text_spans[:3]]
        while len(summary_source) < 3:
            summary_source.append(summary_source[-1] if summary_source else "管理层讨论与分析披露了经营情况。")

        points = []
        for span in text_spans[:3]:
            points.append(
                {
                    "text": span["text"],
                    "source_section_ids": [span["source_section_id"]],
                    "evidence": [
                        {
                            "content_type": "text",
                            "source_section_id": span["source_section_id"],
                            "text_span_id": span["text_span_id"],
                            "evidence_text": span["text"][:80],
                        }
                    ],
                }
            )
        for table in evidence_package.get("tables", [])[:1]:
            points.append(
                {
                    "text": table["summary"],
                    "source_section_ids": [table["source_section_id"]],
                    "evidence": [
                        {
                            "content_type": "table",
                            "source_section_id": table["source_section_id"],
                            "table_id": table["table_id"],
                            "evidence_text": table["summary"],
                        }
                    ],
                }
            )

        return {
            "summary": [f"{sentence.rstrip('。')}。" for sentence in summary_source[:3]],
            "analysis_sections": [{"title": "经营情况", "points": points}],
        }


class NoopQaIndexer:
    def build_index(self, implementation_id: str, evidence_package: dict) -> tuple[bool, str | None]:
        return True, None


class UnavailableFigureVisualAnalyzer:
    prompt_version = "figure_summary_v1"

    def is_available(self) -> bool:
        return False

    def summarize(self, candidate: PdfFigureCandidate) -> dict:
        raise RuntimeError("visual model is unavailable")


class ConservativeFigureVisualAnalyzer:
    prompt_version = "figure_summary_v1"

    def is_available(self) -> bool:
        return True

    def summarize(self, candidate: PdfFigureCandidate) -> dict:
        title = candidate.title or candidate.caption or "图示"
        return {
            "is_informational": True,
            "classification_reason": "通过 PDF 图像候选进入图示分析路径。",
            "summary": f"{title}位于管理层讨论与分析章节，需要结合图示内容解读。",
            "relevance": "high",
            "relevance_reason": "该图示来自管理层讨论与分析正文。",
        }


class FilesystemFigureAssetStore:
    def __init__(self, root: Path):
        self.root = root

    def prepare_figure_asset(
        self,
        *,
        implementation_id: str,
        image_id: str,
        image_bytes: bytes,
        image_extension: str,
        width: int,
        height: int,
    ) -> dict:
        extension = _safe_image_extension(image_extension)
        content_type = f"image/{'jpeg' if extension in {'jpg', 'jpeg'} else extension}"
        original_key = f"{implementation_id}/figures/{image_id}.{extension}"
        thumb_key = f"{implementation_id}/thumbs/{image_id}.{extension}"
        temp_original = self._temp_path(implementation_id, "figures", image_id, extension)
        temp_thumb = self._temp_path(implementation_id, "thumbs", image_id, extension)
        temp_original.parent.mkdir(parents=True, exist_ok=True)
        temp_thumb.parent.mkdir(parents=True, exist_ok=True)
        temp_original.write_bytes(image_bytes)

        thumbnail: dict[str, Any] | None = None
        try:
            temp_thumb.write_bytes(self._thumbnail_bytes(image_bytes))
            thumbnail = {
                "storage_key": thumb_key,
                "content_type": content_type,
                "byte_size": len(image_bytes),
                "width": width,
                "height": height,
            }
        except Exception:
            thumbnail = None

        return {
            "original": {
                "storage_key": original_key,
                "content_type": content_type,
                "byte_size": len(image_bytes),
                "width": width,
                "height": height,
            },
            "thumbnail": thumbnail,
        }

    def promote_run_assets(self, implementation_id: str) -> None:
        temp_root = self.root / "_tmp" / implementation_id
        if not temp_root.exists():
            return
        for source in temp_root.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(temp_root)
            target = self.root / implementation_id / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
        self._remove_empty_dirs(temp_root)

    def cleanup_run(self, implementation_id: str) -> None:
        self._remove_tree(self.root / "_tmp" / implementation_id)
        self._remove_tree(self.root / implementation_id)

    def resolve_asset(self, implementation_id: str, storage_key: str) -> Path:
        expected_prefix = f"{implementation_id}/"
        if not storage_key.startswith(expected_prefix):
            raise RuntimeError("figure asset key does not belong to this analysis run")
        resolved = (self.root / storage_key).resolve()
        root = self.root.resolve()
        if resolved != root and root not in resolved.parents:
            raise RuntimeError("refusing to read figure asset outside report asset root")
        return resolved

    def _temp_path(
        self,
        implementation_id: str,
        folder: str,
        image_id: str,
        extension: str,
    ) -> Path:
        return self.root / "_tmp" / implementation_id / folder / f"{image_id}.{extension}"

    def _thumbnail_bytes(self, image_bytes: bytes) -> bytes:
        return image_bytes

    def _remove_tree(self, target: Path) -> None:
        if not target.exists():
            return
        root = self.root.resolve()
        resolved = target.resolve()
        if resolved != root and root not in resolved.parents:
            raise RuntimeError("refusing to clean figure assets outside report asset root")
        if resolved.is_file() or resolved.is_symlink():
            resolved.unlink()
            return
        for child in sorted(resolved.rglob("*"), key=lambda path: len(path.parts), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        resolved.rmdir()

    def _remove_empty_dirs(self, target: Path) -> None:
        if not target.exists():
            return
        for child in sorted(target.rglob("*"), key=lambda path: len(path.parts), reverse=True):
            if child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    pass
        try:
            target.rmdir()
        except OSError:
            pass


class FilesystemAnalysisResourceCleaner:
    artifact_kinds = ("pages", "chunks", "chroma", "report_tmp", "figures")

    def __init__(self, root: Path):
        self.root = root

    def cleanup_run(self, implementation_id: str) -> None:
        for artifact_kind in self.artifact_kinds:
            self._remove_tree(self.root / artifact_kind / implementation_id)

    def _remove_tree(self, target: Path) -> None:
        if not target.exists():
            return

        root = self.root.resolve()
        resolved = target.resolve()
        if resolved != root and root not in resolved.parents:
            raise RuntimeError("refusing to clean path outside analysis artifact root")

        if resolved.is_file() or resolved.is_symlink():
            resolved.unlink()
            return

        for child in sorted(resolved.rglob("*"), key=lambda path: len(path.parts), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        resolved.rmdir()


@dataclass(frozen=True)
class AnalysisStartResult:
    run: AnalysisRun
    result: AnalysisResult | None


class MdaAnalysisService:
    def __init__(
        self,
        *,
        extractor: PdfTextExtractor,
        outline_generator: MdaOutlineGenerator | None = None,
        qa_indexer: QaIndexer | None = None,
        figure_visual_analyzer: FigureVisualAnalyzer | None = None,
        figure_asset_store: FigureAssetStore | None = None,
        resource_cleaner: AnalysisResourceCleaner | None = None,
        analysis_run_lifecycle: AnalysisRunLifecycle | None = None,
    ):
        self.extractor = extractor
        self.outline_generator = outline_generator or ExtractiveMdaOutlineGenerator()
        self.qa_indexer = qa_indexer or NoopQaIndexer()
        self.figure_visual_analyzer = (
            figure_visual_analyzer
            or build_default_figure_visual_analyzer()
            or UnavailableFigureVisualAnalyzer()
        )
        self.figure_asset_store = figure_asset_store or FilesystemFigureAssetStore(
            Path("backend/data/report_assets")
        )
        self.resource_cleaner = resource_cleaner or FilesystemAnalysisResourceCleaner(
            Path("backend/data/analysis_artifacts")
        )
        self.analysis_run_lifecycle = analysis_run_lifecycle or AnalysisRunLifecycle(
            resource_cleaner=self.resource_cleaner,
            figure_asset_store=self.figure_asset_store,
        )
        self.execution = ManagementDiscussionAnalysisExecution(
            extractor=self.extractor,
            outline_generator=self.outline_generator,
            qa_indexer=self.qa_indexer,
            figure_visual_analyzer=self.figure_visual_analyzer,
            figure_asset_store=self.figure_asset_store,
        )

    def start_analysis(
        self,
        session: Session,
        *,
        file_version_id: int,
        concurrency_limit: int,
    ) -> AnalysisStartResult:
        file_version, run = self._lifecycle().begin_analysis(
            session,
            file_version_id=file_version_id,
            concurrency_limit=concurrency_limit,
        )

        try:
            execution_result = self.execution.execute(
                session,
                file_version=file_version,
                run=run,
                advance_stage=lambda stage, status: self._lifecycle().advance_run(
                    session,
                    run,
                    stage=stage,
                    status=status,
                ),
                ensure_not_stopped=lambda: self._ensure_not_stopped(session, run),
            )
            self._ensure_not_stopped(session, run)
            self._lifecycle().mark_run_ready(session, run)
            result = self._lifecycle().persist_completed_result(
                session,
                run=run,
                result=execution_result.result,
            )
            return AnalysisStartResult(run=run, result=result)
        except AnalysisStopped:
            self._lifecycle().resolve_start_stopped(session, run)
            return AnalysisStartResult(run=run, result=None)
        except BusinessError as exc:
            if self._lifecycle().resolve_start_business_error(session, run=run, error=exc):
                return AnalysisStartResult(run=run, result=None)
            raise

    def stop_analysis(self, session: Session, *, file_version_id: int) -> AnalysisRun:
        return self._lifecycle().stop_analysis(
            session,
            file_version_id=file_version_id,
        )

    def delete_analysis_result(self, session: Session, *, file_version_id: int) -> AnalysisRun:
        run = self._lifecycle().delete_current_result(
            session,
            file_version_id=file_version_id,
        )
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise BusinessError("DELETE_ANALYSIS_RESULT_FAILED") from exc
        if run is None:
            raise BusinessError("ANALYSIS_RESULT_NOT_FOUND")
        return run

    def _ensure_not_stopped(self, session: Session, run: AnalysisRun) -> None:
        session.refresh(run)
        if run.status == "stopped":
            raise AnalysisStopped

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


def _safe_image_extension(image_extension: str) -> str:
    extension = image_extension.lower().lstrip(".")
    if extension in {"png", "jpg", "jpeg", "gif", "webp"}:
        return extension
    return "png"
