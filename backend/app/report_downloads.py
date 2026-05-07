from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Protocol
import zipfile

from backend.app.models import AnalysisResult


class FigureAssetResolver(Protocol):
    def resolve_asset(self, implementation_id: str, storage_key: str) -> Path:
        """Resolve a run-owned figure asset key to a local file."""


class AnalysisResultDownloadService:
    def __init__(self, figure_asset_store: FigureAssetResolver | None = None):
        self.figure_asset_store = figure_asset_store

    def render_markdown(self, result: AnalysisResult) -> str:
        return render_analysis_result_markdown(result)

    def build_zip(self, result: AnalysisResult) -> bytes:
        return build_analysis_result_zip(result, self.figure_asset_store)


def render_analysis_result_markdown(result: AnalysisResult) -> str:
    structured_outline = result.structured_outline
    evidence_package = result.evidence_package
    tables = {table["table_id"]: table for table in evidence_package.get("tables", [])}
    figures = {figure["image_id"]: figure for figure in evidence_package.get("figures", [])}

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

    if figures:
        lines.extend(
            [
                "",
                "> 图示引用保留在 Markdown 中。请下载 ZIP 以保留完整离线图片。",
            ]
        )
    if tables:
        lines.extend(
            [
                "",
                "> 表格摘要保留在 Markdown 中。请下载 ZIP 以保留完整结构化表格数据。",
            ]
        )

    for section in structured_outline.get("analysis_sections", []):
        lines.extend(["", f"## {section['title']}", ""])
        for point in section.get("points", []):
            lines.append(f"- {point['text']}")
            evidence_items = point.get("evidence", [])
            if not evidence_items:
                continue
            lines.append("  - 证据：")
            for evidence in evidence_items:
                lines.append(f"    - {_format_evidence(evidence, tables, figures)}")

    if tables:
        lines.extend(["", "## 表格证据", ""])
        for table in tables.values():
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

    if figures:
        lines.extend(["", "## 图示证据", ""])
        for figure in figures.values():
            title = figure.get("title") or figure.get("caption") or figure["image_id"]
            image_path = _figure_archive_path(figure)
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


def build_analysis_result_zip(
    result: AnalysisResult,
    figure_asset_store: FigureAssetResolver | None,
) -> bytes:
    evidence_package = result.evidence_package
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.md", render_analysis_result_markdown(result))
        for table in evidence_package.get("tables", []):
            archive.writestr(
                f"tables/{table['table_id']}.json",
                json.dumps(table, ensure_ascii=False, indent=2),
            )
        for figure in evidence_package.get("figures", []):
            if figure_asset_store is None:
                raise RuntimeError("figure asset store is required for ZIP downloads")
            original = figure["original"]
            asset_path = figure_asset_store.resolve_asset(
                result.analysis_run.implementation_id,
                original["storage_key"],
            )
            archive.write(asset_path, _figure_archive_path(figure))
    return buffer.getvalue()


def _format_evidence(evidence: dict, tables: dict[str, dict], figures: dict[str, dict]) -> str:
    content_type = evidence.get("content_type")
    page_label = evidence.get("page_label") or _page_label_from_evidence(evidence, tables, figures)
    evidence_text = str(evidence.get("evidence_text") or "").strip()
    if content_type == "table":
        table_id = evidence.get("table_id")
        table = tables.get(table_id, {})
        return f"表格 `{table_id}`（{table.get('title', '未命名表格')}，{page_label}）：{evidence_text}"
    if content_type == "figure_summary":
        image_id = evidence.get("image_id")
        figure = figures.get(image_id, {})
        title = figure.get("title") or figure.get("caption") or "未命名图示"
        return f"图示 `{image_id}`（{title}，{page_label}）：{evidence_text}"
    text_span_id = evidence.get("text_span_id")
    return f"文本 `{text_span_id}`（{page_label}）：{evidence_text}"


def _page_label_from_evidence(
    evidence: dict,
    tables: dict[str, dict],
    figures: dict[str, dict],
) -> str:
    if evidence.get("content_type") == "table":
        table = tables.get(evidence.get("table_id"))
        if table is not None:
            return table["page_label"]
    if evidence.get("content_type") == "figure_summary":
        figure = figures.get(evidence.get("image_id"))
        if figure is not None:
            return figure["page_label"]
    page = evidence.get("page")
    return f"PDF 第 {page} 页" if page is not None else "PDF 页码未知"


def _figure_archive_path(figure: dict) -> str:
    storage_key = figure["original"]["storage_key"]
    extension = storage_key.rsplit(".", 1)[-1] if "." in storage_key else "png"
    return f"figures/{figure['image_id']}.{extension}"
