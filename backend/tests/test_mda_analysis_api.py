import io
import json
from pathlib import Path
import sqlite3
import zipfile

from fastapi.testclient import TestClient

from backend.app.current_analysis_result_access import (
    DownloadedAnalysisResult,
    ResolvedFigureAsset,
)
from backend.app.main import create_app
from backend.app.mda_analysis import FilesystemFigureAssetStore
from backend.app.pdf_extraction import PdfFigureCandidate, PdfTextDocument


PDF_BYTES = b"%PDF-1.7\ntext only mda bytes"
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\xf8\x0f"
    b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeExtractor:
    def __init__(self, pages: list[str]):
        self.pages = pages

    def extract_text(self, _content: bytes) -> PdfTextDocument:
        return PdfTextDocument(self.pages)


class FakeFigureExtractor(FakeExtractor):
    def __init__(self, pages: list[str], figure_candidates: list[PdfFigureCandidate]):
        super().__init__(pages)
        self.figure_candidates = figure_candidates

    def extract_text(self, _content: bytes) -> PdfTextDocument:
        return PdfTextDocument(self.pages, figure_candidates=self.figure_candidates)


class StopAfterExtractionExtractor:
    def __init__(self, db_path: Path, pages: list[str]):
        self.db_path = db_path
        self.pages = pages
        self.stop_during_next_extract = False
        self.stop_updates = 0

    def extract_text(self, _content: bytes) -> PdfTextDocument:
        if self.stop_during_next_extract:
            with sqlite3.connect(self.db_path) as connection:
                cursor = connection.execute(
                    """
                    update analysis_runs
                    set status = 'stopped'
                    where id = (
                        select id
                        from analysis_runs
                        where status in ('parsing', 'generating')
                        order by id desc
                        limit 1
                    )
                    """
                )
                self.stop_updates = cursor.rowcount
        return PdfTextDocument(self.pages)


class FakeOutlineGenerator:
    prompt_version = "mda_outline_v1"

    def generate(self, evidence_package: dict, validation_errors: list[str] | None = None) -> dict:
        assert validation_errors is None
        revenue_span = next(
            span for span in evidence_package["text_spans"] if "营业收入同比增长" in span["text"]
        )
        risk_span = next(
            span for span in evidence_package["text_spans"] if "原材料价格波动" in span["text"]
        )
        first_span_id = revenue_span["text_span_id"]
        second_span_id = risk_span["text_span_id"]
        first_section_id = revenue_span["source_section_id"]
        second_section_id = risk_span["source_section_id"]
        return {
            "summary": [
                "公司围绕主营业务披露了经营表现。",
                "管理层讨论了业务增长的主要来源。",
                "报告同时说明了原材料价格波动风险。",
            ],
            "analysis_sections": [
                {
                    "title": "经营表现",
                    "points": [
                        {
                            "text": "公司营业收入保持增长，主要来自核心产品销售。",
                            "source_section_ids": [first_section_id],
                            "evidence": [
                                {
                                    "content_type": "text",
                                    "source_section_id": first_section_id,
                                    "text_span_id": first_span_id,
                                    "evidence_text": "营业收入同比增长",
                                }
                            ],
                        },
                        {
                            "text": "这个无证据观点应由后端丢弃。",
                            "source_section_ids": [],
                            "evidence": [],
                        },
                    ],
                },
                {
                    "title": "风险因素",
                    "points": [
                        {
                            "text": "原材料价格波动可能影响成本控制。",
                            "source_section_ids": [second_section_id],
                            "evidence": [
                                {
                                    "content_type": "text",
                                    "source_section_id": second_section_id,
                                    "text_span_id": second_span_id,
                                    "evidence_text": "原材料价格波动",
                                }
                            ],
                        }
                    ],
                },
                {
                    "title": "未披露主题",
                    "points": [
                        {
                            "text": "没有证据的推荐主题不应展示。",
                            "source_section_ids": [],
                            "evidence": [],
                        }
                    ],
                },
            ],
        }


class RecordingResourceCleaner:
    def __init__(self):
        self.cleaned_implementation_ids: list[str] = []

    def cleanup_run(self, implementation_id: str) -> None:
        self.cleaned_implementation_ids.append(implementation_id)


class FailingResourceCleaner:
    def cleanup_run(self, implementation_id: str) -> None:
        raise RuntimeError(f"cleanup failed for {implementation_id}")


class FailingPromotionFigureAssetStore(FilesystemFigureAssetStore):
    def __init__(self, root: Path):
        super().__init__(root)
        self.promoted_ids: list[str] = []
        self.cleaned_ids: list[str] = []

    def promote_run_assets(self, implementation_id: str) -> None:
        super().promote_run_assets(implementation_id)
        self.promoted_ids.append(implementation_id)
        raise RuntimeError("promotion failed after moving files")

    def cleanup_run(self, implementation_id: str) -> None:
        self.cleaned_ids.append(implementation_id)
        super().cleanup_run(implementation_id)


class FailingThumbnailFigureAssetStore(FilesystemFigureAssetStore):
    def _thumbnail_bytes(self, image_bytes: bytes) -> bytes:
        raise RuntimeError("thumbnail generation failed")


class CountingQaIndexer:
    def __init__(self):
        self.call_count = 0

    def build_index(self, implementation_id: str, evidence_package: dict) -> tuple[bool, str | None]:
        self.call_count += 1
        return True, None


class RecordingQaIndexer:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def build_index(self, implementation_id: str, evidence_package: dict) -> tuple[bool, str | None]:
        self.calls.append((implementation_id, evidence_package))
        return True, None


class FailingQaIndexer:
    def build_index(self, implementation_id: str, evidence_package: dict) -> tuple[bool, str | None]:
        raise RuntimeError("chroma write failed")


class InvalidQaAnswerGenerator:
    prompt_version = "qa_answer_v1"

    def generate(self, question: str, evidence: list[dict]) -> dict:
        return {
            "status": "answered",
            "answer": "这个回答引用了不存在的证据。",
            "evidence": [
                {
                    "content_type": "text",
                    "source_section_id": "source_section_2",
                    "text_span_id": "text_span_missing",
                    "evidence_text": "不存在的证据",
                }
            ],
        }


class RetryingOutlineGenerator:
    prompt_version = "mda_outline_v1"

    def __init__(self):
        self.calls: list[list[str] | None] = []

    def generate(self, evidence_package: dict, validation_errors: list[str] | None = None) -> dict:
        self.calls.append(validation_errors)
        if validation_errors is None:
            return {"summary": ["太短。"], "analysis_sections": []}

        span = evidence_package["text_spans"][0]
        return {
            "summary": ["第一句。", "第二句。", "第三句。"],
            "analysis_sections": [
                {
                    "title": "经营表现",
                    "points": [
                        {
                            "text": "重试后返回可验证观点。",
                            "source_section_ids": [span["source_section_id"]],
                            "evidence": [
                                {
                                    "content_type": "text",
                                    "source_section_id": span["source_section_id"],
                                    "text_span_id": span["text_span_id"],
                                    "evidence_text": span["text"],
                                }
                            ],
                        }
                    ],
                }
            ],
        }


class EvidenceFreeOutlineGenerator:
    prompt_version = "mda_outline_v1"

    def __init__(self):
        self.call_count = 0

    def generate(self, evidence_package: dict, validation_errors: list[str] | None = None) -> dict:
        self.call_count += 1
        return {
            "summary": ["第一句。", "第二句。", "第三句。"],
            "analysis_sections": [
                {
                    "title": "经营表现",
                    "points": [
                        {
                            "text": "没有证据的观点。",
                            "source_section_ids": [],
                            "evidence": [],
                        }
                    ],
                }
            ],
        }


class CountingOutlineGenerator(FakeOutlineGenerator):
    def __init__(self):
        self.call_count = 0

    def generate(self, evidence_package: dict, validation_errors: list[str] | None = None) -> dict:
        self.call_count += 1
        return super().generate(evidence_package, validation_errors)


class InvalidAssetOutlineGenerator:
    prompt_version = "mda_outline_v1"

    def __init__(self):
        self.calls: list[list[str] | None] = []

    def generate(self, evidence_package: dict, validation_errors: list[str] | None = None) -> dict:
        self.calls.append(validation_errors)
        return {
            "summary": ["第一句。", "第二句。", "第三句。"],
            "analysis_sections": [
                {
                    "title": "图表引用",
                    "points": [
                        {
                            "text": "引用了不存在的图表。",
                            "source_section_ids": ["source_section_1"],
                            "evidence": [
                                {
                                    "content_type": "table",
                                    "source_section_id": "source_section_1",
                                    "table_id": "table_missing",
                                    "evidence_text": "表格证据",
                                },
                                {
                                    "content_type": "figure_summary",
                                    "source_section_id": "source_section_1",
                                    "image_id": "image_missing",
                                    "evidence_text": "图示证据",
                                },
                            ],
                        }
                    ],
                }
            ],
        }


class InvalidTableReferenceOutlineGenerator:
    prompt_version = "mda_outline_v1"

    def __init__(self):
        self.calls: list[list[str] | None] = []

    def generate(self, evidence_package: dict, validation_errors: list[str] | None = None) -> dict:
        self.calls.append(validation_errors)
        return {
            "summary": ["第一句。", "第二句。", "第三句。"],
            "analysis_sections": [
                {
                    "title": "表格引用",
                    "points": [
                        {
                            "text": "引用了不存在的表格。",
                            "source_section_ids": ["source_section_1"],
                            "evidence": [
                                {
                                    "content_type": "table",
                                    "source_section_id": "source_section_1",
                                    "table_id": "table_missing",
                                    "evidence_text": "表格证据",
                                }
                            ],
                        }
                    ],
                }
            ],
        }


class InvalidFigureReferenceOutlineGenerator:
    prompt_version = "mda_outline_v1"

    def __init__(self):
        self.calls: list[list[str] | None] = []

    def generate(self, evidence_package: dict, validation_errors: list[str] | None = None) -> dict:
        self.calls.append(validation_errors)
        return {
            "summary": ["第一句。", "第二句。", "第三句。"],
            "analysis_sections": [
                {
                    "title": "图示引用",
                    "points": [
                        {
                            "text": "引用了不存在的图示。",
                            "source_section_ids": ["source_section_2"],
                            "evidence": [
                                {
                                    "content_type": "figure_summary",
                                    "source_section_id": "source_section_2",
                                    "image_id": "image_missing",
                                    "evidence_text": "图示证据",
                                }
                            ],
                        }
                    ],
                }
            ],
        }


class TableAwareOutlineGenerator:
    prompt_version = "mda_outline_v1"

    def generate(self, evidence_package: dict, validation_errors: list[str] | None = None) -> dict:
        assert validation_errors is None
        table = evidence_package["tables"][0]
        return {
            "summary": [
                "公司披露了按产品划分的主营业务收入。",
                "表格证据显示核心产品收入占比较高。",
                "管理层讨论与分析同时保留了可追溯页码。",
            ],
            "analysis_sections": [
                {
                    "title": "主营业务构成",
                    "points": [
                        {
                            "text": "核心产品仍是主营业务收入的主要来源。",
                            "source_section_ids": [table["source_section_id"]],
                            "evidence": [
                                {
                                    "content_type": "table",
                                    "source_section_id": table["source_section_id"],
                                    "table_id": table["table_id"],
                                    "evidence_text": "核心产品收入 80 亿元",
                                }
                            ],
                        }
                    ],
                }
            ],
        }


class RecordingFigureAnalyzer:
    prompt_version = "figure_summary_v1"

    def __init__(self):
        self.seen_candidate_ids: list[str] = []

    def is_available(self) -> bool:
        return True

    def summarize(self, candidate: PdfFigureCandidate) -> dict:
        self.seen_candidate_ids.append(candidate.candidate_id)
        return {
            "is_informational": True,
            "classification_reason": "包含经营收入结构图。",
            "summary": "图示展示核心产品收入占比较高，与经营表现相关。",
            "relevance": "high",
            "relevance_reason": "直接支持主营业务收入结构分析。",
        }


class LowRelevanceFigureAnalyzer(RecordingFigureAnalyzer):
    def summarize(self, candidate: PdfFigureCandidate) -> dict:
        self.seen_candidate_ids.append(candidate.candidate_id)
        return {
            "is_informational": True,
            "classification_reason": "这是正文中的装饰性产品图片。",
            "summary": "图片展示产品外观，但不直接支持经营或财务分析。",
            "relevance": "low",
            "relevance_reason": "缺少业务或财务数据含义。",
        }


class UnavailableFigureAnalyzer:
    prompt_version = "figure_summary_v1"

    def __init__(self):
        self.call_count = 0

    def is_available(self) -> bool:
        return False

    def summarize(self, candidate: PdfFigureCandidate) -> dict:
        self.call_count += 1
        return {"is_informational": True, "summary": candidate.candidate_id}


class FigureAwareOutlineGenerator:
    prompt_version = "mda_outline_v1"

    def generate(self, evidence_package: dict, validation_errors: list[str] | None = None) -> dict:
        assert validation_errors is None
        figure = evidence_package["figures"][0]
        return {
            "summary": [
                "公司披露了主营业务经营表现。",
                "图示证据显示核心产品收入占比较高。",
                "管理层讨论与分析保留了可追溯图示证据。",
            ],
            "analysis_sections": [
                {
                    "title": "经营表现",
                    "points": [
                        {
                            "text": "核心产品仍是主营业务收入的重要来源。",
                            "source_section_ids": [figure["source_section_id"]],
                            "evidence": [
                                {
                                    "content_type": "figure_summary",
                                    "source_section_id": figure["source_section_id"],
                                    "image_id": figure["image_id"],
                                    "evidence_text": "核心产品收入占比较高",
                                }
                            ],
                        }
                    ],
                }
            ],
        }


def make_client(tmp_path: Path, pages: list[str], outline_generator=None) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        source_pdf_dir=tmp_path / "source_pdfs",
        extractor=FakeExtractor(pages),
        outline_generator=outline_generator or FakeOutlineGenerator(),
    )
    return TestClient(app)


def make_limited_client(tmp_path: Path, pages: list[str], concurrency_limit: int) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        source_pdf_dir=tmp_path / "source_pdfs",
        extractor=FakeExtractor(pages),
        outline_generator=FakeOutlineGenerator(),
        analysis_concurrency_limit=concurrency_limit,
    )
    return TestClient(app)


def annual_report_with_text_only_mda_pages() -> list[str]:
    return [
        "贵州茅台酒股份有限公司\n2024 年年度报告",
        "目录\n公司简介和主要财务指标 3\n管理层讨论与分析 4\n公司治理 6",
        "\n".join(
            [
                "第二节 公司简介和主要财务指标",
                "公司全称：贵州茅台酒股份有限公司",
                "公司简称：贵州茅台",
                "股票代码：600519",
                "主要会计数据日期：2024年12月31日",
            ]
        ),
        "\n".join(
            [
                "第三节 管理层讨论与分析",
                "一、经营情况讨论与分析",
                "报告期内，公司实现营业收入100亿元，营业收入同比增长。",
                "核心产品销售稳定，是收入增长的主要来源。",
            ]
        ),
        "\n".join(
            [
                "二、风险因素",
                "公司面临原材料价格波动风险，需要持续加强成本控制。",
            ]
        ),
        "第四节 公司治理\n本节内容不应进入分析证据。",
    ]


def annual_report_with_mda_table_pages() -> list[str]:
    return [
        "贵州茅台酒股份有限公司\n2024 年年度报告",
        "目录\n公司简介和主要财务指标 3\n管理层讨论与分析 4\n公司治理 6",
        "\n".join(
            [
                "第二节 公司简介和主要财务指标",
                "公司全称：贵州茅台酒股份有限公司",
                "公司简称：贵州茅台",
                "股票代码：600519",
                "主要会计数据日期：2024年12月31日",
            ]
        ),
        "\n".join(
            [
                "第三节 管理层讨论与分析",
                "一、经营情况讨论与分析",
                "报告期内，公司按产品披露主营业务收入。",
                "表格：主营业务分产品情况",
                "| 产品 | 收入 | 同比 |",
                "| --- | --- | --- |",
                "| 核心产品 | 80亿元 | 12% |",
                "| 其他产品 | 20亿元 | 3% |",
                "注：收入为不含税金额。",
            ]
        ),
        "\n".join(
            [
                "二、风险因素",
                "公司面临原材料价格波动风险，需要持续加强成本控制。",
            ]
        ),
        "第四节 公司治理\n本节内容不应进入分析证据。",
    ]


def annual_report_with_malformed_mda_table_pages() -> list[str]:
    pages = annual_report_with_mda_table_pages()
    pages[3] = "\n".join(
        [
            "第三节 管理层讨论与分析",
            "一、经营情况讨论与分析",
            "报告期内，公司按产品披露主营业务收入。",
            "表格：主营业务分产品情况",
            "核心产品 80亿元 12%",
        ]
    )
    return pages


def annual_report_with_large_mda_table_pages(row_count: int = 120) -> list[str]:
    pages = annual_report_with_mda_table_pages()
    table_rows = [f"| 产品{index} | {index}亿元 | {index}% |" for index in range(1, row_count + 1)]
    pages[3] = "\n".join(
        [
            "第三节 管理层讨论与分析",
            "一、经营情况讨论与分析",
            "报告期内，公司按产品披露主营业务收入。",
            "表格：主营业务分产品情况",
            "| 产品 | 收入 | 同比 |",
            "| --- | --- | --- |",
            *table_rows,
            "注：收入为不含税金额。",
        ]
    )
    return pages


def mda_figure_candidates() -> list[PdfFigureCandidate]:
    return [
        PdfFigureCandidate(
            candidate_id="logo",
            page=4,
            bbox=[24, 18, 54, 48],
            width=30,
            height=30,
            image_bytes=PNG_BYTES,
            role="logo",
        ),
        PdfFigureCandidate(
            candidate_id="revenue-chart",
            page=4,
            bbox=[96, 180, 480, 360],
            width=384,
            height=180,
            image_bytes=PNG_BYTES,
            title="主营业务收入结构图",
        ),
    ]


def upload(client: TestClient):
    return client.post(
        "/api/uploads/annual-reports",
        files={"file": ("moutai-2024.pdf", PDF_BYTES, "application/pdf")},
    )


def insert_active_analysis_run(tmp_path: Path, file_version_id: int) -> None:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute(
            """
            insert into analysis_runs
                (file_version_id, implementation_id, status, stage, stage_history, created_at)
            values (?, ?, 'parsing', 'locating_section', '["locating_section"]', '2026-05-07 00:00:00.000000')
            """,
            (file_version_id, f"manual_active_{file_version_id}"),
        )


def latest_failed_run(tmp_path: Path, file_version_id: int) -> tuple[str, str]:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        row = connection.execute(
            """
            select error_code, error_message
            from analysis_runs
            where file_version_id = ?
            order by id desc
            limit 1
            """,
            (file_version_id,),
        ).fetchone()
    return str(row[0]), str(row[1])


def analysis_run_statuses(tmp_path: Path, file_version_id: int) -> list[str]:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        rows = connection.execute(
            """
            select status
            from analysis_runs
            where file_version_id = ?
            order by id
            """,
            (file_version_id,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def test_analyzes_text_only_mda_into_interactive_evidence_backed_report(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_with_text_only_mda_pages())
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert started.status_code == 201
    run = started.json()
    assert run["file_version_id"] == file_version_id
    assert run["status"] == "ready"
    assert run["stage"] == "completed"
    assert run["prompt_version"] == "mda_outline_v1"
    assert run["stages"] == [
        "locating_section",
        "extracting_content",
        "analyzing_figures",
        "generating_report",
        "building_qa_index",
        "completed",
    ]
    assert run["chroma_collection_name"] == run["implementation_id"]

    listed = client.get("/api/annual-reports").json()["items"]
    assert listed[0]["summary_status"] == "有报告"
    assert listed[0]["file_versions"][0]["display_status"] == "analyzed"

    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result")

    assert report.status_code == 200
    body = report.json()
    assert "markdown_report" not in body
    assert body["title"] == "管理层讨论与分析"
    assert body["labels"] == {
        "source_tree": "章节结构",
        "analysis_report": "分析报告",
        "qa_index": "问答索引",
        "evidence_package": "证据包",
    }
    assert len(body["summary"]) == 3
    assert body["source_sections"][0]["title"] == "管理层讨论与分析"
    assert body["source_sections"][0]["children"][0]["title"] == "一、经营情况讨论与分析"
    assert body["text_span_index"]["text_span_1"]["page_label"] == "PDF 第 4 页"
    assert "第四节" not in body["text_span_index"]["text_span_1"]["text"]
    assert [section["title"] for section in body["analysis_sections"]] == ["经营表现", "风险因素"]
    assert body["analysis_sections"][0]["points"][0]["evidence"][0]["page_label"] == "PDF 第 4 页"
    assert body["analysis_sections"][1]["points"][0]["evidence"][0]["page_label"] == "PDF 第 5 页"


def test_qa_indexing_failure_keeps_report_available_and_blocks_qa(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            source_pdf_dir=tmp_path / "source_pdfs",
            extractor=FakeExtractor(annual_report_with_text_only_mda_pages()),
            outline_generator=FakeOutlineGenerator(),
            qa_indexer=FailingQaIndexer(),
        )
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert started.status_code == 201
    assert started.json()["status"] == "ready"
    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result")
    assert report.status_code == 200
    assert report.json()["qa_available"] is False
    assert report.json()["qa_unavailable_reason"] == "chroma write failed"

    qa = client.post(
        f"/api/file-versions/{file_version_id}/analysis-result/qa",
        json={"question": "营业收入表现如何？"},
    )

    assert qa.status_code == 409
    assert qa.json() == {
        "error_code": "QA_INDEX_UNAVAILABLE",
        "message": "问答暂不可用",
    }
    listed_version = client.get("/api/annual-reports").json()["items"][0]["file_versions"][0]
    assert listed_version["display_status"] == "analyzed"


def test_qa_answers_from_current_evidence_or_returns_scoped_status(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_with_text_only_mda_pages())
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201

    answered = client.post(
        f"/api/file-versions/{file_version_id}/analysis-result/qa",
        json={"question": "收入增长的主要来源是什么？"},
    )

    assert answered.status_code == 200
    assert answered.json()["status"] == "answered"
    assert "核心产品销售稳定" in answered.json()["answer"]
    assert answered.json()["evidence"] == [
        {
            "content_type": "text",
            "source_section_id": "source_section_2",
            "text_span_id": "text_span_2",
            "page": 4,
            "page_label": "PDF 第 4 页",
            "evidence_text": "核心产品销售稳定，是收入增长的主要来源。",
        }
    ]

    out_of_scope = client.post(
        f"/api/file-versions/{file_version_id}/analysis-result/qa",
        json={"question": "公司治理有哪些变化？"},
    )
    insufficient = client.post(
        f"/api/file-versions/{file_version_id}/analysis-result/qa",
        json={"question": "海外渠道库存策略是什么？"},
    )

    assert out_of_scope.status_code == 200
    assert out_of_scope.json() == {
        "status": "out_of_scope",
        "answer": "当前问答仅基于第三节‘管理层讨论与分析’，无法回答该问题",
        "evidence": [],
        "prompt_version": "qa_answer_v1",
    }
    assert insufficient.status_code == 200
    assert insufficient.json() == {
        "status": "insufficient_evidence",
        "answer": "当前管理层讨论与分析证据不足，无法回答该问题",
        "evidence": [],
        "prompt_version": "qa_answer_v1",
    }


def test_qa_answers_can_cite_table_and_figure_evidence(
    tmp_path: Path,
) -> None:
    table_client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'table.db'}",
            source_pdf_dir=tmp_path / "table_pdfs",
            extractor=FakeExtractor(annual_report_with_mda_table_pages()),
            outline_generator=TableAwareOutlineGenerator(),
        )
    )
    table_upload = upload(table_client)
    assert table_upload.status_code == 201
    table_file_version_id = table_upload.json()["file_version"]["id"]
    assert table_client.post(f"/api/file-versions/{table_file_version_id}/analysis-runs").status_code == 201

    table_qa = table_client.post(
        f"/api/file-versions/{table_file_version_id}/analysis-result/qa",
        json={"question": "核心产品收入是多少？"},
    )

    assert table_qa.status_code == 200
    assert table_qa.json()["status"] == "answered"
    assert "核心产品 | 80亿元 | 12%" in table_qa.json()["answer"]
    assert table_qa.json()["evidence"][0]["content_type"] == "table"
    assert table_qa.json()["evidence"][0]["table_id"] == "table_1"

    figure_client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'figure.db'}",
            source_pdf_dir=tmp_path / "figure_pdfs",
            extractor=FakeFigureExtractor(
                annual_report_with_text_only_mda_pages(),
                mda_figure_candidates(),
            ),
            outline_generator=FigureAwareOutlineGenerator(),
            figure_visual_analyzer=RecordingFigureAnalyzer(),
            report_asset_dir=tmp_path / "report_assets",
        )
    )
    figure_upload = upload(figure_client)
    assert figure_upload.status_code == 201
    figure_file_version_id = figure_upload.json()["file_version"]["id"]
    assert figure_client.post(f"/api/file-versions/{figure_file_version_id}/analysis-runs").status_code == 201

    figure_qa = figure_client.post(
        f"/api/file-versions/{figure_file_version_id}/analysis-result/qa",
        json={"question": "收入结构图展示什么？"},
    )

    assert figure_qa.status_code == 200
    assert figure_qa.json()["status"] == "answered"
    assert "核心产品收入占比较高" in figure_qa.json()["answer"]
    assert figure_qa.json()["evidence"][0]["content_type"] == "figure_summary"
    assert figure_qa.json()["evidence"][0]["image_id"] == "image_1"


def test_qa_answer_validation_rejects_evidence_ids_outside_current_result(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            source_pdf_dir=tmp_path / "source_pdfs",
            extractor=FakeExtractor(annual_report_with_text_only_mda_pages()),
            outline_generator=FakeOutlineGenerator(),
            qa_answer_generator=InvalidQaAnswerGenerator(),
        )
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    assert client.post(f"/api/file-versions/{file_version_id}/analysis-runs").status_code == 201

    qa = client.post(
        f"/api/file-versions/{file_version_id}/analysis-result/qa",
        json={"question": "收入增长的主要来源是什么？"},
    )

    assert qa.status_code == 500
    assert qa.json() == {
        "error_code": "QA_EVIDENCE_VALIDATION_FAILED",
        "message": "问答证据校验失败",
    }


def test_table_evidence_flows_to_report_detail_asset_access_and_qa_index(
    tmp_path: Path,
) -> None:
    qa_indexer = RecordingQaIndexer()
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            source_pdf_dir=tmp_path / "source_pdfs",
            extractor=FakeExtractor(annual_report_with_mda_table_pages()),
            outline_generator=TableAwareOutlineGenerator(),
            qa_indexer=qa_indexer,
        )
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert started.status_code == 201
    analysis_run_id = started.json()["id"]
    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result")
    assert report.status_code == 200
    body = report.json()
    table_meta = body["table_index"]["table_1"]
    assert table_meta == {
        "table_id": "table_1",
        "title": "主营业务分产品情况",
        "summary": "主营业务分产品情况，共 2 行 3 列。",
        "page": 4,
        "page_label": "PDF 第 4 页",
        "source_section_id": "source_section_2",
        "columns": ["产品", "收入", "同比"],
        "row_count": 2,
        "notes": ["收入为不含税金额。"],
        "table_url": f"/api/file-versions/{file_version_id}/analysis-result/tables/table_1",
    }
    assert "rows" not in table_meta
    assert body["source_sections"][0]["children"][0]["table_ids"] == ["table_1"]
    assert body["analysis_sections"][0]["points"][0]["evidence"] == [
        {
            "content_type": "table",
            "source_section_id": "source_section_2",
            "table_id": "table_1",
            "page": 4,
            "page_label": "PDF 第 4 页",
            "evidence_text": "核心产品收入 80 亿元",
        }
    ]

    table = client.get(f"/api/file-versions/{file_version_id}/analysis-result/tables/table_1")
    assert table.status_code == 200
    assert table.json()["rows"] == [
        {"产品": "核心产品", "收入": "80亿元", "同比": "12%"},
        {"产品": "其他产品", "收入": "20亿元", "同比": "3%"},
    ]
    missing_table = client.get(f"/api/file-versions/{file_version_id}/analysis-result/tables/table_missing")
    assert missing_table.status_code == 404
    assert missing_table.json() == {
        "error_code": "TABLE_ASSET_NOT_FOUND",
        "message": "表格资源不存在",
    }

    assert len(qa_indexer.calls) == 1
    implementation_id, indexing_package = qa_indexer.calls[0]
    assert implementation_id == started.json()["implementation_id"]
    table_docs = [
        doc for doc in indexing_package["qa_index_documents"] if doc["metadata"]["content_type"] == "table"
    ]
    assert table_docs == [
        {
            "doc_id": "table_1",
            "text": (
                "表格：主营业务分产品情况\n"
                "摘要：主营业务分产品情况，共 2 行 3 列。\n"
                "列：产品，收入，同比\n"
                "核心产品 | 80亿元 | 12%\n"
                "其他产品 | 20亿元 | 3%\n"
                "注：收入为不含税金额。"
            ),
            "metadata": {
                "file_version_id": file_version_id,
                "analysis_run_id": analysis_run_id,
                "section": "ManagementDiscussionAnalysisSection",
                "source_section_id": "source_section_2",
                "subsection_title": "一、经营情况讨论与分析",
                "page": 4,
                "content_type": "table",
            },
        }
    ]


def test_mda_figure_evidence_is_filtered_asseted_and_served_through_controlled_api(
    tmp_path: Path,
) -> None:
    analyzer = RecordingFigureAnalyzer()
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        source_pdf_dir=tmp_path / "source_pdfs",
        extractor=FakeFigureExtractor(
            annual_report_with_text_only_mda_pages(),
            mda_figure_candidates(),
        ),
        outline_generator=FigureAwareOutlineGenerator(),
        figure_visual_analyzer=analyzer,
        report_asset_dir=tmp_path / "report_assets",
    )
    client = TestClient(app)
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert started.status_code == 201
    assert analyzer.seen_candidate_ids == ["revenue-chart"]
    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result")
    assert report.status_code == 200
    body = report.json()
    assert body["source_sections"][0]["children"][0]["image_ids"] == ["image_1"]
    figure = body["figure_index"]["image_1"]
    assert figure["image_id"] == "image_1"
    assert figure["page_label"] == "PDF 第 4 页"
    assert figure["bbox"] == [96, 180, 480, 360]
    assert figure["title"] == "主营业务收入结构图"
    assert figure["summary"] == "图示展示核心产品收入占比较高，与经营表现相关。"
    assert figure["relevance"] == "high"
    assert figure["thumb_url"].endswith("/figures/image_1?variant=thumb")
    assert figure["original_url"].endswith("/figures/image_1?variant=original")
    figure_evidence = body["analysis_sections"][0]["points"][0]["evidence"][0]
    assert figure_evidence == {
        "content_type": "figure_summary",
        "source_section_id": "source_section_2",
        "image_id": "image_1",
        "page": 4,
        "page_label": "PDF 第 4 页",
        "evidence_text": "核心产品收入占比较高",
        "thumb_url": figure["thumb_url"],
        "original_url": figure["original_url"],
    }

    original = client.get(figure["original_url"])
    thumb = client.get(figure["thumb_url"])
    assert original.status_code == 200
    assert thumb.status_code == 200
    assert original.content == PNG_BYTES
    assert thumb.content == PNG_BYTES


def test_visual_model_availability_is_required_only_when_mda_figures_need_analysis(
    tmp_path: Path,
) -> None:
    unavailable = UnavailableFigureAnalyzer()
    no_figure_app = create_app(
        database_url=f"sqlite:///{tmp_path / 'no_figures.db'}",
        source_pdf_dir=tmp_path / "no_figure_pdfs",
        extractor=FakeFigureExtractor(annual_report_with_text_only_mda_pages(), []),
        outline_generator=FakeOutlineGenerator(),
        figure_visual_analyzer=unavailable,
        report_asset_dir=tmp_path / "no_figure_assets",
    )
    no_figure_client = TestClient(no_figure_app)
    no_figure_upload = upload(no_figure_client)
    assert no_figure_upload.status_code == 201

    no_figure_run = no_figure_client.post(
        f"/api/file-versions/{no_figure_upload.json()['file_version']['id']}/analysis-runs"
    )

    assert no_figure_run.status_code == 201
    assert no_figure_run.json()["status"] == "ready"

    figure_app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        source_pdf_dir=tmp_path / "figure_pdfs",
        extractor=FakeFigureExtractor(
            annual_report_with_text_only_mda_pages(),
            mda_figure_candidates(),
        ),
        outline_generator=FakeOutlineGenerator(),
        figure_visual_analyzer=unavailable,
        report_asset_dir=tmp_path / "figure_assets",
    )
    figure_client = TestClient(figure_app)
    figure_upload = upload(figure_client)
    assert figure_upload.status_code == 201
    file_version_id = figure_upload.json()["file_version"]["id"]

    failed = figure_client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert failed.status_code == 422
    assert failed.json() == {
        "error_code": "VISION_MODEL_UNAVAILABLE",
        "message": "视觉模型不可用，无法分析管理层讨论与分析中的图表",
    }
    assert unavailable.call_count == 0
    assert latest_failed_run(tmp_path, file_version_id) == (
        "VISION_MODEL_UNAVAILABLE",
        "视觉模型不可用，无法分析管理层讨论与分析中的图表",
    )


def test_mda_table_parsing_failure_is_audited_with_table_analysis_failed(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        annual_report_with_malformed_mda_table_pages(),
        outline_generator=FakeOutlineGenerator(),
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    failed = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert failed.status_code == 422
    assert failed.json() == {
        "error_code": "TABLE_ANALYSIS_FAILED",
        "message": "管理层讨论与分析中的表格无法识别",
    }
    assert latest_failed_run(tmp_path, file_version_id) == (
        "TABLE_ANALYSIS_FAILED",
        "管理层讨论与分析中的表格无法识别",
    )


def test_invalid_table_references_are_retried_once_then_rejected(
    tmp_path: Path,
) -> None:
    generator = InvalidTableReferenceOutlineGenerator()
    client = make_client(
        tmp_path,
        annual_report_with_mda_table_pages(),
        outline_generator=generator,
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    failed = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert failed.status_code == 422
    assert failed.json() == {
        "error_code": "ANALYSIS_OUTPUT_INVALID_TABLE_REFERENCE",
        "message": "分析结果引用了不存在的表格",
    }
    assert len(generator.calls) == 2
    assert generator.calls[0] is None
    assert generator.calls[1] == ["unknown table_id table_missing"]


def test_invalid_figure_references_are_retried_once_then_rejected(
    tmp_path: Path,
) -> None:
    generator = InvalidFigureReferenceOutlineGenerator()
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            source_pdf_dir=tmp_path / "source_pdfs",
            extractor=FakeFigureExtractor(
                annual_report_with_text_only_mda_pages(),
                mda_figure_candidates(),
            ),
            outline_generator=generator,
            figure_visual_analyzer=RecordingFigureAnalyzer(),
            report_asset_dir=tmp_path / "report_assets",
        )
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    failed = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert failed.status_code == 422
    assert failed.json() == {
        "error_code": "ANALYSIS_OUTPUT_INVALID_FIGURE_REFERENCE",
        "message": "分析结果引用了不存在的图",
    }
    assert len(generator.calls) == 2
    assert generator.calls[0] is None
    assert generator.calls[1] == ["unknown image_id image_missing"]


def test_figure_asset_promotion_failure_rolls_back_promoted_assets_and_audits_run(
    tmp_path: Path,
) -> None:
    asset_store = FailingPromotionFigureAssetStore(tmp_path / "report_assets")
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            source_pdf_dir=tmp_path / "source_pdfs",
            extractor=FakeFigureExtractor(
                annual_report_with_text_only_mda_pages(),
                mda_figure_candidates(),
            ),
            outline_generator=FigureAwareOutlineGenerator(),
            figure_visual_analyzer=RecordingFigureAnalyzer(),
            figure_asset_store=asset_store,
        )
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    failed = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert failed.status_code == 500
    assert failed.json() == {
        "error_code": "REPORT_ASSET_COMMIT_FAILED",
        "message": "报告资源保存失败",
    }
    assert asset_store.promoted_ids
    implementation_id = asset_store.promoted_ids[0]
    assert implementation_id in asset_store.cleaned_ids
    assert not (tmp_path / "report_assets" / implementation_id).exists()
    assert client.get(f"/api/file-versions/{file_version_id}/analysis-result").status_code == 404
    assert latest_failed_run(tmp_path, file_version_id) == (
        "REPORT_ASSET_COMMIT_FAILED",
        "报告资源保存失败",
    )


def test_low_relevance_figures_are_retained_as_other_figures_not_main_evidence(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            source_pdf_dir=tmp_path / "source_pdfs",
            extractor=FakeFigureExtractor(
                annual_report_with_text_only_mda_pages(),
                mda_figure_candidates(),
            ),
            outline_generator=FakeOutlineGenerator(),
            figure_visual_analyzer=LowRelevanceFigureAnalyzer(),
            report_asset_dir=tmp_path / "report_assets",
        )
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201

    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result")

    assert report.status_code == 200
    body = report.json()
    assert list(body["figure_index"]) == ["image_1"]
    assert body["other_figures"] == [body["figure_index"]["image_1"]]
    assert body["other_figures"][0]["summary"] == "图片展示产品外观，但不直接支持经营或财务分析。"
    all_evidence = [
        evidence
        for section in body["analysis_sections"]
        for point in section["points"]
        for evidence in point["evidence"]
    ]
    assert all(evidence["content_type"] != "figure_summary" for evidence in all_evidence)


def test_thumbnail_generation_failure_keeps_analysis_ready_when_original_asset_exists(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            source_pdf_dir=tmp_path / "source_pdfs",
            extractor=FakeFigureExtractor(
                annual_report_with_text_only_mda_pages(),
                mda_figure_candidates(),
            ),
            outline_generator=FigureAwareOutlineGenerator(),
            figure_visual_analyzer=RecordingFigureAnalyzer(),
            figure_asset_store=FailingThumbnailFigureAssetStore(tmp_path / "report_assets"),
        )
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert started.status_code == 201
    assert started.json()["status"] == "ready"
    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result").json()
    figure = report["figure_index"]["image_1"]
    assert figure["thumbnail"] == figure["original"]
    assert client.get(figure["original_url"]).content == PNG_BYTES
    assert client.get(figure["thumb_url"]).content == PNG_BYTES


def test_report_detail_keeps_large_table_rows_on_demand(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        annual_report_with_large_mda_table_pages(),
        outline_generator=TableAwareOutlineGenerator(),
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201

    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result")

    assert report.status_code == 200
    table_meta = report.json()["table_index"]["table_1"]
    assert table_meta["row_count"] == 120
    assert "rows" not in table_meta
    assert "产品120" not in report.text

    table = client.get(table_meta["table_url"])
    assert table.status_code == 200
    assert table.json()["rows"][-1] == {"产品": "产品120", "收入": "120亿元", "同比": "120%"}


def test_markdown_download_renders_current_analysis_result_from_structured_outline(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_with_text_only_mda_pages())
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201

    downloaded = client.get(
        f"/api/file-versions/{file_version_id}/analysis-result/download?format=markdown"
    )

    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("text/markdown")
    assert "attachment" in downloaded.headers["content-disposition"]
    body = downloaded.text
    assert "# 管理层讨论与分析" in body
    assert "公司围绕主营业务披露了经营表现。" in body
    assert "## 经营表现" in body
    assert "公司营业收入保持增长，主要来自核心产品销售。" in body
    assert "证据" in body
    assert "营业收入同比增长" in body
    assert "PDF 第 4 页" in body
    assert "公司治理" not in body
    assert "这个无证据观点应由后端丢弃" not in body
    assert "未披露主题" not in body


def test_zip_download_includes_markdown_and_structured_table_json(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        annual_report_with_mda_table_pages(),
        outline_generator=TableAwareOutlineGenerator(),
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201

    downloaded = client.get(
        f"/api/file-versions/{file_version_id}/analysis-result/download?format=zip"
    )

    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = set(archive.namelist())
        assert "report.md" in names
        assert "tables/table_1.json" in names
        assert all(not name.startswith("/") for name in names)
        assert all(".." not in name.split("/") for name in names)
        markdown = archive.read("report.md").decode("utf-8")
        assert "主营业务分产品情况" in markdown
        assert "请下载 ZIP 以保留完整结构化表格数据" in markdown
        assert "`tables/table_1.json`" in markdown
        assert "PDF 第 4 页" in markdown
        table = json.loads(archive.read("tables/table_1.json").decode("utf-8"))
    assert table["table_id"] == "table_1"
    assert table["rows"] == [
        {"产品": "核心产品", "收入": "80亿元", "同比": "12%"},
        {"产品": "其他产品", "收入": "20亿元", "同比": "3%"},
    ]


def test_zip_download_includes_markdown_and_original_figure_assets(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            source_pdf_dir=tmp_path / "source_pdfs",
            extractor=FakeFigureExtractor(
                annual_report_with_text_only_mda_pages(),
                mda_figure_candidates(),
            ),
            outline_generator=FigureAwareOutlineGenerator(),
            figure_visual_analyzer=RecordingFigureAnalyzer(),
            report_asset_dir=tmp_path / "report_assets",
        )
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201

    downloaded = client.get(
        f"/api/file-versions/{file_version_id}/analysis-result/download?format=zip"
    )

    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = set(archive.namelist())
        assert "report.md" in names
        assert "figures/image_1.png" in names
        assert archive.read("figures/image_1.png") == PNG_BYTES
        markdown = archive.read("report.md").decode("utf-8")
    assert "![主营业务收入结构图](figures/image_1.png)" in markdown
    assert "请下载 ZIP 以保留完整离线图片" in markdown
    assert "`image_1`" in markdown
    assert "PDF 第 4 页" in markdown


def test_report_download_rejects_wrong_owner_and_unsupported_format(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_with_text_only_mda_pages())
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201

    wrong_owner = client.get(
        f"/api/file-versions/{file_version_id + 999}/analysis-result/download?format=markdown"
    )
    unsupported = client.get(
        f"/api/file-versions/{file_version_id}/analysis-result/download?format=pdf"
    )

    assert wrong_owner.status_code == 404
    assert wrong_owner.json() == {
        "error_code": "FILE_VERSION_NOT_FOUND",
        "message": "文件版本不存在",
    }
    assert unsupported.status_code == 400
    assert unsupported.json() == {
        "error_code": "UNSUPPORTED_REPORT_DOWNLOAD_FORMAT",
        "message": "不支持的报告下载格式",
    }


def test_report_download_generation_failures_use_stable_error_codes(
    tmp_path: Path,
) -> None:
    class FailingDownloads:
        def render_markdown(self, _result) -> str:
            raise RuntimeError("markdown failed")

        def build_zip(self, _result) -> bytes:
            raise RuntimeError("zip failed")

    client = make_client(tmp_path, annual_report_with_text_only_mda_pages())
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201
    client.app.state.report_downloads = FailingDownloads()
    client.app.state.current_analysis_result_access.report_downloads = (
        client.app.state.report_downloads
    )

    markdown = client.get(
        f"/api/file-versions/{file_version_id}/analysis-result/download?format=markdown"
    )
    zipped = client.get(
        f"/api/file-versions/{file_version_id}/analysis-result/download?format=zip"
    )

    assert markdown.status_code == 500
    assert markdown.json() == {
        "error_code": "REPORT_MARKDOWN_GENERATION_FAILED",
        "message": "分析报告 Markdown 生成失败",
    }
    assert zipped.status_code == 500
    assert zipped.json() == {
        "error_code": "REPORT_ZIP_GENERATION_FAILED",
        "message": "分析报告 ZIP 生成失败",
    }


def test_analysis_result_read_routes_delegate_to_current_access_module(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_with_text_only_mda_pages())
    figure_path = tmp_path / "figure.png"
    figure_path.write_bytes(PNG_BYTES)

    class RecordingAccess:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def report_detail(self, session, *, file_version_id: int) -> dict:
            self.calls.append(("report_detail", file_version_id))
            return {
                "file_version_id": file_version_id,
                "analysis_run_id": 11,
                "title": "管理层讨论与分析",
                "prompt_version": "mda_outline_v1",
                "summary": ["第一句。", "第二句。", "第三句。"],
                "source_sections": [],
                "text_span_index": {},
                "table_index": {},
                "figure_index": {},
                "other_figures": [],
                "analysis_sections": [],
                "qa_available": True,
                "qa_unavailable_reason": None,
                "labels": {
                    "source_tree": "章节结构",
                    "analysis_report": "分析报告",
                    "qa_index": "问答索引",
                    "evidence_package": "证据包",
                },
            }

        def answer_question(self, session, *, file_version_id: int, question: str) -> dict:
            self.calls.append(("answer_question", file_version_id, question))
            return {
                "status": "answered",
                "answer": "已通过 facade 处理。",
                "evidence": [],
                "prompt_version": "qa_answer_v1",
            }

        def download(
            self,
            session,
            *,
            file_version_id: int,
            format: str,
        ) -> DownloadedAnalysisResult:
            self.calls.append(("download", file_version_id, format))
            if format == "markdown":
                return DownloadedAnalysisResult(
                    content="# delegated\n",
                    media_type="text/markdown; charset=utf-8",
                    filename="delegated.md",
                )
            return DownloadedAnalysisResult(
                content=b"PK\x03\x04delegated",
                media_type="application/zip",
                filename="delegated.zip",
            )

        def table_asset(self, session, *, file_version_id: int, table_id: str) -> dict:
            self.calls.append(("table_asset", file_version_id, table_id))
            return {
                "table_id": table_id,
                "title": "主营业务分产品情况",
                "summary": "主营业务分产品情况，共 1 行 2 列。",
                "page": 4,
                "page_label": "PDF 第 4 页",
                "source_section_id": "source_section_2",
                "columns": ["产品", "收入"],
                "rows": [{"产品": "核心产品", "收入": "80亿元"}],
                "notes": [],
                "metadata": {"row_count": 1, "column_count": 2},
                "source_bbox": None,
            }

        def figure_asset(
            self,
            session,
            *,
            file_version_id: int,
            image_id: str,
            variant: str,
        ) -> ResolvedFigureAsset:
            self.calls.append(("figure_asset", file_version_id, image_id, variant))
            return ResolvedFigureAsset(path=figure_path, content_type="image/png")

    access = RecordingAccess()
    client.app.state.current_analysis_result_access = access

    report = client.get("/api/file-versions/7/analysis-result")
    qa = client.post(
        "/api/file-versions/7/analysis-result/qa",
        json={"question": "核心产品收入怎么样？"},
    )
    markdown = client.get("/api/file-versions/7/analysis-result/download?format=markdown")
    table = client.get("/api/file-versions/7/analysis-result/tables/table_1")
    figure = client.get("/api/file-versions/7/analysis-result/figures/image_1?variant=thumb")

    assert report.status_code == 200
    assert report.json()["analysis_run_id"] == 11
    assert qa.status_code == 200
    assert qa.json()["answer"] == "已通过 facade 处理。"
    assert markdown.status_code == 200
    assert markdown.text == "# delegated\n"
    assert markdown.headers["content-disposition"] == 'attachment; filename="delegated.md"'
    assert table.status_code == 200
    assert table.json()["table_id"] == "table_1"
    assert figure.status_code == 200
    assert figure.content == PNG_BYTES
    assert access.calls == [
        ("report_detail", 7),
        ("answer_question", 7, "核心产品收入怎么样？"),
        ("download", 7, "markdown"),
        ("table_asset", 7, "table_1"),
        ("figure_asset", 7, "image_1", "thumb"),
    ]


def test_analysis_start_rejects_same_file_version_concurrency_and_product_limit(
    tmp_path: Path,
) -> None:
    same_file_client = make_client(tmp_path / "same", annual_report_with_text_only_mda_pages())
    uploaded = upload(same_file_client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    insert_active_analysis_run(tmp_path / "same", file_version_id)

    duplicate_start = same_file_client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert duplicate_start.status_code == 409
    assert duplicate_start.json() == {
        "error_code": "ANALYSIS_ALREADY_IN_PROGRESS",
        "message": "该文件版本已有分析正在进行",
    }

    limited_client = make_limited_client(
        tmp_path / "limit",
        annual_report_with_text_only_mda_pages(),
        concurrency_limit=1,
    )
    first = upload(limited_client)
    second = limited_client.post(
        "/api/uploads/annual-reports",
        files={"file": ("moutai-revised.pdf", b"%PDF-1.7\nsecond", "application/pdf")},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    insert_active_analysis_run(tmp_path / "limit", first.json()["file_version"]["id"])

    limited = limited_client.post(f"/api/file-versions/{second.json()['file_version']['id']}/analysis-runs")

    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "30"
    assert limited.json() == {
        "error_code": "ANALYSIS_CONCURRENCY_LIMIT_REACHED",
        "message": "当前分析任务较多，请稍后再试",
    }


def test_stop_current_analysis_marks_run_stopped_and_cleans_intermediate_artifacts(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_with_text_only_mda_pages())
    cleaner = RecordingResourceCleaner()
    client.app.state.mda_analysis.resource_cleaner = cleaner
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    insert_active_analysis_run(tmp_path, file_version_id)

    stopped = client.post(f"/api/file-versions/{file_version_id}/analysis-runs/stop")

    assert stopped.status_code == 200
    run = stopped.json()
    assert run["file_version_id"] == file_version_id
    assert run["status"] == "stopped"
    assert run["error_code"] is None
    assert cleaner.cleaned_implementation_ids == [f"manual_active_{file_version_id}"]
    listed_version = client.get("/api/annual-reports").json()["items"][0]["file_versions"][0]
    assert listed_version["display_status"] == "stopped"
    assert listed_version["display_status_message"] is None


def test_cancellation_checkpoint_prevents_later_model_and_index_calls(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    extractor = StopAfterExtractionExtractor(db_path, annual_report_with_text_only_mda_pages())
    generator = CountingOutlineGenerator()
    qa_indexer = CountingQaIndexer()
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{db_path}",
            source_pdf_dir=tmp_path / "source_pdfs",
            extractor=extractor,
            outline_generator=generator,
            qa_indexer=qa_indexer,
        )
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    extractor.stop_during_next_extract = True

    stopped = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert stopped.status_code == 201
    assert stopped.json()["status"] == "stopped"
    assert extractor.stop_updates == 1
    assert generator.call_count == 0
    assert qa_indexer.call_count == 0
    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result")
    assert report.status_code == 404


def test_delete_current_analysis_result_marks_run_deleted_and_allows_reanalysis(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_with_text_only_mda_pages())
    cleaner = RecordingResourceCleaner()
    client.app.state.mda_analysis.resource_cleaner = cleaner
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    first_run = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert first_run.status_code == 201
    first_implementation_id = first_run.json()["implementation_id"]

    deleted = client.delete(f"/api/file-versions/{file_version_id}/analysis-result")

    assert deleted.status_code == 200
    deleted_run = deleted.json()
    assert deleted_run["status"] == "result_deleted"
    assert cleaner.cleaned_implementation_ids == [first_implementation_id]
    assert client.get(f"/api/file-versions/{file_version_id}/analysis-result").status_code == 404
    listed_version = client.get("/api/annual-reports").json()["items"][0]["file_versions"][0]
    assert listed_version["display_status"] == "not_analyzed"

    second_run = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert second_run.status_code == 201
    assert second_run.json()["status"] == "ready"
    assert second_run.json()["implementation_id"] != first_implementation_id
    assert analysis_run_statuses(tmp_path, file_version_id) == ["result_deleted", "ready"]


def test_failed_and_stopped_file_versions_can_retry_with_historical_runs_retained(
    tmp_path: Path,
) -> None:
    failed_client = make_client(
        tmp_path / "failed",
        annual_report_with_text_only_mda_pages()[:-1],
    )
    failed_upload = upload(failed_client)
    assert failed_upload.status_code == 201
    failed_file_version_id = failed_upload.json()["file_version"]["id"]
    failed = failed_client.post(f"/api/file-versions/{failed_file_version_id}/analysis-runs")
    assert failed.status_code == 422
    failed_client.app.state.mda_analysis.extractor.pages = annual_report_with_text_only_mda_pages()

    failed_retry = failed_client.post(f"/api/file-versions/{failed_file_version_id}/analysis-runs")

    assert failed_retry.status_code == 201
    assert failed_retry.json()["status"] == "ready"
    assert analysis_run_statuses(tmp_path / "failed", failed_file_version_id) == ["failed", "ready"]

    stopped_client = make_client(tmp_path / "stopped", annual_report_with_text_only_mda_pages())
    stopped_upload = upload(stopped_client)
    assert stopped_upload.status_code == 201
    stopped_file_version_id = stopped_upload.json()["file_version"]["id"]
    insert_active_analysis_run(tmp_path / "stopped", stopped_file_version_id)
    stopped = stopped_client.post(f"/api/file-versions/{stopped_file_version_id}/analysis-runs/stop")
    assert stopped.status_code == 200

    stopped_retry = stopped_client.post(f"/api/file-versions/{stopped_file_version_id}/analysis-runs")

    assert stopped_retry.status_code == 201
    assert stopped_retry.json()["status"] == "ready"
    assert analysis_run_statuses(tmp_path / "stopped", stopped_file_version_id) == [
        "stopped",
        "ready",
    ]


def test_current_analysis_result_blocks_reanalysis_until_deleted(tmp_path: Path) -> None:
    client = make_client(tmp_path, annual_report_with_text_only_mda_pages())
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    first_run = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert first_run.status_code == 201

    guarded = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert guarded.status_code == 409
    assert guarded.json() == {
        "error_code": "ANALYSIS_RESULT_ALREADY_EXISTS",
        "message": "该文件版本已有分析报告，请先删除后再重新分析",
    }


def test_stop_failures_use_stable_error_codes(tmp_path: Path) -> None:
    no_active_client = make_client(tmp_path / "no_active", annual_report_with_text_only_mda_pages())
    uploaded = upload(no_active_client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    no_active = no_active_client.post(f"/api/file-versions/{file_version_id}/analysis-runs/stop")

    assert no_active.status_code == 409
    assert no_active.json() == {
        "error_code": "STOP_ANALYSIS_FAILED",
        "message": "停止分析失败",
    }

    cleanup_failure_client = make_client(
        tmp_path / "cleanup_failure",
        annual_report_with_text_only_mda_pages(),
    )
    cleanup_failure_client.app.state.mda_analysis.resource_cleaner = FailingResourceCleaner()
    cleanup_upload = upload(cleanup_failure_client)
    assert cleanup_upload.status_code == 201
    cleanup_file_version_id = cleanup_upload.json()["file_version"]["id"]
    insert_active_analysis_run(tmp_path / "cleanup_failure", cleanup_file_version_id)

    cleanup_failure = cleanup_failure_client.post(
        f"/api/file-versions/{cleanup_file_version_id}/analysis-runs/stop"
    )

    assert cleanup_failure.status_code == 500
    assert cleanup_failure.json() == {
        "error_code": "STOP_ANALYSIS_CLEANUP_FAILED",
        "message": "停止分析时清理中间结果失败",
    }
    assert latest_failed_run(tmp_path / "cleanup_failure", cleanup_file_version_id) == (
        "STOP_ANALYSIS_CLEANUP_FAILED",
        "停止分析时清理中间结果失败",
    )


def test_mda_section_location_and_text_extraction_failures_are_audited(
    tmp_path: Path,
) -> None:
    cases = [
        (
            "missing",
            [
                "贵州茅台酒股份有限公司\n2024 年年度报告",
                "目录\n公司简介和主要财务指标 3",
                "\n".join(
                    [
                        "第二节 公司简介和主要财务指标",
                        "公司全称：贵州茅台酒股份有限公司",
                        "公司简称：贵州茅台",
                        "股票代码：600519",
                        "主要会计数据日期：2024年12月31日",
                    ]
                ),
                "第四节 公司治理",
            ],
            "MD_A_SECTION_NOT_FOUND",
            "无法定位管理层讨论与分析",
        ),
        (
            "start_unverified",
            [
                "贵州茅台酒股份有限公司\n2024 年年度报告",
                "目录\n公司简介和主要财务指标 3\n管理层讨论与分析 4",
                "\n".join(
                    [
                        "第二节 公司简介和主要财务指标",
                        "公司全称：贵州茅台酒股份有限公司",
                        "公司简称：贵州茅台",
                        "股票代码：600519",
                        "主要会计数据日期：2024年12月31日",
                    ]
                ),
                "这里不是第三节正文",
                "第三节 管理层讨论与分析",
                "第四节 公司治理",
            ],
            "MD_A_SECTION_START_UNVERIFIED",
            "无法验证管理层讨论与分析起始位置",
        ),
        (
            "end_missing",
            annual_report_with_text_only_mda_pages()[:-1],
            "MD_A_SECTION_END_NOT_FOUND",
            "无法确定管理层讨论与分析结束位置",
        ),
        (
            "no_text",
            [
                "贵州茅台酒股份有限公司\n2024 年年度报告",
                "目录\n公司简介和主要财务指标 3\n管理层讨论与分析 4",
                "\n".join(
                    [
                        "第二节 公司简介和主要财务指标",
                        "公司全称：贵州茅台酒股份有限公司",
                        "公司简称：贵州茅台",
                        "股票代码：600519",
                        "主要会计数据日期：2024年12月31日",
                    ]
                ),
                "第三节 管理层讨论与分析",
                "第四节 公司治理",
            ],
            "MD_A_TEXT_EXTRACTION_FAILED",
            "管理层讨论与分析中的文本无法识别",
        ),
    ]

    for name, pages, error_code, message in cases:
        client = make_client(tmp_path / name, pages)
        uploaded = upload(client)
        assert uploaded.status_code == 201
        file_version_id = uploaded.json()["file_version"]["id"]

        failed = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

        assert failed.status_code == 422
        assert failed.json() == {"error_code": error_code, "message": message}
        assert latest_failed_run(tmp_path / name, file_version_id) == (error_code, message)
        listed_version = client.get("/api/annual-reports").json()["items"][0]["file_versions"][0]
        assert listed_version["display_status"] == "analysis_failed"
        assert listed_version["display_status_message"] == message


def test_structured_outline_validation_retries_schema_errors_once(
    tmp_path: Path,
) -> None:
    generator = RetryingOutlineGenerator()
    client = make_client(
        tmp_path,
        annual_report_with_text_only_mda_pages(),
        outline_generator=generator,
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201

    started = client.post(f"/api/file-versions/{uploaded.json()['file_version']['id']}/analysis-runs")

    assert started.status_code == 201
    assert len(generator.calls) == 2
    assert generator.calls[0] is None
    assert generator.calls[1] == [
        "summary must contain 3 to 5 non-empty sentences",
    ]
    report = client.get(
        f"/api/file-versions/{uploaded.json()['file_version']['id']}/analysis-result"
    ).json()
    assert report["analysis_sections"][0]["points"][0]["text"] == "重试后返回可验证观点。"


def test_analysis_output_with_no_valid_evidence_fails_without_saving_report(
    tmp_path: Path,
) -> None:
    generator = EvidenceFreeOutlineGenerator()
    client = make_client(
        tmp_path,
        annual_report_with_text_only_mda_pages(),
        outline_generator=generator,
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    failed = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert failed.status_code == 422
    assert failed.json() == {
        "error_code": "ANALYSIS_OUTPUT_NO_VALID_EVIDENCE",
        "message": "分析结果缺少可验证证据",
    }
    assert generator.call_count == 1
    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result")
    assert report.status_code == 404
    assert report.json() == {
        "error_code": "ANALYSIS_RESULT_NOT_FOUND",
        "message": "该文件版本暂无分析报告",
    }


def test_invalid_model_asset_references_are_retried_once_then_fail_with_specific_error(
    tmp_path: Path,
) -> None:
    generator = InvalidAssetOutlineGenerator()
    client = make_client(
        tmp_path,
        annual_report_with_text_only_mda_pages(),
        outline_generator=generator,
    )
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]

    failed = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")

    assert failed.status_code == 422
    assert failed.json() == {
        "error_code": "ANALYSIS_OUTPUT_INVALID_ASSET_REFERENCE",
        "message": "分析结果引用了不存在的图表资源",
    }
    assert len(generator.calls) == 2
    assert generator.calls[0] is None
    assert generator.calls[1] == ["unknown table_id table_missing", "unknown image_id image_missing"]
