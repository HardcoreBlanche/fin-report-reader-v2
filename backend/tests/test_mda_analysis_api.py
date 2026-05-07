from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.pdf_extraction import PdfTextDocument


PDF_BYTES = b"%PDF-1.7\ntext only mda bytes"


class FakeExtractor:
    def __init__(self, pages: list[str]):
        self.pages = pages

    def extract_text(self, _content: bytes) -> PdfTextDocument:
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
