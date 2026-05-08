from __future__ import annotations

import re
from typing import Protocol

from backend.app.errors import BusinessError
from backend.app.mda_analysis import build_qa_index_documents
from backend.app.models import AnalysisResult


QA_PROMPT_VERSION = "qa_answer_v1"
OUT_OF_SCOPE_ANSWER = "当前问答仅基于第三节‘管理层讨论与分析’，无法回答该问题"
INSUFFICIENT_EVIDENCE_ANSWER = "当前管理层讨论与分析证据不足，无法回答该问题"


class QaAnswerGenerator(Protocol):
    prompt_version: str

    def generate(self, question: str, evidence: list[dict]) -> dict:
        """Generate one answer from already-retrieved current AnalysisResult evidence."""


class ExtractiveQaAnswerGenerator:
    prompt_version = QA_PROMPT_VERSION

    def generate(self, question: str, evidence: list[dict]) -> dict:
        if not evidence:
            return {
                "status": "insufficient_evidence",
                "answer": INSUFFICIENT_EVIDENCE_ANSWER,
                "evidence": [],
            }
        first = evidence[0]
        return {
            "status": "answered",
            "answer": f"根据当前管理层讨论与分析证据，{first['evidence_text']}",
            "evidence": [first],
        }


class AnalysisResultQaService:
    def __init__(self, answer_generator: QaAnswerGenerator | None = None):
        self.answer_generator = answer_generator or ExtractiveQaAnswerGenerator()

    def answer(self, result: AnalysisResult, question: str) -> dict:
        cleaned_question = question.strip()
        if not cleaned_question:
            raise BusinessError("EMPTY_QUESTION")
        if not result.qa_available:
            raise BusinessError("QA_INDEX_UNAVAILABLE")
        if _is_out_of_scope(cleaned_question):
            return {
                "status": "out_of_scope",
                "answer": OUT_OF_SCOPE_ANSWER,
                "evidence": [],
                "prompt_version": self.answer_generator.prompt_version,
            }

        evidence = _retrieve_evidence(result, cleaned_question)
        if not evidence:
            return {
                "status": "insufficient_evidence",
                "answer": INSUFFICIENT_EVIDENCE_ANSWER,
                "evidence": [],
                "prompt_version": self.answer_generator.prompt_version,
            }

        try:
            generated = self.answer_generator.generate(cleaned_question, evidence)
        except Exception as exc:
            raise BusinessError("QA_GENERATION_FAILED") from exc
        validated = validate_qa_answer(result, generated)
        validated["prompt_version"] = self.answer_generator.prompt_version
        return validated


def validate_qa_answer(result: AnalysisResult, generated: dict) -> dict:
    status = generated.get("status")
    answer = generated.get("answer")
    evidence = generated.get("evidence")
    if status not in {"answered", "insufficient_evidence", "out_of_scope"}:
        raise BusinessError("QA_GENERATION_FAILED")
    if not isinstance(answer, str) or not answer.strip():
        raise BusinessError("QA_GENERATION_FAILED")
    if not isinstance(evidence, list):
        raise BusinessError("QA_GENERATION_FAILED")
    if status != "answered":
        return {"status": status, "answer": answer.strip(), "evidence": []}
    if not evidence:
        raise BusinessError("QA_EVIDENCE_VALIDATION_FAILED")

    validated_evidence: list[dict] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise BusinessError("QA_EVIDENCE_VALIDATION_FAILED")
        validated_evidence.append(_validate_evidence_item(result, item))
    return {"status": "answered", "answer": answer.strip(), "evidence": validated_evidence}


def _retrieve_evidence(result: AnalysisResult, question: str) -> list[dict]:
    documents = build_qa_index_documents(
        file_version_id=result.file_version_id,
        analysis_run_id=result.analysis_run_id,
        evidence_package=result.evidence_package,
    )
    scored: list[tuple[int, dict]] = []
    for document in documents:
        score = _match_score(question, document["text"])
        if score >= 5:
            evidence = _evidence_from_document(result, document)
            if evidence is not None:
                scored.append((score, evidence))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [evidence for _, evidence in scored[:3]]


def _evidence_from_document(result: AnalysisResult, document: dict) -> dict | None:
    content_type = document["metadata"]["content_type"]
    doc_id = document["doc_id"]
    if content_type == "text":
        span = next(
            (
                span
                for span in result.evidence_package.get("text_spans", [])
                if span.get("text_span_id") == doc_id
            ),
            None,
        )
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
        table = next(
            (
                table
                for table in result.evidence_package.get("tables", [])
                if table.get("table_id") == doc_id
            ),
            None,
        )
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
        figure = next(
            (
                figure
                for figure in result.evidence_package.get("figures", [])
                if figure.get("image_id") == doc_id
            ),
            None,
        )
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


def _validate_evidence_item(result: AnalysisResult, evidence: dict) -> dict:
    content_type = evidence.get("content_type")
    if content_type == "text":
        span = next(
            (
                span
                for span in result.evidence_package.get("text_spans", [])
                if span.get("text_span_id") == evidence.get("text_span_id")
            ),
            None,
        )
        if span is None or evidence.get("source_section_id") != span["source_section_id"]:
            raise BusinessError("QA_EVIDENCE_VALIDATION_FAILED")
        return {
            "content_type": "text",
            "source_section_id": span["source_section_id"],
            "text_span_id": span["text_span_id"],
            "page": span["page"],
            "page_label": span["page_label"],
            "evidence_text": str(evidence.get("evidence_text") or span["text"]),
        }
    if content_type == "table":
        table = next(
            (
                table
                for table in result.evidence_package.get("tables", [])
                if table.get("table_id") == evidence.get("table_id")
            ),
            None,
        )
        if table is None or evidence.get("source_section_id") != table["source_section_id"]:
            raise BusinessError("QA_EVIDENCE_VALIDATION_FAILED")
        return {
            "content_type": "table",
            "source_section_id": table["source_section_id"],
            "table_id": table["table_id"],
            "page": table["page"],
            "page_label": table["page_label"],
            "evidence_text": str(evidence.get("evidence_text") or table["summary"]),
        }
    if content_type == "figure_summary":
        figure = next(
            (
                figure
                for figure in result.evidence_package.get("figures", [])
                if figure.get("image_id") == evidence.get("image_id")
            ),
            None,
        )
        if figure is None or evidence.get("source_section_id") != figure["source_section_id"]:
            raise BusinessError("QA_EVIDENCE_VALIDATION_FAILED")
        return {
            "content_type": "figure_summary",
            "source_section_id": figure["source_section_id"],
            "image_id": figure["image_id"],
            "page": figure["page"],
            "page_label": figure["page_label"],
            "evidence_text": str(evidence.get("evidence_text") or figure["summary"]),
        }
    raise BusinessError("QA_EVIDENCE_VALIDATION_FAILED")


def _match_score(question: str, text: str) -> int:
    normalized_question = _normalize_for_match(question)
    normalized_text = _normalize_for_match(text)
    if not normalized_question or not normalized_text:
        return 0

    score = 0
    question_chars = {char for char in normalized_question if char not in _STOP_CHARS}
    for char in question_chars:
        if char in normalized_text:
            score += 1

    for gram in _char_ngrams(normalized_question, 2):
        if gram in normalized_text:
            score += 2
    for gram in _char_ngrams(normalized_question, 3):
        if gram in normalized_text:
            score += 3
    return score


def _is_out_of_scope(question: str) -> bool:
    return any(term in question for term in _OUT_OF_SCOPE_TERMS)


def _normalize_for_match(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value).lower()


def _char_ngrams(value: str, size: int) -> set[str]:
    return {
        value[index : index + size]
        for index in range(0, max(len(value) - size + 1, 0))
        if not any(char in _STOP_CHARS for char in value[index : index + size])
    }


_STOP_CHARS = set("的是了和与及或吗呢啊有哪些如何什么多少是否一个当前")

_OUT_OF_SCOPE_TERMS = {
    "公司治理",
    "董事",
    "监事",
    "股东",
    "分红",
    "利润表",
    "资产负债表",
    "现金流量表",
    "财务报表",
    "股票价格",
    "交易所",
    "股本",
    "审计",
}
