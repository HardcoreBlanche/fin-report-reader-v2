from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Protocol
import zipfile

from backend.app.evidence_package import EvidencePackage, MDA_TITLE
from backend.app.models import AnalysisResult


class FigureAssetResolver(Protocol):
    def resolve_asset(self, implementation_id: str, storage_key: str) -> Path:
        """Resolve a run-owned figure asset key to a local file."""


class EvidencePackageProjection:
    def __init__(self, package: EvidencePackage):
        self.package = package

    def report_detail(
        self,
        *,
        file_version_id: int,
        analysis_run_id: int,
        prompt_version: str,
        structured_outline: dict,
        qa_available: bool,
        qa_unavailable_reason: str | None,
    ) -> dict:
        text_span_index = {
            span["text_span_id"]: span for span in self.package.text_spans_data()
        }
        table_index = {
            table["table_id"]: self.table_read_model(table, file_version_id=file_version_id)
            for table in self.package.tables_data()
        }
        figure_index = {
            figure["image_id"]: self.figure_read_model(figure, file_version_id=file_version_id)
            for figure in self.package.figures_data()
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
                                self._enrich_report_evidence(
                                    evidence,
                                    text_span_index=text_span_index,
                                    table_index=table_index,
                                    figure_index=figure_index,
                                )
                                for evidence in point.get("evidence", [])
                            ],
                        }
                        for point in section.get("points", [])
                    ],
                }
            )

        return {
            "file_version_id": file_version_id,
            "analysis_run_id": analysis_run_id,
            "title": MDA_TITLE,
            "prompt_version": prompt_version,
            "summary": structured_outline.get("summary", []),
            "source_sections": list(self.package.source_sections_data()),
            "text_span_index": text_span_index,
            "table_index": table_index,
            "figure_index": figure_index,
            "other_figures": [
                figure
                for figure in figure_index.values()
                if not figure.get("is_relevant_to_analysis", True)
            ],
            "analysis_sections": analysis_sections,
            "qa_available": qa_available,
            "qa_unavailable_reason": qa_unavailable_reason,
            "labels": {
                "source_tree": "章节结构",
                "analysis_report": "分析报告",
                "qa_index": "问答索引",
                "evidence_package": "证据包",
            },
        }

    def table_asset(self, table_id: str) -> dict | None:
        return self.package.table_by_id(table_id)

    def figure_asset(self, image_id: str) -> dict | None:
        return self.package.figure_by_id(image_id)

    def qa_index_documents(self, *, file_version_id: int, analysis_run_id: int) -> list[dict]:
        section_titles = self.package.source_section_titles()
        documents: list[dict] = []
        for span in self.package.text_spans_data():
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
        for table in self.package.tables_data():
            documents.append(
                {
                    "doc_id": table["table_id"],
                    "text": self._table_text_for_index(table),
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
        for figure in self.package.figures_data():
            documents.append(
                {
                    "doc_id": figure["image_id"],
                    "text": self._figure_text_for_index(figure),
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

    def evidence_from_index_document(self, document: dict) -> dict | None:
        content_type = document["metadata"]["content_type"]
        doc_id = document["doc_id"]
        if content_type == "text":
            span = self.package.text_span_by_id(doc_id)
            if span is None:
                return None
            return {
                "content_type": "text",
                "source_section_id": span["source_section_id"],
                "text_span_id": span["text_span_id"],
                "page": span["page"],
                "page_label": span["page_label"],
                "evidence_text": span["text"],
            }
        if content_type == "table":
            table = self.package.table_by_id(doc_id)
            if table is None:
                return None
            return {
                "content_type": "table",
                "source_section_id": table["source_section_id"],
                "table_id": table["table_id"],
                "page": table["page"],
                "page_label": table["page_label"],
                "evidence_text": document["text"],
            }
        if content_type == "figure_summary":
            figure = self.package.figure_by_id(doc_id)
            if figure is None:
                return None
            return {
                "content_type": "figure_summary",
                "source_section_id": figure["source_section_id"],
                "image_id": figure["image_id"],
                "page": figure["page"],
                "page_label": figure["page_label"],
                "evidence_text": figure["summary"],
            }
        return None

    def tables_for_download(self) -> tuple[dict, ...]:
        return self.package.tables_data()

    def figures_for_download(self) -> tuple[dict, ...]:
        return self.package.figures_data()

    def page_label_for_evidence(self, evidence: dict) -> str:
        if evidence.get("content_type") == "table":
            table = self.package.table_by_id(evidence.get("table_id"))
            if table is not None:
                return table["page_label"]
        if evidence.get("content_type") == "figure_summary":
            figure = self.package.figure_by_id(evidence.get("image_id"))
            if figure is not None:
                return figure["page_label"]
        page = evidence.get("page")
        return f"PDF 第 {page} 页" if page is not None else "PDF 页码未知"

    def table_title(self, table_id: str | None) -> str:
        table = self.package.table_by_id(table_id)
        return table.get("title", "未命名表格") if table is not None else "未命名表格"

    def figure_title(self, image_id: str | None) -> str:
        figure = self.package.figure_by_id(image_id)
        if figure is None:
            return "未命名图示"
        return figure.get("title") or figure.get("caption") or "未命名图示"

    def render_markdown(self, result: AnalysisResult) -> str:
        structured_outline = result.structured_outline
        lines: list[str] = [
            "# 管理层讨论与分析",
            "",
            "本报告仅基于当前管理层讨论与分析的已验证分析结果生成。",
            "",
            "## 摘要",
            "",
        ]
        for sentence in structured_outline.get("summary", []):
            lines.append(f"- {sentence}")

        if self.package.has_figures():
            lines.extend(["", "> 图示引用保留在 Markdown 中。请下载 ZIP 以保留完整离线图片。"])
        if self.package.has_tables():
            lines.extend(["", "> 表格摘要保留在 Markdown 中。请下载 ZIP 以保留完整结构化表格数据。"])

        for section in structured_outline.get("analysis_sections", []):
            lines.extend(["", f"## {section['title']}", ""])
            for point in section.get("points", []):
                lines.append(f"- {point['text']}")
                evidence_items = point.get("evidence", [])
                if not evidence_items:
                    continue
                lines.append("  - 证据：")
                for evidence in evidence_items:
                    lines.append(f"    - {self.format_markdown_evidence(evidence)}")

        if self.package.has_tables():
            lines.extend(["", "## 表格证据", ""])
            for table in self.tables_for_download():
                lines.extend(
                    [
                        f"### {table['title']}",
                        "",
                        f"- 摘要：{table['summary']}",
                        f"- 页码：{table['page_label']}",
                        f"- 完整数据：`tables/{table['table_id']}.json`",
                        "",
                    ]
                )

        if self.package.has_figures():
            lines.extend(["", "## 图示证据", ""])
            for figure in self.figures_for_download():
                title = figure.get("title") or figure.get("caption") or figure["image_id"]
                image_path = self.figure_archive_path(figure)
                lines.extend(
                    [
                        f"### {title}",
                        "",
                        f"![{title}]({image_path})",
                        "",
                        f"- 摘要：{figure['summary']}",
                        f"- 页码：{figure['page_label']}",
                        "",
                    ]
                )

        return "\n".join(lines).rstrip() + "\n"

    def build_zip(
        self,
        *,
        result: AnalysisResult,
        figure_asset_store: FigureAssetResolver | None,
    ) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.md", self.render_markdown(result))
            for table in self.tables_for_download():
                archive.writestr(
                    f"tables/{table['table_id']}.json",
                    json.dumps(table, ensure_ascii=False, indent=2),
                )
            for figure in self.figures_for_download():
                if figure_asset_store is None:
                    raise RuntimeError("figure asset store is required for ZIP downloads")
                original = figure["original"]
                asset_path = figure_asset_store.resolve_asset(
                    result.analysis_run.implementation_id,
                    original["storage_key"],
                )
                archive.write(asset_path, self.figure_archive_path(figure))
        return buffer.getvalue()

    def format_markdown_evidence(self, evidence: dict) -> str:
        content_type = evidence.get("content_type")
        page_label = evidence.get("page_label") or self.page_label_for_evidence(evidence)
        evidence_text = str(evidence.get("evidence_text") or "").strip()
        if content_type == "table":
            table_id = evidence.get("table_id")
            title = self.table_title(table_id)
            return f"表格 `{table_id}`（{title}，{page_label}）：{evidence_text}"
        if content_type == "figure_summary":
            image_id = evidence.get("image_id")
            title = self.figure_title(image_id)
            return f"图示 `{image_id}`（{title}，{page_label}）：{evidence_text}"
        text_span_id = evidence.get("text_span_id")
        return f"文本 `{text_span_id}`（{page_label}）：{evidence_text}"

    def figure_archive_path(self, figure: dict) -> str:
        storage_key = figure["original"]["storage_key"]
        extension = storage_key.rsplit(".", 1)[-1] if "." in storage_key else "png"
        return f"figures/{figure['image_id']}.{extension}"

    def table_read_model(self, table: dict, *, file_version_id: int) -> dict:
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

    def figure_read_model(self, figure: dict, *, file_version_id: int) -> dict:
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

    def _enrich_report_evidence(
        self,
        evidence: dict,
        *,
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

    def _table_text_for_index(self, table: dict) -> str:
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

    def _figure_text_for_index(self, figure: dict) -> str:
        lines = [f"图示：{figure.get('title') or figure['image_id']}"]
        if figure.get("caption"):
            lines.append(f"说明：{figure['caption']}")
        lines.append(f"摘要：{figure['summary']}")
        if figure.get("relevance_reason"):
            lines.append(f"相关性：{figure['relevance_reason']}")
        return "\n".join(lines)


def projection_from_package(data: dict) -> EvidencePackageProjection:
    return EvidencePackageProjection(EvidencePackage(data))


def projection_from_result(result: AnalysisResult) -> EvidencePackageProjection:
    return EvidencePackageProjection(EvidencePackage(result.evidence_package))
