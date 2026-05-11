from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable
from typing import Protocol

from sqlalchemy.orm import Session

from backend.app.evidence_package import EvidencePackage, EvidencePackageBuilder, MDA_TITLE
from backend.app.evidence_package_projection import EvidencePackageProjection
from backend.app.errors import BusinessError
from backend.app.models import AnalysisResult, AnalysisRun, FileVersion
from backend.app.pdf_extraction import PdfFigureCandidate, PdfReadError, PdfTextExtractor


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


@dataclass(frozen=True)
class ManagementDiscussionAnalysisExecutionResult:
    result: AnalysisResult


@dataclass(frozen=True)
class _LocatedMdaSection:
    pages: list[tuple[int, str]]
    locator_evidence: list[dict]
    start_page: int
    end_page: int


@dataclass(frozen=True)
class OutlineValidation:
    is_valid: bool
    outline: dict
    errors: list[str]
    error_code: str


class ManagementDiscussionAnalysisExecution:
    def __init__(
        self,
        *,
        extractor: PdfTextExtractor,
        outline_generator: MdaOutlineGenerator,
        qa_indexer: QaIndexer,
        figure_visual_analyzer: FigureVisualAnalyzer,
        figure_asset_store: FigureAssetStore,
    ):
        self.extractor = extractor
        self.outline_generator = outline_generator
        self.qa_indexer = qa_indexer
        self.figure_visual_analyzer = figure_visual_analyzer
        self.figure_asset_store = figure_asset_store

    def execute(
        self,
        session: Session,
        *,
        file_version: FileVersion,
        run: AnalysisRun,
        advance_stage: Callable[[str, str | None], None],
        ensure_not_stopped: Callable[[], None],
    ) -> ManagementDiscussionAnalysisExecutionResult:
        ensure_not_stopped()
        evidence_package = self._extract_evidence_package(file_version, run.implementation_id)
        ensure_not_stopped()
        advance_stage("extracting_content", None)
        ensure_not_stopped()
        advance_stage("analyzing_figures", "generating")
        ensure_not_stopped()
        advance_stage("generating_report", None)
        structured_outline = self._generate_validated_outline(
            session,
            run,
            evidence_package,
            ensure_not_stopped=ensure_not_stopped,
        )
        ensure_not_stopped()
        try:
            self.figure_asset_store.promote_run_assets(run.implementation_id)
        except Exception as exc:
            raise BusinessError("REPORT_ASSET_COMMIT_FAILED") from exc
        advance_stage("building_qa_index", None)
        ensure_not_stopped()
        qa_available, qa_unavailable_reason = self._build_qa_index_metadata(
            evidence_package=evidence_package,
            file_version_id=file_version.id,
            analysis_run_id=run.id,
            implementation_id=run.implementation_id,
        )
        ensure_not_stopped()
        return ManagementDiscussionAnalysisExecutionResult(
            result=AnalysisResult(
                file_version_id=file_version.id,
                analysis_run_id=run.id,
                prompt_version=self.outline_generator.prompt_version,
                evidence_package=evidence_package,
                structured_outline=structured_outline,
                qa_available=qa_available,
                qa_unavailable_reason=qa_unavailable_reason,
            )
        )

    def _extract_evidence_package(self, file_version: FileVersion, implementation_id: str) -> dict:
        try:
            content = Path(file_version.storage_path).read_bytes()
            document = self.extractor.extract_text(content)
            pages = document.pages
        except (OSError, PdfReadError) as exc:
            raise BusinessError("MD_A_TEXT_EXTRACTION_FAILED") from exc

        located = locate_mda_section(pages)
        evidence_package = build_text_evidence_package(located, implementation_id)
        package = EvidencePackage(evidence_package)
        figure_candidates = [
            candidate
            for candidate in document.figure_candidates
            if located.start_page <= candidate.page < located.end_page
        ]
        self._extract_figure_evidence(
            figure_candidates,
            package,
            implementation_id,
        )
        if not package.has_extractable_content():
            raise BusinessError("MD_A_TEXT_EXTRACTION_FAILED")
        return evidence_package

    def _extract_figure_evidence(
        self,
        candidates: list[PdfFigureCandidate],
        package: EvidencePackage,
        implementation_id: str,
    ) -> None:
        filtered_candidates = filter_mda_figure_candidates(candidates)
        if not filtered_candidates:
            return
        if not self.figure_visual_analyzer.is_available():
            raise BusinessError("VISION_MODEL_UNAVAILABLE")

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

            image_id = package.next_image_id()
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

            source_section_id = package.source_section_id_for_page(candidate.page)
            relevance = str(visual_summary.get("relevance") or "high").lower()
            package.register_figure(
                {
                    "image_id": image_id,
                    "source_section_id": source_section_id,
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

    def _generate_validated_outline(
        self,
        session: Session,
        run: AnalysisRun,
        evidence_package: dict,
        *,
        ensure_not_stopped: Callable[[], None],
    ) -> dict:
        ensure_not_stopped()
        first_output = self.outline_generator.generate(evidence_package)
        ensure_not_stopped()
        first_validation = validate_structured_outline(first_output, evidence_package)
        if first_validation.is_valid:
            return first_validation.outline
        if first_validation.error_code == "ANALYSIS_OUTPUT_NO_VALID_EVIDENCE":
            raise BusinessError(first_validation.error_code)

        ensure_not_stopped()
        retried_output = self.outline_generator.generate(
            evidence_package,
            validation_errors=first_validation.errors,
        )
        ensure_not_stopped()
        retried_validation = validate_structured_outline(retried_output, evidence_package)
        if retried_validation.is_valid:
            return retried_validation.outline
        raise BusinessError(retried_validation.error_code)

    def _build_qa_index_metadata(
        self,
        *,
        evidence_package: dict,
        file_version_id: int,
        analysis_run_id: int,
        implementation_id: str,
    ) -> tuple[bool, str | None]:
        indexing_package = {
            **evidence_package,
            "qa_index_documents": EvidencePackageProjection(
                EvidencePackage(evidence_package)
            ).qa_index_documents(
                file_version_id=file_version_id,
                analysis_run_id=analysis_run_id,
            ),
        }
        try:
            qa_available, qa_unavailable_reason = self.qa_indexer.build_index(
                implementation_id,
                indexing_package,
            )
        except Exception as exc:
            qa_available = False
            qa_unavailable_reason = str(exc) or "QA indexing failed"
        if not qa_available and not qa_unavailable_reason:
            qa_unavailable_reason = "QA indexing failed"
        return qa_available, qa_unavailable_reason


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
    builder = EvidencePackageBuilder(
        implementation_id=implementation_id,
        root_title=MDA_TITLE,
        start_page=located.start_page,
        end_page=located.end_page,
        locator_evidence=located.locator_evidence,
    )

    for page, text in located.pages:
        lines = [raw_line.strip() for raw_line in text.splitlines() if raw_line.strip()]
        line_index = 0
        while line_index < len(lines):
            line = lines[line_index]
            if not line:
                line_index += 1
                continue
            if _is_source_subsection_heading(line):
                builder.start_subsection(title=line, page=page)
                line_index += 1
                continue
            if _table_title_from_line(line) is not None:
                table, consumed = _parse_table_block(
                    lines=lines[line_index:],
                    page=page,
                    source_section_id=builder.current_source_section_id,
                    table_id=builder.next_table_id(),
                )
                builder.add_table(table)
                line_index += consumed
                continue

            builder.add_text_span(page=page, text=line)
            line_index += 1

    return builder.to_persisted_json()


def validate_structured_outline(output: dict, evidence_package: dict) -> OutlineValidation:
    package = EvidencePackage(evidence_package)
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
            validation = package.validate_analysis_point(raw_point)
            invalid_table = invalid_table or validation.invalid_table
            invalid_figure = invalid_figure or validation.invalid_figure
            if validation.errors:
                errors.extend(validation.errors)
                schema_error = schema_error or not (
                    validation.invalid_table or validation.invalid_figure
                )
                continue
            if validation.point is not None:
                valid_points.append(validation.point)

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
            "source_sections": package.source_sections_for_outline(),
            "analysis_sections": valid_sections,
        },
        errors=[],
        error_code="",
    )


def _invalid(error_code: str, errors: list[str]) -> OutlineValidation:
    return OutlineValidation(is_valid=False, outline={}, errors=errors, error_code=error_code)


def _parse_table_block(
    *,
    lines: list[str],
    page: int,
    source_section_id: str,
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
        "source_section_id": source_section_id,
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


def _is_relevant_figure(relevance: str, visual_summary: dict) -> bool:
    explicit = visual_summary.get("is_relevant_to_analysis")
    if explicit is not None:
        return bool(explicit)
    return relevance not in {"low", "none", "irrelevant", "unrelated"}


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
