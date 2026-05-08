import io
import sqlite3
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.pdf_extraction import PdfTextDocument


PDF_V1_BYTES = b"%PDF-1.7\nmocked ci journey v1"
PDF_V2_BYTES = b"%PDF-1.7\nmocked ci journey v2"


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
        revenue_section_id = revenue_span["source_section_id"]
        risk_section_id = risk_span["source_section_id"]
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
                            "source_section_ids": [revenue_section_id],
                            "evidence": [
                                {
                                    "content_type": "text",
                                    "source_section_id": revenue_section_id,
                                    "text_span_id": revenue_span["text_span_id"],
                                    "evidence_text": "营业收入同比增长",
                                }
                            ],
                        }
                    ],
                },
                {
                    "title": "风险因素",
                    "points": [
                        {
                            "text": "原材料价格波动可能影响成本控制。",
                            "source_section_ids": [risk_section_id],
                            "evidence": [
                                {
                                    "content_type": "text",
                                    "source_section_id": risk_section_id,
                                    "text_span_id": risk_span["text_span_id"],
                                    "evidence_text": "原材料价格波动",
                                }
                            ],
                        }
                    ],
                },
            ],
        }


def annual_report_pages(*, summary: bool = False) -> list[str]:
    first_page = "贵州茅台酒股份有限公司\n2024 年年度报告"
    if summary:
        first_page = "贵州茅台酒股份有限公司\n2024 年年度报告摘要"
    return [
        first_page,
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


def make_client(tmp_path: Path, pages: list[str]) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        source_pdf_dir=tmp_path / "source_pdfs",
        extractor=FakeExtractor(pages),
        outline_generator=FakeOutlineGenerator(),
    )
    return TestClient(app)


def upload(client: TestClient, *, filename: str, content: bytes):
    return client.post(
        "/api/uploads/annual-reports",
        files={"file": (filename, content, "application/pdf")},
    )


def insert_active_analysis_run(tmp_path: Path, file_version_id: int) -> None:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute(
            """
            insert into analysis_runs
                (file_version_id, implementation_id, status, stage, stage_history, created_at)
            values (?, ?, 'parsing', 'locating_section', '["locating_section"]', '2026-05-08 00:00:00.000000')
            """,
            (file_version_id, f"mocked_active_{file_version_id}"),
        )


def test_mocked_ci_journey_covers_complete_annual_report_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path, annual_report_pages())

    accepted_v1 = upload(client, filename="moutai-v1.pdf", content=PDF_V1_BYTES)
    assert accepted_v1.status_code == 201
    assert accepted_v1.json()["annual_report_already_exists"] is False
    annual_report_id = accepted_v1.json()["annual_report"]["id"]
    first_file_version_id = accepted_v1.json()["file_version"]["id"]

    duplicate = upload(client, filename="moutai-duplicate.pdf", content=PDF_V1_BYTES)
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "DUPLICATE_FILE_VERSION"
    assert duplicate.json()["details"]["file_version"]["id"] == first_file_version_id

    accepted_v2 = upload(client, filename="moutai-v2.pdf", content=PDF_V2_BYTES)
    assert accepted_v2.status_code == 201
    assert accepted_v2.json()["annual_report_already_exists"] is True
    second_file_version_id = accepted_v2.json()["file_version"]["id"]

    listed_after_uploads = client.get("/api/annual-reports")
    assert listed_after_uploads.status_code == 200
    reports = listed_after_uploads.json()["items"]
    assert len(reports) == 1
    assert reports[0]["id"] == annual_report_id
    selected_file_version = next(
        version for version in reports[0]["file_versions"] if version["id"] == second_file_version_id
    )
    assert selected_file_version["display_status"] == "not_analyzed"

    started = client.post(f"/api/file-versions/{second_file_version_id}/analysis-runs")
    assert started.status_code == 201
    run = started.json()
    assert run["status"] == "ready"
    assert run["stage"] == "completed"
    assert run["stages"] == [
        "locating_section",
        "extracting_content",
        "analyzing_figures",
        "generating_report",
        "building_qa_index",
        "completed",
    ]

    report_detail = client.get(f"/api/file-versions/{second_file_version_id}/analysis-result")
    assert report_detail.status_code == 200
    report_body = report_detail.json()
    assert report_body["file_version_id"] == second_file_version_id
    assert report_body["title"] == "管理层讨论与分析"
    assert report_body["analysis_sections"][0]["title"] == "经营表现"

    markdown_download = client.get(
        f"/api/file-versions/{second_file_version_id}/analysis-result/download?format=markdown"
    )
    assert markdown_download.status_code == 200
    markdown_text = markdown_download.content.decode("utf-8")
    assert "公司围绕主营业务披露了经营表现" in markdown_text

    zip_download = client.get(
        f"/api/file-versions/{second_file_version_id}/analysis-result/download?format=zip"
    )
    assert zip_download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_download.content)) as archive:
        assert "report.md" in set(archive.namelist())

    qa_answer = client.post(
        f"/api/file-versions/{second_file_version_id}/analysis-result/qa",
        json={"question": "收入增长的主要来源是什么？"},
    )
    assert qa_answer.status_code == 200
    assert qa_answer.json()["status"] == "answered"

    deleted_result = client.delete(f"/api/file-versions/{second_file_version_id}/analysis-result")
    assert deleted_result.status_code == 200
    assert deleted_result.json()["status"] == "result_deleted"

    missing_result = client.get(f"/api/file-versions/{second_file_version_id}/analysis-result")
    assert missing_result.status_code == 404
    assert missing_result.json() == {
        "error_code": "ANALYSIS_RESULT_NOT_FOUND",
        "message": "该文件版本暂无分析报告",
    }

    insert_active_analysis_run(tmp_path, first_file_version_id)
    stopped = client.post(f"/api/file-versions/{first_file_version_id}/analysis-runs/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"

    retried = client.post(f"/api/file-versions/{first_file_version_id}/analysis-runs")
    assert retried.status_code == 201
    assert retried.json()["status"] == "ready"

    file_version_confirmation = client.get(
        f"/api/file-versions/{first_file_version_id}/delete-confirmation"
    )
    assert file_version_confirmation.status_code == 200
    assert file_version_confirmation.json()["will_delete_annual_report"] is False

    deleted_file_version = client.delete(f"/api/file-versions/{first_file_version_id}?confirm=true")
    assert deleted_file_version.status_code == 200
    assert deleted_file_version.json()["deleted_annual_report_id"] is None

    annual_report_confirmation = client.get(
        f"/api/annual-reports/{annual_report_id}/delete-confirmation"
    )
    assert annual_report_confirmation.status_code == 200
    assert annual_report_confirmation.json()["file_version_count"] == 1

    deleted_annual_report = client.delete(f"/api/annual-reports/{annual_report_id}?confirm=true")
    assert deleted_annual_report.status_code == 200
    assert deleted_annual_report.json() == {
        "annual_report_id": annual_report_id,
        "deleted_file_version_count": 1,
        "deleted_analysis_result_count": 0,
    }

    listed_after_cleanup = client.get("/api/annual-reports")
    assert listed_after_cleanup.status_code == 200
    assert listed_after_cleanup.json() == {"items": []}


def test_mocked_ci_rejects_annual_report_summary_with_stable_error_contract(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_pages(summary=True))

    rejected = upload(client, filename="moutai-summary.pdf", content=PDF_V1_BYTES)

    assert rejected.status_code == 422
    assert rejected.json() == {
        "error_code": "ANNUAL_REPORT_SUMMARY_NOT_SUPPORTED",
        "message": "当前仅支持完整年度报告，不支持年度报告摘要",
    }
    listed = client.get("/api/annual-reports")
    assert listed.status_code == 200
    assert listed.json() == {"items": []}
