from __future__ import annotations

from dataclasses import dataclass


MDA_TITLE = "管理层讨论与分析"


@dataclass(frozen=True)
class EvidencePointValidation:
    point: dict | None
    errors: list[str]
    invalid_table: bool
    invalid_figure: bool


class EvidencePackage:
    def __init__(self, data: dict):
        self._data = data

    def to_persisted_json(self) -> dict:
        return self._data

    def has_extractable_content(self) -> bool:
        return bool(self._text_spans() or self._tables())

    def source_sections_data(self) -> tuple[dict, ...]:
        return tuple(self._source_sections())

    def text_spans_data(self) -> tuple[dict, ...]:
        return tuple(self._text_spans())

    def tables_data(self) -> tuple[dict, ...]:
        return tuple(self._tables())

    def figures_data(self) -> tuple[dict, ...]:
        return tuple(self._figures())

    def source_section_id_for_page(self, page: int) -> str:
        if not self._source_sections():
            raise ValueError("EvidencePackage has no source sections")
        best = self._source_sections()[0]
        stack = list(self._source_sections())
        while stack:
            section = stack.pop()
            if section.get("page_start", page) <= page <= section.get("page_end", page):
                best = section
                stack.extend(section.get("children", []))
        return best["source_section_id"]

    def source_sections_for_outline(self) -> list[dict]:
        return self._source_sections()

    def next_image_id(self) -> str:
        return f"image_{len(self._figures()) + 1}"

    def register_figure(self, figure: dict) -> None:
        self._figures().append(figure)
        source_section = self._source_section_by_id(figure["source_section_id"])
        if source_section is None:
            raise ValueError(f"Unknown source section {figure['source_section_id']}")
        source_section.setdefault("image_ids", []).append(figure["image_id"])

    def has_tables(self) -> bool:
        return bool(self._tables())

    def has_figures(self) -> bool:
        return bool(self._figures())

    def text_span_by_id(self, text_span_id: str | None) -> dict | None:
        return self._text_span_index().get(text_span_id)

    def table_by_id(self, table_id: str | None) -> dict | None:
        return self._table_index().get(table_id)

    def figure_by_id(self, image_id: str | None) -> dict | None:
        return self._figure_index().get(image_id)

    def source_section_ids(self) -> set[str]:
        return self._source_section_ids()

    def source_section_titles(self) -> dict[str, str]:
        return self._source_section_titles()

    def validate_analysis_point(self, raw_point: object) -> EvidencePointValidation:
        if not isinstance(raw_point, dict) or not isinstance(raw_point.get("text"), str):
            return EvidencePointValidation(None, ["analysis point text is required"], False, False)

        raw_evidence = raw_point.get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            return EvidencePointValidation(None, [], False, False)

        text_spans = self._text_span_index()
        tables = self._table_index()
        figures = self._figure_index()
        source_section_ids = self._source_section_ids()
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
                span = text_spans.get(text_span_id)
                if span is None:
                    errors.append(f"unknown text_span_id {text_span_id}")
                    continue
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
            return EvidencePointValidation(None, errors, invalid_table, invalid_figure)
        if not valid_evidence:
            return EvidencePointValidation(None, [], False, False)

        source_ids = sorted({item["source_section_id"] for item in valid_evidence})
        return EvidencePointValidation(
            {
                "text": raw_point["text"].strip(),
                "source_section_ids": source_ids,
                "evidence": valid_evidence,
            },
            [],
            False,
            False,
        )

    def validate_qa_evidence_item(self, evidence: dict) -> dict | None:
        content_type = evidence.get("content_type")
        if content_type == "text":
            span = self._text_span_index().get(evidence.get("text_span_id"))
            if span is None or evidence.get("source_section_id") != span["source_section_id"]:
                return None
            return {
                "content_type": "text",
                "source_section_id": span["source_section_id"],
                "text_span_id": span["text_span_id"],
                "page": span["page"],
                "page_label": span["page_label"],
                "evidence_text": str(evidence.get("evidence_text") or span["text"]),
            }
        if content_type == "table":
            table = self._table_index().get(evidence.get("table_id"))
            if table is None or evidence.get("source_section_id") != table["source_section_id"]:
                return None
            return {
                "content_type": "table",
                "source_section_id": table["source_section_id"],
                "table_id": table["table_id"],
                "page": table["page"],
                "page_label": table["page_label"],
                "evidence_text": str(evidence.get("evidence_text") or table["summary"]),
            }
        if content_type == "figure_summary":
            figure = self._figure_index().get(evidence.get("image_id"))
            if figure is None or evidence.get("source_section_id") != figure["source_section_id"]:
                return None
            return {
                "content_type": "figure_summary",
                "source_section_id": figure["source_section_id"],
                "image_id": figure["image_id"],
                "page": figure["page"],
                "page_label": figure["page_label"],
                "evidence_text": str(evidence.get("evidence_text") or figure["summary"]),
            }
        return None

    def _source_sections(self) -> list[dict]:
        return self._data.setdefault("source_sections", [])

    def _text_spans(self) -> list[dict]:
        return self._data.setdefault("text_spans", [])

    def _tables(self) -> list[dict]:
        return self._data.setdefault("tables", [])

    def _figures(self) -> list[dict]:
        return self._data.setdefault("figures", [])

    def _text_span_index(self) -> dict[str, dict]:
        return {span["text_span_id"]: span for span in self._text_spans()}

    def _table_index(self) -> dict[str, dict]:
        return {table["table_id"]: table for table in self._tables()}

    def _figure_index(self) -> dict[str, dict]:
        return {figure["image_id"]: figure for figure in self._figures()}

    def _source_section_ids(self) -> set[str]:
        return {
            section_id
            for section in self._source_sections()
            for section_id in _walk_source_section_ids(section)
        }

    def _source_section_titles(self) -> dict[str, str]:
        titles: dict[str, str] = {}
        for section in self._source_sections():
            titles[section["source_section_id"]] = section["title"]
            titles.update(_source_section_titles(section.get("children", [])))
        return titles

    def _source_section_by_id(self, source_section_id: str) -> dict | None:
        stack = list(self._source_sections())
        while stack:
            section = stack.pop()
            if section.get("source_section_id") == source_section_id:
                return section
            stack.extend(section.get("children", []))
        return None


class EvidencePackageBuilder:
    def __init__(
        self,
        *,
        implementation_id: str,
        root_title: str,
        start_page: int,
        end_page: int,
        locator_evidence: list[dict],
    ):
        self._root_section = {
            "source_section_id": "source_section_1",
            "title": root_title,
            "level": 1,
            "page_start": start_page,
            "page_end": end_page,
            "text_span_ids": [],
            "table_ids": [],
            "image_ids": [],
            "children": [],
        }
        self._current_section = self._root_section
        self._next_section_number = 2
        self._data = {
            "implementation_id": implementation_id,
            "source_sections": [self._root_section],
            "text_spans": [],
            "tables": [],
            "figures": [],
            "section_location_evidence": locator_evidence,
        }

    @property
    def current_source_section_id(self) -> str:
        return self._current_section["source_section_id"]

    def start_subsection(self, *, title: str, page: int) -> None:
        self._current_section = {
            "source_section_id": f"source_section_{self._next_section_number}",
            "title": title,
            "level": 2,
            "page_start": page,
            "page_end": page,
            "text_span_ids": [],
            "table_ids": [],
            "image_ids": [],
            "children": [],
        }
        self._next_section_number += 1
        self._root_section["children"].append(self._current_section)

    def add_text_span(self, *, page: int, text: str) -> None:
        text_span_id = f"text_span_{len(self._data['text_spans']) + 1}"
        self._current_section["page_end"] = page
        self._current_section["text_span_ids"].append(text_span_id)
        self._data["text_spans"].append(
            {
                "text_span_id": text_span_id,
                "source_section_id": self._current_section["source_section_id"],
                "page": page,
                "page_label": f"PDF 第 {page} 页",
                "text": text,
            }
        )

    def next_table_id(self) -> str:
        return f"table_{len(self._data['tables']) + 1}"

    def add_table(self, table: dict) -> None:
        self._current_section["page_end"] = table["page"]
        self._current_section["table_ids"].append(table["table_id"])
        self._data["tables"].append(table)

    def to_package(self) -> EvidencePackage:
        return EvidencePackage(self._data)

    def to_persisted_json(self) -> dict:
        return self._data


def _source_section_titles(source_sections: list[dict]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for section in source_sections:
        titles[section["source_section_id"]] = section["title"]
        titles.update(_source_section_titles(section.get("children", [])))
    return titles


def _walk_source_section_ids(section: dict) -> list[str]:
    section_ids = [section["source_section_id"]]
    for child in section.get("children", []):
        section_ids.extend(_walk_source_section_ids(child))
    return section_ids
