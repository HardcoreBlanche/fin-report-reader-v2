from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.errors import BusinessError
from backend.app.models import AnalysisResult, AnalysisRun, FileVersion
from backend.app.pdf_extraction import PdfFigureCandidate, PdfReadError, PdfTextExtractor


ANALYSIS_STAGES = [
    "locating_section",
    "extracting_content",
    "analyzing_figures",
    "generating_report",
    "building_qa_index",
    "completed",
]
ACTIVE_ANALYSIS_STATUSES = {"parsing", "generating"}
MDA_TITLE = "管理层讨论与分析"


class AnalysisStopped(Exception):
    """Raised inside the orchestrator when a stop request has reached the run."""


class MdaOutlineGenerator(Protocol):
    prompt_version: str

    def generate(
        self,
        evidence_package: dict,
        validation_errors: list[str] | None = None,
    ) -> dict:
        """Generate a structured MDA outline from a text-only evidence package."""


class QaIndexer(Protocol):
    def build_index(self, implementation_id: str, evidence_package: dict) -> tuple[bool, str | None]:
        """Build the run-scoped QA index and return availability metadata."""


class FigureVisualAnalyzer(Protocol):
    prompt_version: str

    def is_available(self) -> bool:
        """Return whether visual-model analysis can be used for MDA figures."""

    def summarize(self, candidate: PdfFigureCandidate) -> dict:
        """Classify and summarize one pre-filtered figure candidate."""


class FigureAssetStore(Protocol):
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
        """Persist temporary original and presentation metadata for a figure."""

    def promote_run_assets(self, implementation_id: str) -> None:
        """Promote prepared temporary assets into the official report asset namespace."""

    def cleanup_run(self, implementation_id: str) -> None:
        """Remove temporary and official assets for one run."""

    def resolve_asset(self, implementation_id: str, storage_key: str) -> Path:
        """Resolve a stored logical asset key to a local path."""


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


@dataclass(frozen=True)
class _LocatedMdaSection:
    pages: list[tuple[int, str]]
    locator_evidence: list[dict]
    start_page: int
    end_page: int


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
    ):
        self.extractor = extractor
        self.outline_generator = outline_generator or ExtractiveMdaOutlineGenerator()
        self.qa_indexer = qa_indexer or NoopQaIndexer()
        self.figure_visual_analyzer = figure_visual_analyzer or UnavailableFigureVisualAnalyzer()
        self.figure_asset_store = figure_asset_store or FilesystemFigureAssetStore(
            Path("backend/data/report_assets")
        )
        self.resource_cleaner = resource_cleaner or FilesystemAnalysisResourceCleaner(
            Path("backend/data/analysis_artifacts")
        )

    def start_analysis(
        self,
        session: Session,
        *,
        file_version_id: int,
        concurrency_limit: int,
    ) -> AnalysisStartResult:
        file_version = session.get(FileVersion, file_version_id)
        if file_version is None or file_version.is_deleted:
            raise BusinessError("FILE_VERSION_NOT_FOUND")

        current_result = session.scalar(
            select(AnalysisResult).where(
                AnalysisResult.file_version_id == file_version_id,
                AnalysisResult.is_current.is_(True),
            )
        )
        if current_result is not None:
            raise BusinessError("ANALYSIS_RESULT_ALREADY_EXISTS")

        active_for_file_version = session.scalar(
            select(AnalysisRun).where(
                AnalysisRun.file_version_id == file_version_id,
                AnalysisRun.status.in_(ACTIVE_ANALYSIS_STATUSES),
            )
        )
        if active_for_file_version is not None:
            raise BusinessError("ANALYSIS_ALREADY_IN_PROGRESS")

        active_count = session.scalar(
            select(func.count(AnalysisRun.id)).where(
                AnalysisRun.status.in_(ACTIVE_ANALYSIS_STATUSES)
            )
        )
        if int(active_count or 0) >= concurrency_limit:
            raise BusinessError("ANALYSIS_CONCURRENCY_LIMIT_REACHED")

        run = AnalysisRun(
            file_version_id=file_version_id,
            implementation_id=f"analysis_run_{uuid4().hex}",
            status="parsing",
            stage="locating_section",
            stage_history=["locating_section"],
        )
        session.add(run)
        session.flush()
        session.commit()

        try:
            self._ensure_not_stopped(session, run)
            evidence_package = self._extract_evidence_package(file_version, run.implementation_id)
            self._ensure_not_stopped(session, run)
            self._advance(run, "extracting_content")
            session.commit()
            self._ensure_not_stopped(session, run)
            self._advance(run, "analyzing_figures", status="generating")
            session.commit()
            self._ensure_not_stopped(session, run)
            self._advance(run, "generating_report")
            session.commit()
            structured_outline = self._generate_validated_outline(session, run, evidence_package)
            self._ensure_not_stopped(session, run)
            try:
                self.figure_asset_store.promote_run_assets(run.implementation_id)
            except Exception as exc:
                self.figure_asset_store.cleanup_run(run.implementation_id)
                raise BusinessError("REPORT_ASSET_COMMIT_FAILED") from exc
            self._advance(run, "building_qa_index")
            session.commit()
            self._ensure_not_stopped(session, run)
            indexing_package = {
                **evidence_package,
                "qa_index_documents": build_qa_index_documents(
                    file_version_id=file_version_id,
                    analysis_run_id=run.id,
                    evidence_package=evidence_package,
                ),
            }
            qa_available, qa_unavailable_reason = self.qa_indexer.build_index(
                run.implementation_id,
                indexing_package,
            )
            self._ensure_not_stopped(session, run)
            run.status = "ready"
            self._advance(run, "completed")
            result = AnalysisResult(
                file_version_id=file_version_id,
                analysis_run_id=run.id,
                prompt_version=self.outline_generator.prompt_version,
                evidence_package=evidence_package,
                structured_outline=structured_outline,
                qa_available=qa_available,
                qa_unavailable_reason=qa_unavailable_reason,
            )
            session.add(result)
            try:
                session.commit()
            except Exception as exc:
                session.rollback()
                self.figure_asset_store.cleanup_run(run.implementation_id)
                self.resource_cleaner.cleanup_run(run.implementation_id)
                run = session.get(AnalysisRun, run.id)
                if run is not None:
                    run.status = "failed"
                    run.error_code = "ANALYSIS_RESULT_SAVE_FAILED"
                    run.error_message = "分析报告保存失败"
                    session.commit()
                raise BusinessError("ANALYSIS_RESULT_SAVE_FAILED") from exc
            return AnalysisStartResult(run=run, result=result)
        except AnalysisStopped:
            self.figure_asset_store.cleanup_run(run.implementation_id)
            session.commit()
            return AnalysisStartResult(run=run, result=None)
        except BusinessError as exc:
            session.refresh(run)
            if run.status == "stopped":
                self.figure_asset_store.cleanup_run(run.implementation_id)
                session.commit()
                return AnalysisStartResult(run=run, result=None)
            self.figure_asset_store.cleanup_run(run.implementation_id)
            run.status = "failed"
            run.error_code = exc.spec.error_code
            run.error_message = exc.spec.message
            session.commit()
            raise

    def stop_analysis(self, session: Session, *, file_version_id: int) -> AnalysisRun:
        file_version = session.get(FileVersion, file_version_id)
        if file_version is None or file_version.is_deleted:
            raise BusinessError("FILE_VERSION_NOT_FOUND")

        run = session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.file_version_id == file_version_id,
                AnalysisRun.status.in_(ACTIVE_ANALYSIS_STATUSES),
            )
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        )
        if run is None:
            raise BusinessError("STOP_ANALYSIS_FAILED")

        run.status = "stopped"
        run.error_code = None
        run.error_message = None
        session.commit()

        try:
            self.resource_cleaner.cleanup_run(run.implementation_id)
            self.figure_asset_store.cleanup_run(run.implementation_id)
        except Exception as exc:
            run.status = "failed"
            run.error_code = "STOP_ANALYSIS_CLEANUP_FAILED"
            run.error_message = "停止分析时清理中间结果失败"
            session.commit()
            raise BusinessError("STOP_ANALYSIS_CLEANUP_FAILED") from exc

        return run

    def delete_analysis_result(self, session: Session, *, file_version_id: int) -> AnalysisRun:
        file_version = session.get(FileVersion, file_version_id)
        if file_version is None or file_version.is_deleted:
            raise BusinessError("FILE_VERSION_NOT_FOUND")

        result = session.scalar(
            select(AnalysisResult).where(
                AnalysisResult.file_version_id == file_version_id,
                AnalysisResult.is_current.is_(True),
            )
        )
        if result is None:
            raise BusinessError("ANALYSIS_RESULT_NOT_FOUND")

        run = result.analysis_run
        try:
            self.resource_cleaner.cleanup_run(run.implementation_id)
            self.figure_asset_store.cleanup_run(run.implementation_id)
        except Exception as exc:
            raise BusinessError("DELETE_ANALYSIS_ARTIFACTS_FAILED") from exc

        run.status = "result_deleted"
        run.error_code = None
        run.error_message = None
        session.delete(result)
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            raise BusinessError("DELETE_ANALYSIS_RESULT_FAILED") from exc
        return run

    def _extract_evidence_package(self, file_version: FileVersion, implementation_id: str) -> dict:
        try:
            content = Path(file_version.storage_path).read_bytes()
            document = self.extractor.extract_text(content)
            pages = document.pages
        except (OSError, PdfReadError) as exc:
            raise BusinessError("MD_A_TEXT_EXTRACTION_FAILED") from exc

        located = locate_mda_section(pages)
        evidence_package = build_text_evidence_package(located, implementation_id)
        figure_candidates = [
            candidate
            for candidate in document.figure_candidates
            if located.start_page <= candidate.page < located.end_page
        ]
        evidence_package["figures"] = self._extract_figure_evidence(
            figure_candidates,
            evidence_package,
            implementation_id,
        )
        if not evidence_package["text_spans"] and not evidence_package["tables"]:
            raise BusinessError("MD_A_TEXT_EXTRACTION_FAILED")
        return evidence_package

    def _extract_figure_evidence(
        self,
        candidates: list[PdfFigureCandidate],
        evidence_package: dict,
        implementation_id: str,
    ) -> list[dict]:
        filtered_candidates = filter_mda_figure_candidates(candidates)
        if not filtered_candidates:
            return []
        if not self.figure_visual_analyzer.is_available():
            raise BusinessError("VISION_MODEL_UNAVAILABLE")

        figures: list[dict] = []
        for candidate in filtered_candidates:
            try:
                visual_summary = self.figure_visual_analyzer.summarize(candidate)
            except Exception as exc:
                raise BusinessError("CHART_ANALYSIS_FAILED") from exc
            if not visual_summary.get("is_informational", True):
                continue
            summary = str(visual_summary.get("summary") or "").strip()
            if not summary:
                raise BusinessError("CHART_ANALYSIS_FAILED")

            image_id = f"image_{len(figures) + 1}"
            try:
                assets = self.figure_asset_store.prepare_figure_asset(
                    implementation_id=implementation_id,
                    image_id=image_id,
                    image_bytes=candidate.image_bytes,
                    image_extension=candidate.image_extension,
                    width=candidate.width,
                    height=candidate.height,
                )
            except Exception as exc:
                raise BusinessError("FIGURE_ASSET_SAVE_FAILED") from exc

            source_section = _source_section_for_page(
                evidence_package["source_sections"],
                candidate.page,
            )
            source_section["image_ids"].append(image_id)
            relevance = str(visual_summary.get("relevance") or "high").lower()
            figures.append(
                {
                    "image_id": image_id,
                    "source_section_id": source_section["source_section_id"],
                    "page": candidate.page,
                    "page_label": f"PDF 第 {candidate.page} 页",
                    "bbox": candidate.bbox,
                    "title": candidate.title,
                    "caption": candidate.caption,
                    "summary": summary,
                    "classification_reason": visual_summary.get("classification_reason"),
                    "relevance": relevance,
                    "relevance_reason": visual_summary.get("relevance_reason"),
                    "is_relevant_to_analysis": _is_relevant_figure(relevance, visual_summary),
                    "original": assets["original"],
                    "thumbnail": assets.get("thumbnail"),
                    "prompt_version": self.figure_visual_analyzer.prompt_version,
                }
            )
        return figures

    def _generate_validated_outline(
        self,
        session: Session,
        run: AnalysisRun,
        evidence_package: dict,
    ) -> dict:
        self._ensure_not_stopped(session, run)
        first_output = self.outline_generator.generate(evidence_package)
        self._ensure_not_stopped(session, run)
        first_validation = validate_structured_outline(first_output, evidence_package)
        if first_validation.is_valid:
            return first_validation.outline
        if first_validation.error_code == "ANALYSIS_OUTPUT_NO_VALID_EVIDENCE":
            raise BusinessError(first_validation.error_code)

        self._ensure_not_stopped(session, run)
        retried_output = self.outline_generator.generate(
            evidence_package,
            validation_errors=first_validation.errors,
        )
        self._ensure_not_stopped(session, run)
        retried_validation = validate_structured_outline(retried_output, evidence_package)
        if retried_validation.is_valid:
            return retried_validation.outline
        raise BusinessError(retried_validation.error_code)

    def _ensure_not_stopped(self, session: Session, run: AnalysisRun) -> None:
        session.refresh(run)
        if run.status == "stopped":
            raise AnalysisStopped

    def _advance(self, run: AnalysisRun, stage: str, status: str | None = None) -> None:
        if status is not None:
            run.status = status
        run.stage = stage
        history = list(run.stage_history or [])
        if not history or history[-1] != stage:
            history.append(stage)
        run.stage_history = history


@dataclass(frozen=True)
class OutlineValidation:
    is_valid: bool
    outline: dict
    errors: list[str]
    error_code: str


def locate_mda_section(pages: list[str]) -> _LocatedMdaSection:
    toc_page_index, toc_start_page = _find_toc_mda_start(pages)
    locator_evidence: list[dict] = []
    if toc_start_page is not None:
        start_index = toc_start_page - 1
        if start_index < 0 or start_index >= len(pages) or not _contains_mda_heading(pages[start_index]):
            raise BusinessError("MD_A_SECTION_START_UNVERIFIED")
        locator_evidence.append(
            {
                "kind": "table_of_contents",
                "page": toc_page_index + 1 if toc_page_index is not None else None,
                "page_label": f"PDF 第 {toc_page_index + 1} 页" if toc_page_index is not None else None,
                "text": MDA_TITLE,
            }
        )
    else:
        start_index = _find_mda_heading_page(pages)
        if start_index is None:
            raise BusinessError("MD_A_SECTION_NOT_FOUND")

    collected_pages: list[tuple[int, str]] = []
    start_seen = False
    end_page: int | None = None
    end_heading_text: str | None = None

    for page_index in range(start_index, len(pages)):
        retained_lines: list[str] = []
        for raw_line in pages[page_index].splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if not start_seen:
                if _is_mda_heading(line):
                    start_seen = True
                    locator_evidence.append(
                        {
                            "kind": "section_start",
                            "page": page_index + 1,
                            "page_label": f"PDF 第 {page_index + 1} 页",
                            "text": line,
                        }
                    )
                continue
            if _is_same_level_section_heading(line):
                end_page = page_index + 1
                end_heading_text = line
                break
            retained_lines.append(line)

        if retained_lines:
            collected_pages.append((page_index + 1, "\n".join(retained_lines)))
        if end_page is not None:
            break

    if end_page is None:
        raise BusinessError("MD_A_SECTION_END_NOT_FOUND")

    locator_evidence.append(
        {
            "kind": "section_end",
            "page": end_page,
            "page_label": f"PDF 第 {end_page} 页",
            "text": end_heading_text,
        }
    )
    return _LocatedMdaSection(
        pages=collected_pages,
        locator_evidence=locator_evidence,
        start_page=start_index + 1,
        end_page=end_page,
    )


def build_text_evidence_package(located: _LocatedMdaSection, implementation_id: str) -> dict:
    source_sections: list[dict] = [
        {
            "source_section_id": "source_section_1",
            "title": MDA_TITLE,
            "level": 1,
            "page_start": located.start_page,
            "page_end": located.end_page,
            "text_span_ids": [],
            "table_ids": [],
            "image_ids": [],
            "children": [],
        }
    ]
    text_spans: list[dict] = []
    tables: list[dict] = []
    current_section = source_sections[0]
    next_section_number = 2

    for page, text in located.pages:
        lines = [raw_line.strip() for raw_line in text.splitlines() if raw_line.strip()]
        line_index = 0
        while line_index < len(lines):
            line = lines[line_index]
            if not line:
                line_index += 1
                continue
            if _is_source_subsection_heading(line):
                current_section = {
                    "source_section_id": f"source_section_{next_section_number}",
                    "title": line,
                    "level": 2,
                    "page_start": page,
                    "page_end": page,
                    "text_span_ids": [],
                    "table_ids": [],
                    "image_ids": [],
                    "children": [],
                }
                next_section_number += 1
                source_sections[0]["children"].append(current_section)
                line_index += 1
                continue
            if _table_title_from_line(line) is not None:
                table, consumed = _parse_table_block(
                    lines=lines[line_index:],
                    page=page,
                    source_section=current_section,
                    table_id=f"table_{len(tables) + 1}",
                )
                tables.append(table)
                current_section["page_end"] = page
                current_section["table_ids"].append(table["table_id"])
                line_index += consumed
                continue

            text_span_id = f"text_span_{len(text_spans) + 1}"
            current_section["page_end"] = page
            current_section["text_span_ids"].append(text_span_id)
            text_spans.append(
                {
                    "text_span_id": text_span_id,
                    "source_section_id": current_section["source_section_id"],
                    "page": page,
                    "page_label": f"PDF 第 {page} 页",
                    "text": line,
                }
            )
            line_index += 1

    return {
        "implementation_id": implementation_id,
        "source_sections": source_sections,
        "text_spans": text_spans,
        "tables": tables,
        "figures": [],
        "section_location_evidence": located.locator_evidence,
    }


def validate_structured_outline(output: dict, evidence_package: dict) -> OutlineValidation:
    errors: list[str] = []
    if not isinstance(output, dict):
        return _invalid("ANALYSIS_OUTPUT_VALIDATION_FAILED", ["output must be an object"])

    summary = output.get("summary")
    if not isinstance(summary, list) or not 3 <= len(summary) <= 5 or not all(
        isinstance(item, str) and item.strip() for item in summary
    ):
        errors.append("summary must contain 3 to 5 non-empty sentences")

    raw_sections = output.get("analysis_sections")
    if not isinstance(raw_sections, list):
        errors.append("analysis_sections must be a list")
        raw_sections = []

    text_spans = {
        span["text_span_id"]: span for span in evidence_package.get("text_spans", [])
    }
    tables = {table["table_id"]: table for table in evidence_package.get("tables", [])}
    figures = {figure["image_id"]: figure for figure in evidence_package.get("figures", [])}
    source_section_ids = {
        section_id
        for section in evidence_package.get("source_sections", [])
        for section_id in _walk_source_section_ids(section)
    }
    valid_sections: list[dict] = []
    invalid_table = False
    invalid_figure = False
    schema_error = bool(errors)

    for raw_section in raw_sections:
        if not isinstance(raw_section, dict) or not isinstance(raw_section.get("title"), str):
            schema_error = True
            errors.append("analysis section title is required")
            continue
        raw_points = raw_section.get("points")
        if not isinstance(raw_points, list):
            schema_error = True
            errors.append(f"{raw_section.get('title')} points must be a list")
            continue

        valid_points: list[dict] = []
        for raw_point in raw_points:
            point, point_errors, point_invalid_table, point_invalid_figure = _validate_point(
                raw_point,
                text_spans,
                tables,
                figures,
                source_section_ids,
            )
            invalid_table = invalid_table or point_invalid_table
            invalid_figure = invalid_figure or point_invalid_figure
            if point_errors:
                errors.extend(point_errors)
                schema_error = schema_error or not (point_invalid_table or point_invalid_figure)
                continue
            if point is not None:
                valid_points.append(point)

        if valid_points:
            valid_sections.append({"title": raw_section["title"].strip(), "points": valid_points})

    if invalid_table and invalid_figure:
        return _invalid("ANALYSIS_OUTPUT_INVALID_ASSET_REFERENCE", errors)
    if invalid_table:
        return _invalid("ANALYSIS_OUTPUT_INVALID_TABLE_REFERENCE", errors)
    if invalid_figure:
        return _invalid("ANALYSIS_OUTPUT_INVALID_FIGURE_REFERENCE", errors)
    if schema_error:
        return _invalid("ANALYSIS_OUTPUT_VALIDATION_FAILED", errors)
    if not valid_sections:
        return _invalid("ANALYSIS_OUTPUT_NO_VALID_EVIDENCE", errors)

    return OutlineValidation(
        is_valid=True,
        outline={
            "summary": [item.strip() for item in summary],
            "source_sections": evidence_package["source_sections"],
            "analysis_sections": valid_sections,
        },
        errors=[],
        error_code="",
    )


def report_detail_from_result(result: AnalysisResult) -> dict:
    evidence_package = result.evidence_package
    structured_outline = result.structured_outline
    text_span_index = {
        span["text_span_id"]: span for span in evidence_package.get("text_spans", [])
    }
    table_index = {
        table["table_id"]: _table_metadata_for_report(table, result.file_version_id)
        for table in evidence_package.get("tables", [])
    }
    figure_index = {
        figure["image_id"]: _figure_metadata_for_report(figure, result.file_version_id)
        for figure in evidence_package.get("figures", [])
    }
    analysis_sections = []
    for section in structured_outline.get("analysis_sections", []):
        analysis_sections.append(
            {
                "title": section["title"],
                "points": [
                    {
                        **point,
                        "evidence": [
                            _enrich_evidence(evidence, text_span_index, table_index, figure_index)
                            for evidence in point.get("evidence", [])
                        ],
                    }
                    for point in section.get("points", [])
                ],
            }
        )

    return {
        "file_version_id": result.file_version_id,
        "analysis_run_id": result.analysis_run_id,
        "title": MDA_TITLE,
        "prompt_version": result.prompt_version,
        "summary": structured_outline.get("summary", []),
        "source_sections": evidence_package.get("source_sections", []),
        "text_span_index": text_span_index,
        "table_index": table_index,
        "figure_index": figure_index,
        "other_figures": [
            figure
            for figure in figure_index.values()
            if not figure.get("is_relevant_to_analysis", True)
        ],
        "analysis_sections": analysis_sections,
        "qa_available": result.qa_available,
        "qa_unavailable_reason": result.qa_unavailable_reason,
        "labels": {
            "source_tree": "章节结构",
            "analysis_report": "分析报告",
            "qa_index": "问答索引",
            "evidence_package": "证据包",
        },
    }


def _validate_point(
    raw_point: object,
    text_spans: dict[str, dict],
    tables: dict[str, dict],
    figures: dict[str, dict],
    source_section_ids: set[str],
) -> tuple[dict | None, list[str], bool, bool]:
    if not isinstance(raw_point, dict) or not isinstance(raw_point.get("text"), str):
        return None, ["analysis point text is required"], False, False

    raw_evidence = raw_point.get("evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        return None, [], False, False

    valid_evidence: list[dict] = []
    errors: list[str] = []
    invalid_table = False
    invalid_figure = False
    for evidence in raw_evidence:
        if not isinstance(evidence, dict):
            errors.append("evidence item must be an object")
            continue
        content_type = evidence.get("content_type")
        if content_type == "text":
            text_span_id = evidence.get("text_span_id")
            if text_span_id not in text_spans:
                errors.append(f"unknown text_span_id {text_span_id}")
                continue
            span = text_spans[text_span_id]
            source_section_id = evidence.get("source_section_id") or span["source_section_id"]
            if source_section_id not in source_section_ids:
                errors.append(f"unknown source_section_id {source_section_id}")
                continue
            valid_evidence.append(
                {
                    "content_type": "text",
                    "source_section_id": source_section_id,
                    "text_span_id": text_span_id,
                    "page": span["page"],
                    "page_label": span["page_label"],
                    "evidence_text": str(evidence.get("evidence_text") or span["text"]),
                }
            )
        elif content_type == "table":
            table_id = evidence.get("table_id")
            table = tables.get(table_id)
            if table is None:
                invalid_table = True
                errors.append(f"unknown table_id {table_id}")
                continue
            source_section_id = evidence.get("source_section_id") or table["source_section_id"]
            if source_section_id not in source_section_ids:
                invalid_table = True
                errors.append(f"unknown source_section_id {source_section_id}")
                continue
            if source_section_id != table["source_section_id"]:
                invalid_table = True
                errors.append(f"table {table_id} belongs to {table['source_section_id']}")
                continue
            valid_evidence.append(
                {
                    "content_type": "table",
                    "source_section_id": source_section_id,
                    "table_id": table_id,
                    "page": table["page"],
                    "page_label": table["page_label"],
                    "evidence_text": str(evidence.get("evidence_text") or table["summary"]),
                }
            )
        elif content_type == "figure_summary":
            image_id = evidence.get("image_id")
            figure = figures.get(image_id)
            if figure is None:
                invalid_figure = True
                errors.append(f"unknown image_id {image_id}")
                continue
            if not figure.get("is_relevant_to_analysis", True):
                continue
            source_section_id = evidence.get("source_section_id") or figure["source_section_id"]
            if source_section_id not in source_section_ids:
                invalid_figure = True
                errors.append(f"unknown source_section_id {source_section_id}")
                continue
            if source_section_id != figure["source_section_id"]:
                invalid_figure = True
                errors.append(f"figure {image_id} belongs to {figure['source_section_id']}")
                continue
            valid_evidence.append(
                {
                    "content_type": "figure_summary",
                    "source_section_id": source_section_id,
                    "image_id": image_id,
                    "page": figure["page"],
                    "page_label": figure["page_label"],
                    "evidence_text": str(evidence.get("evidence_text") or figure["summary"]),
                }
            )
        else:
            errors.append(f"unsupported evidence content_type {content_type}")

    if errors:
        return None, errors, invalid_table, invalid_figure
    if not valid_evidence:
        return None, [], False, False

    source_ids = sorted({item["source_section_id"] for item in valid_evidence})
    return (
        {
            "text": raw_point["text"].strip(),
            "source_section_ids": source_ids,
            "evidence": valid_evidence,
        },
        [],
        False,
        False,
    )


def _enrich_evidence(
    evidence: dict,
    text_span_index: dict[str, dict],
    table_index: dict[str, dict],
    figure_index: dict[str, dict],
) -> dict:
    if evidence.get("content_type") == "table":
        table = table_index.get(evidence.get("table_id"))
        if table is None:
            return evidence
        return {
            **evidence,
            "page": table["page"],
            "page_label": table["page_label"],
        }
    if evidence.get("content_type") == "figure_summary":
        figure = figure_index.get(evidence.get("image_id"))
        if figure is None:
            return evidence
        return {
            **evidence,
            "page": figure["page"],
            "page_label": figure["page_label"],
            "thumb_url": figure["thumb_url"],
            "original_url": figure["original_url"],
        }
    if evidence.get("content_type") != "text":
        return evidence
    span = text_span_index.get(evidence.get("text_span_id"))
    if span is None:
        return evidence
    return {
        **evidence,
        "page": span["page"],
        "page_label": span["page_label"],
    }


def _invalid(error_code: str, errors: list[str]) -> OutlineValidation:
    return OutlineValidation(is_valid=False, outline={}, errors=errors, error_code=error_code)


def table_asset_from_result(result: AnalysisResult, table_id: str) -> dict | None:
    for table in result.evidence_package.get("tables", []):
        if table.get("table_id") == table_id:
            return table
    return None


def figure_asset_from_result(result: AnalysisResult, image_id: str) -> dict | None:
    for figure in result.evidence_package.get("figures", []):
        if figure.get("image_id") == image_id:
            return figure
    return None


def build_qa_index_documents(
    *,
    file_version_id: int,
    analysis_run_id: int,
    evidence_package: dict,
) -> list[dict]:
    section_titles = _source_section_titles(evidence_package.get("source_sections", []))
    documents: list[dict] = []
    for span in evidence_package.get("text_spans", []):
        documents.append(
            {
                "doc_id": span["text_span_id"],
                "text": span["text"],
                "metadata": {
                    "file_version_id": file_version_id,
                    "analysis_run_id": analysis_run_id,
                    "section": "ManagementDiscussionAnalysisSection",
                    "source_section_id": span["source_section_id"],
                    "subsection_title": section_titles.get(span["source_section_id"], MDA_TITLE),
                    "page": span["page"],
                    "content_type": "text",
                },
            }
        )
    for table in evidence_package.get("tables", []):
        documents.append(
            {
                "doc_id": table["table_id"],
                "text": _table_text_for_index(table),
                "metadata": {
                    "file_version_id": file_version_id,
                    "analysis_run_id": analysis_run_id,
                    "section": "ManagementDiscussionAnalysisSection",
                    "source_section_id": table["source_section_id"],
                    "subsection_title": section_titles.get(table["source_section_id"], MDA_TITLE),
                    "page": table["page"],
                    "content_type": "table",
                },
            }
        )
    for figure in evidence_package.get("figures", []):
        documents.append(
            {
                "doc_id": figure["image_id"],
                "text": _figure_text_for_index(figure),
                "metadata": {
                    "file_version_id": file_version_id,
                    "analysis_run_id": analysis_run_id,
                    "section": "ManagementDiscussionAnalysisSection",
                    "source_section_id": figure["source_section_id"],
                    "subsection_title": section_titles.get(
                        figure["source_section_id"],
                        MDA_TITLE,
                    ),
                    "page": figure["page"],
                    "content_type": "figure_summary",
                },
            }
        )
    return documents


def _parse_table_block(
    *,
    lines: list[str],
    page: int,
    source_section: dict,
    table_id: str,
) -> tuple[dict, int]:
    title = _table_title_from_line(lines[0])
    if title is None or len(lines) < 2 or not _is_pipe_table_row(lines[1]):
        raise BusinessError("TABLE_ANALYSIS_FAILED")

    columns = _parse_pipe_table_row(lines[1])
    if len(columns) < 2:
        raise BusinessError("TABLE_ANALYSIS_FAILED")

    line_index = 2
    if line_index < len(lines) and _is_pipe_separator_row(lines[line_index]):
        line_index += 1

    rows: list[dict[str, str]] = []
    while line_index < len(lines) and _is_pipe_table_row(lines[line_index]):
        values = _parse_pipe_table_row(lines[line_index])
        if len(values) != len(columns):
            raise BusinessError("TABLE_ANALYSIS_FAILED")
        rows.append(dict(zip(columns, values, strict=True)))
        line_index += 1

    if not rows:
        raise BusinessError("TABLE_ANALYSIS_FAILED")

    notes: list[str] = []
    while line_index < len(lines) and _is_note_line(lines[line_index]):
        notes.append(_clean_note(lines[line_index]))
        line_index += 1

    summary = f"{title}，共 {len(rows)} 行 {len(columns)} 列。"
    table = {
        "table_id": table_id,
        "source_section_id": source_section["source_section_id"],
        "title": title,
        "summary": summary,
        "page": page,
        "page_label": f"PDF 第 {page} 页",
        "columns": columns,
        "rows": rows,
        "notes": notes,
        "metadata": {
            "row_count": len(rows),
            "column_count": len(columns),
            "parser": "pipe_table_v1",
        },
        "source_bbox": None,
    }
    return table, line_index


def _table_metadata_for_report(table: dict, file_version_id: int) -> dict:
    return {
        "table_id": table["table_id"],
        "title": table["title"],
        "summary": table["summary"],
        "page": table["page"],
        "page_label": table["page_label"],
        "source_section_id": table["source_section_id"],
        "columns": table["columns"],
        "row_count": len(table.get("rows", [])),
        "notes": table.get("notes", []),
        "table_url": (
            f"/api/file-versions/{file_version_id}/analysis-result/tables/{table['table_id']}"
        ),
    }


def _figure_metadata_for_report(figure: dict, file_version_id: int) -> dict:
    base_url = f"/api/file-versions/{file_version_id}/analysis-result/figures/{figure['image_id']}"
    original = figure["original"]
    thumbnail = figure.get("thumbnail") or original
    return {
        "image_id": figure["image_id"],
        "source_section_id": figure["source_section_id"],
        "page": figure["page"],
        "page_label": figure["page_label"],
        "bbox": figure["bbox"],
        "title": figure.get("title"),
        "caption": figure.get("caption"),
        "summary": figure["summary"],
        "classification_reason": figure.get("classification_reason"),
        "relevance": figure.get("relevance"),
        "relevance_reason": figure.get("relevance_reason"),
        "is_relevant_to_analysis": figure.get("is_relevant_to_analysis", True),
        "original": original,
        "thumbnail": thumbnail,
        "thumb_url": f"{base_url}?variant=thumb",
        "original_url": f"{base_url}?variant=original",
    }


def _table_text_for_index(table: dict) -> str:
    lines = [
        f"表格：{table['title']}",
        f"摘要：{table['summary']}",
        f"列：{'，'.join(table['columns'])}",
    ]
    for row in table.get("rows", []):
        lines.append(" | ".join(str(row.get(column, "")) for column in table["columns"]))
    for note in table.get("notes", []):
        lines.append(f"注：{note}")
    return "\n".join(lines)


def _figure_text_for_index(figure: dict) -> str:
    lines = [f"图示：{figure.get('title') or figure['image_id']}"]
    if figure.get("caption"):
        lines.append(f"说明：{figure['caption']}")
    lines.append(f"摘要：{figure['summary']}")
    if figure.get("relevance_reason"):
        lines.append(f"相关性：{figure['relevance_reason']}")
    return "\n".join(lines)


def _source_section_titles(source_sections: list[dict]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for section in source_sections:
        titles[section["source_section_id"]] = section["title"]
        titles.update(_source_section_titles(section.get("children", [])))
    return titles


def _table_title_from_line(line: str) -> str | None:
    match = re.match(r"^(?:表格|表)\s*[:：]\s*(.+)$", line)
    if match:
        return match.group(1).strip()
    numbered = re.match(r"^表\s*\d+(?:[-－]\d+)?\s+(.+)$", line)
    if numbered:
        return numbered.group(1).strip()
    return None


def _is_pipe_table_row(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and len(_parse_pipe_table_row(line)) >= 2


def _is_pipe_separator_row(line: str) -> bool:
    cells = _parse_pipe_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells)


def _parse_pipe_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_note_line(line: str) -> bool:
    return bool(re.match(r"^注\d*[：:]", line))


def _clean_note(line: str) -> str:
    return re.sub(r"^注\d*[：:]\s*", "", line).strip()


def filter_mda_figure_candidates(candidates: list[PdfFigureCandidate]) -> list[PdfFigureCandidate]:
    decorative_roles = {
        "logo",
        "watermark",
        "header",
        "footer",
        "background",
        "icon",
        "decorative",
    }
    filtered: list[PdfFigureCandidate] = []
    for candidate in candidates:
        role = (candidate.role or "").lower()
        if role in decorative_roles:
            continue
        if candidate.occurrence_count > 1:
            continue
        if candidate.width < 80 or candidate.height < 60:
            continue
        if _is_header_or_footer_candidate(candidate):
            continue
        if _is_background_candidate(candidate):
            continue
        filtered.append(candidate)
    return filtered


def _is_header_or_footer_candidate(candidate: PdfFigureCandidate) -> bool:
    if candidate.page_height is None:
        return False
    _, top, _, bottom = candidate.bbox
    page_height = candidate.page_height
    height = bottom - top
    if height > page_height * 0.2:
        return False
    return bottom <= page_height * 0.12 or top >= page_height * 0.88


def _is_background_candidate(candidate: PdfFigureCandidate) -> bool:
    if candidate.page_width is None or candidate.page_height is None:
        return False
    left, top, right, bottom = candidate.bbox
    area = max(right - left, 0) * max(bottom - top, 0)
    page_area = candidate.page_width * candidate.page_height
    return page_area > 0 and area / page_area > 0.8


def _source_section_for_page(source_sections: list[dict], page: int) -> dict:
    best = source_sections[0]
    stack = list(source_sections)
    while stack:
        section = stack.pop()
        if section.get("page_start", page) <= page <= section.get("page_end", page):
            best = section
            stack.extend(section.get("children", []))
    return best


def _is_relevant_figure(relevance: str, visual_summary: dict) -> bool:
    explicit = visual_summary.get("is_relevant_to_analysis")
    if explicit is not None:
        return bool(explicit)
    return relevance not in {"low", "none", "irrelevant", "unrelated"}


def _safe_image_extension(image_extension: str) -> str:
    extension = image_extension.lower().lstrip(".")
    if extension in {"png", "jpg", "jpeg", "gif", "webp"}:
        return extension
    return "png"


def _find_toc_mda_start(pages: list[str]) -> tuple[int | None, int | None]:
    for index, page_text in enumerate(pages[:10]):
        if "目录" not in page_text or MDA_TITLE not in page_text:
            continue
        for line in page_text.splitlines():
            if MDA_TITLE not in line:
                continue
            match = re.search(r"(\d{1,3})\s*$", line.strip())
            if match:
                return index, int(match.group(1))
    return None, None


def _find_mda_heading_page(pages: list[str]) -> int | None:
    for index, page_text in enumerate(pages[:20]):
        if _contains_mda_heading(page_text):
            return index
    return None


def _contains_mda_heading(page_text: str) -> bool:
    return any(_is_mda_heading(line.strip()) for line in page_text.splitlines())


def _is_mda_heading(line: str) -> bool:
    return bool(re.search(r"第三节\s*管理层讨论与分析", line))


def _is_same_level_section_heading(line: str) -> bool:
    return bool(re.search(r"^第[一二三四五六七八九十]+节", line)) and not _is_mda_heading(line)


def _is_source_subsection_heading(line: str) -> bool:
    return bool(re.search(r"^[一二三四五六七八九十]+、", line) or re.search(r"^（[一二三四五六七八九十]+）", line))


def _walk_source_section_ids(section: dict) -> list[str]:
    section_ids = [section["source_section_id"]]
    for child in section.get("children", []):
        section_ids.extend(_walk_source_section_ids(child))
    return section_ids
