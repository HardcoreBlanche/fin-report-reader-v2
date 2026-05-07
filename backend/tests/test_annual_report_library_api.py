from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.pdf_extraction import PdfTextDocument


PDF_BYTES = b"%PDF-1.7\nannual report library bytes"


class FakeExtractor:
    def __init__(self, pages: list[str]):
        self.pages = pages

    def extract_text(self, _content: bytes) -> PdfTextDocument:
        return PdfTextDocument(self.pages)


def make_client(tmp_path: Path, pages: list[str]) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        source_pdf_dir=tmp_path / "source_pdfs",
        extractor=FakeExtractor(pages),
    )
    return TestClient(app)


def first_page(company_name: str = "贵州茅台酒股份有限公司", year: int = 2024) -> str:
    return f"{company_name}\n{year} 年年度报告"


def company_profile_section(
    *,
    company_full_name: str = "贵州茅台酒股份有限公司",
    company_short_name: str | None = "贵州茅台",
    stock_lines: str = "股票代码：600519",
    date_line: str = "主要会计数据日期：2024年12月31日",
) -> str:
    short_name_line = f"公司简称：{company_short_name}" if company_short_name else ""
    return "\n".join(
        line
        for line in [
            "第二节 公司简介和主要财务指标",
            f"公司全称：{company_full_name}",
            short_name_line,
            stock_lines,
            date_line,
        ]
        if line
    )


def annual_report_pages(
    *,
    first_page_text: str | None = None,
    profile_text: str | None = None,
) -> list[str]:
    return [
        first_page_text or first_page(),
        "目录\n公司简介和主要财务指标 3",
        profile_text or company_profile_section(),
    ]


def upload(client: TestClient, filename: str = "annual-report.pdf", content: bytes = PDF_BYTES):
    return client.post(
        "/api/uploads/annual-reports",
        files={"file": (filename, content, "application/pdf")},
    )


def mark_file_version_deleted(tmp_path: Path, file_version_id: int) -> None:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute("update file_versions set is_deleted = 1 where id = ?", (file_version_id,))
        connection.execute(
            "delete from active_content_hashes where file_version_id = ?",
            (file_version_id,),
        )


def insert_analysis_run(
    tmp_path: Path,
    *,
    file_version_id: int,
    status: str,
    error_message: str | None = None,
) -> int:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        cursor = connection.execute(
            """
            insert into analysis_runs
                (file_version_id, implementation_id, status, stage, stage_history, error_message, created_at)
            values (?, ?, ?, ?, '[]', ?, '2026-05-07 00:00:00.000000')
            """,
            (file_version_id, f"manual_run_{file_version_id}_{status}", status, None, error_message),
        )
        return int(cursor.lastrowid)


def insert_current_analysis_result(
    tmp_path: Path,
    *,
    file_version_id: int,
    analysis_run_id: int,
) -> None:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute(
            """
            insert into analysis_results
                (
                    file_version_id,
                    analysis_run_id,
                    is_current,
                    prompt_version,
                    evidence_package,
                    structured_outline,
                    qa_available,
                    created_at
                )
            values (?, ?, 1, 'mda_outline_v1', '{}', '{}', 1, '2026-05-07 00:00:00.000000')
            """,
            (file_version_id, analysis_run_id),
        )


def upload_report(
    client: TestClient,
    *,
    stock_code: str,
    company_name: str,
    filename: str,
    content: bytes,
) -> dict:
    client.app.state.admission.extractor.pages = annual_report_pages(
        first_page_text=first_page(company_name=company_name),
        profile_text=company_profile_section(
            company_full_name=company_name,
            company_short_name=None,
            stock_lines=f"股票代码：{stock_code}",
        ),
    )
    response = upload(client, filename=filename, content=content)
    assert response.status_code == 201
    return response.json()


def test_duplicate_active_file_version_upload_returns_existing_summaries(tmp_path: Path) -> None:
    client = make_client(tmp_path, annual_report_pages())
    accepted = upload(client, filename="moutai-2024.pdf")
    assert accepted.status_code == 201

    duplicate = upload(client, filename="same-content.pdf")

    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "error_code": "DUPLICATE_FILE_VERSION",
        "message": "该文件已上传",
        "details": {
            "annual_report": {
                "id": accepted.json()["annual_report"]["id"],
                "normalized_stock_code": "A:600519",
                "stock_code": "600519",
                "report_year": 2024,
                "company_full_name": "贵州茅台酒股份有限公司",
                "company_short_name": "贵州茅台",
                "summary_status": "未分析",
            },
            "file_version": {
                "id": accepted.json()["file_version"]["id"],
                "original_filename": "moutai-2024.pdf",
                "content_hash": accepted.json()["file_version"]["content_hash"],
                "uploaded_at": accepted.json()["file_version"]["uploaded_at"],
                "display_status": "not_analyzed",
                "display_status_message": None,
            },
        },
    }


def test_upload_groups_file_versions_by_normalized_stock_code_and_report_year(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_pages())

    first = upload(client, filename="moutai-original.pdf", content=b"%PDF-1.7\nfirst")
    second = upload(client, filename="moutai-revised.pdf", content=b"%PDF-1.7\nsecond")
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["annual_report_already_exists"] is True

    client.app.state.admission.extractor.pages = annual_report_pages(
        profile_text=company_profile_section(stock_lines="股票代码：000858")
    )
    same_name_different_code = upload(
        client,
        filename="same-company-different-code.pdf",
        content=b"%PDF-1.7\nthird",
    )
    assert same_name_different_code.status_code == 201
    assert same_name_different_code.json()["annual_report_already_exists"] is False

    listed = client.get("/api/annual-reports").json()["items"]

    assert {report["normalized_stock_code"] for report in listed} == {"A:600519", "A:000858"}
    assert [report["company_full_name"] for report in listed] == [
        "贵州茅台酒股份有限公司",
        "贵州茅台酒股份有限公司",
    ]
    grouped = {
        report["normalized_stock_code"]: [
            version["original_filename"] for version in report["file_versions"]
        ]
        for report in listed
    }
    assert grouped["A:600519"] == ["moutai-original.pdf", "moutai-revised.pdf"]
    assert grouped["A:000858"] == ["same-company-different-code.pdf"]


def test_deleted_content_reupload_creates_a_new_active_file_version(tmp_path: Path) -> None:
    client = make_client(tmp_path, annual_report_pages())
    original = upload(client, filename="deleted-later.pdf", content=PDF_BYTES)
    assert original.status_code == 201
    original_file_version_id = original.json()["file_version"]["id"]

    mark_file_version_deleted(tmp_path, original_file_version_id)
    reuploaded = upload(client, filename="uploaded-again.pdf", content=PDF_BYTES)

    assert reuploaded.status_code == 201
    assert reuploaded.json()["annual_report_already_exists"] is True
    assert reuploaded.json()["file_version"]["id"] != original_file_version_id
    listed = client.get("/api/annual-reports").json()["items"]
    assert [[version["original_filename"] for version in report["file_versions"]] for report in listed] == [
        ["uploaded-again.pdf"]
    ]


def test_summary_and_file_version_display_statuses_are_inferred_from_current_state(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, annual_report_pages())

    analyzing_report = upload_report(
        client,
        stock_code="600001",
        company_name="状态一股份有限公司",
        filename="analyzed.pdf",
        content=b"%PDF-1.7\nanalyzed",
    )
    analyzing_file_version = upload_report(
        client,
        stock_code="600001",
        company_name="状态一股份有限公司",
        filename="analyzing.pdf",
        content=b"%PDF-1.7\nanalyzing",
    )
    ready_run = insert_analysis_run(
        tmp_path,
        file_version_id=analyzing_report["file_version"]["id"],
        status="ready",
    )
    insert_current_analysis_result(
        tmp_path,
        file_version_id=analyzing_report["file_version"]["id"],
        analysis_run_id=ready_run,
    )
    insert_analysis_run(
        tmp_path,
        file_version_id=analyzing_file_version["file_version"]["id"],
        status="parsing",
    )

    report_with_current_result = upload_report(
        client,
        stock_code="600002",
        company_name="状态二股份有限公司",
        filename="current-result-wins.pdf",
        content=b"%PDF-1.7\ncurrent result",
    )
    current_result_run = insert_analysis_run(
        tmp_path,
        file_version_id=report_with_current_result["file_version"]["id"],
        status="ready",
    )
    insert_current_analysis_result(
        tmp_path,
        file_version_id=report_with_current_result["file_version"]["id"],
        analysis_run_id=current_result_run,
    )
    insert_analysis_run(
        tmp_path,
        file_version_id=report_with_current_result["file_version"]["id"],
        status="failed",
        error_message="后续失败不覆盖当前报告",
    )

    failed_report = upload_report(
        client,
        stock_code="600003",
        company_name="状态三股份有限公司",
        filename="failed.pdf",
        content=b"%PDF-1.7\nfailed",
    )
    insert_analysis_run(
        tmp_path,
        file_version_id=failed_report["file_version"]["id"],
        status="failed",
        error_message="模型调用失败",
    )

    stopped_report = upload_report(
        client,
        stock_code="600004",
        company_name="状态四股份有限公司",
        filename="stopped.pdf",
        content=b"%PDF-1.7\nstopped",
    )
    insert_analysis_run(
        tmp_path,
        file_version_id=stopped_report["file_version"]["id"],
        status="stopped",
    )

    upload_report(
        client,
        stock_code="600005",
        company_name="状态五股份有限公司",
        filename="not-analyzed.pdf",
        content=b"%PDF-1.7\nnot analyzed",
    )

    missing_result_report = upload_report(
        client,
        stock_code="600006",
        company_name="状态六股份有限公司",
        filename="ready-without-result.pdf",
        content=b"%PDF-1.7\nready missing result",
    )
    insert_analysis_run(
        tmp_path,
        file_version_id=missing_result_report["file_version"]["id"],
        status="ready",
    )

    reports = {
        report["normalized_stock_code"]: report
        for report in client.get("/api/annual-reports").json()["items"]
    }

    assert reports["A:600001"]["summary_status"] == "分析中"
    assert {
        version["original_filename"]: version["display_status"]
        for version in reports["A:600001"]["file_versions"]
    } == {"analyzed.pdf": "analyzed", "analyzing.pdf": "analyzing"}

    assert reports["A:600002"]["summary_status"] == "有报告"
    assert reports["A:600002"]["file_versions"][0]["display_status"] == "analyzed"

    assert reports["A:600003"]["summary_status"] == "有失败"
    assert reports["A:600003"]["file_versions"][0]["display_status"] == "analysis_failed"
    assert reports["A:600003"]["file_versions"][0]["display_status_message"] == "模型调用失败"

    assert reports["A:600004"]["summary_status"] == "已停止"
    assert reports["A:600004"]["file_versions"][0]["display_status"] == "stopped"

    assert reports["A:600005"]["summary_status"] == "未分析"
    assert reports["A:600005"]["file_versions"][0]["display_status"] == "not_analyzed"

    assert reports["A:600006"]["summary_status"] == "有失败"
    assert reports["A:600006"]["file_versions"][0]["display_status"] == "analysis_failed"
    assert reports["A:600006"]["file_versions"][0]["display_status_message"] == "分析结果缺失"
