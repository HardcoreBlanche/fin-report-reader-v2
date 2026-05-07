from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.errors import BusinessError
from backend.app.models import AnalysisResult, AnalysisRun, FileVersion
from backend.app.pdf_extraction import PdfReadError, PdfTextExtractor


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

        return {
            "summary": [f"{sentence.rstrip('。')}。" for sentence in summary_source[:3]],
            "analysis_sections": [{"title": "经营情况", "points": points}],
        }


class NoopQaIndexer:
    def build_index(self, implementation_id: str, evidence_package: dict) -> tuple[bool, str | None]:
        return True, None


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
        resource_cleaner: AnalysisResourceCleaner | None = None,
    ):
        self.extractor = extractor
        self.outline_generator = outline_generator or ExtractiveMdaOutlineGenerator()
        self.qa_indexer = qa_indexer or NoopQaIndexer()
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
            self._advance(run, "building_qa_index")
            session.commit()
            self._ensure_not_stopped(session, run)
            qa_available, qa_unavailable_reason = self.qa_indexer.build_index(
                run.implementation_id,
                evidence_package,
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
            session.commit()
            return AnalysisStartResult(run=run, result=result)
        except AnalysisStopped:
            session.commit()
            return AnalysisStartResult(run=run, result=None)
        except BusinessError as exc:
            session.refresh(run)
            if run.status == "stopped":
                session.commit()
                return AnalysisStartResult(run=run, result=None)
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
            pages = self.extractor.extract_text(content).pages
        except (OSError, PdfReadError) as exc:
            raise BusinessError("MD_A_TEXT_EXTRACTION_FAILED") from exc

        located = locate_mda_section(pages)
        evidence_package = build_text_evidence_package(located, implementation_id)
        if not evidence_package["text_spans"]:
            raise BusinessError("MD_A_TEXT_EXTRACTION_FAILED")
        return evidence_package

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
    current_section = source_sections[0]
    next_section_number = 2

    for page, text in located.pages:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
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

    return {
        "implementation_id": implementation_id,
        "source_sections": source_sections,
        "text_spans": text_spans,
        "tables": [],
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
    analysis_sections = []
    for section in structured_outline.get("analysis_sections", []):
        analysis_sections.append(
            {
                "title": section["title"],
                "points": [
                    {
                        **point,
                        "evidence": [
                            _enrich_evidence(evidence, text_span_index)
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
            invalid_table = True
            errors.append(f"unknown table_id {evidence.get('table_id')}")
        elif content_type == "figure_summary":
            invalid_figure = True
            errors.append(f"unknown image_id {evidence.get('image_id')}")
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


def _enrich_evidence(evidence: dict, text_span_index: dict[str, dict]) -> dict:
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
