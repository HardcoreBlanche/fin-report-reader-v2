from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.pdf_extraction import PdfReadError, PdfTextDocument
from backend.app.schemas import UploadSuccessResponse


PDF_BYTES = b"%PDF-1.7\nfake test bytes"


class FakeExtractor:
    def __init__(self, pages: list[str] | None = None, *, unreadable: bool = False):
        self.pages = pages or []
        self.unreadable = unreadable

    def extract_text(self, _content: bytes) -> PdfTextDocument:
        if self.unreadable:
            raise PdfReadError
        return PdfTextDocument(self.pages)


def make_client(tmp_path: Path, pages: list[str] | None = None, *, unreadable: bool = False) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        source_pdf_dir=tmp_path / "source_pdfs",
        extractor=FakeExtractor(pages, unreadable=unreadable),
    )
    return TestClient(app)


def first_page(company_name: str = "贵州茅台酒股份有限公司", year: int = 2024) -> str:
    return f"{company_name}\n{year} 年年度报告"


def company_profile_section(
    *,
    company_full_name: str = "贵州茅台酒股份有限公司",
    stock_lines: str = "股票代码：600519",
    date_line: str = "主要会计数据日期：2024年12月31日",
    company_short_name: str = "公司简称：贵州茅台",
) -> str:
    return "\n".join(
        [
            "第二节 公司简介和主要财务指标",
            f"公司全称：{company_full_name}",
            company_short_name,
            stock_lines,
            date_line,
        ]
    )


def supported_annual_report_pages(
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


def assert_upload_error(response, status_code: int, error_code: str, message: str) -> None:
    assert response.status_code == status_code
    assert response.json() == {"error_code": error_code, "message": message}


def source_pdf_files(tmp_path: Path) -> list[Path]:
    source_dir = tmp_path / "source_pdfs"
    if not source_dir.exists():
        return []
    return [path for path in source_dir.iterdir() if path.is_file()]


def active_content_hash_count(tmp_path: Path) -> int:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        row = connection.execute("select count(*) from active_content_hashes").fetchone()
    return int(row[0])


def test_rejects_invalid_file_extension_with_stable_error_contract(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = upload(client, filename="not-a-pdf.txt")

    assert_upload_error(response, 400, "INVALID_FILE_EXTENSION", "仅支持 PDF 文件")

    assert client.get("/api/annual-reports").json() == {"items": []}


def test_upload_route_delegates_to_annual_report_upload_intake(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    class RecordingUploadIntake:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bytes]] = []

        def upload(self, session, *, filename: str, content: bytes) -> UploadSuccessResponse:
            del session
            self.calls.append((filename, content))
            return UploadSuccessResponse(
                annual_report={
                    "id": 1,
                    "normalized_stock_code": "A:600519",
                    "stock_code": "600519",
                    "report_year": 2024,
                    "company_full_name": "贵州茅台酒股份有限公司",
                    "company_short_name": "贵州茅台",
                    "summary_status": "未分析",
                },
                file_version={
                    "id": 2,
                    "original_filename": filename,
                    "content_hash": "hash",
                    "uploaded_at": "2026-05-07T00:00:00Z",
                    "display_status": "not_analyzed",
                    "display_status_message": None,
                },
                annual_report_already_exists=False,
            )

    intake = RecordingUploadIntake()
    client.app.state.upload_intake = intake

    response = upload(client, filename="delegated.pdf", content=b"%PDF-1.7\ndelegated")

    assert response.status_code == 201
    assert response.json()["file_version"]["original_filename"] == "delegated.pdf"
    assert intake.calls == [("delegated.pdf", b"%PDF-1.7\ndelegated")]


def test_rejects_invalid_pdf_header_and_unreadable_pdf_as_format_errors(tmp_path: Path) -> None:
    invalid_header_client = make_client(tmp_path / "header")
    invalid_header_response = upload(invalid_header_client, content=b"not a pdf")
    assert_upload_error(invalid_header_response, 400, "INVALID_PDF_HEADER", "文件内容不是有效 PDF")

    unreadable_client = make_client(tmp_path / "unreadable", unreadable=True)
    unreadable_response = upload(unreadable_client)
    assert_upload_error(unreadable_response, 400, "INVALID_PDF_FILE", "PDF 文件无法读取")


def test_rejects_unsupported_report_types_and_non_chinese_reports(tmp_path: Path) -> None:
    cases = [
        (
            [first_page_text := "贵州茅台酒股份有限公司\n2024 年年度报告摘要", company_profile_section()],
            "ANNUAL_REPORT_SUMMARY_NOT_SUPPORTED",
            "当前仅支持完整年度报告，不支持年度报告摘要",
        ),
        (
            ["贵州茅台酒股份有限公司\n2024 年半年度报告", company_profile_section()],
            "NOT_AN_ANNUAL_REPORT",
            "当前仅支持年度报告",
        ),
        (
            ["Kweichow Moutai Co., Ltd.\n2024 Annual Report", company_profile_section()],
            "NON_CHINESE_ANNUAL_REPORT",
            "当前仅支持中文年度报告",
        ),
    ]

    assert first_page_text
    for index, (pages, error_code, message) in enumerate(cases):
        client = make_client(tmp_path / str(index), pages)
        response = upload(client)
        assert_upload_error(response, 422, error_code, message)
        assert client.get("/api/annual-reports").json() == {"items": []}


def test_rejects_missing_company_profile_section(tmp_path: Path) -> None:
    client = make_client(tmp_path, [first_page(), "目录\n第三节 管理层讨论与分析 8"])

    response = upload(client)

    assert_upload_error(response, 422, "COMPANY_PROFILE_SECTION_NOT_FOUND", "无法定位公司简介和主要财务指标")


def test_rejects_identity_extraction_failures_from_structured_body_evidence(tmp_path: Path) -> None:
    cases = [
        (
            "missing_stock_code",
            supported_annual_report_pages(
                profile_text=company_profile_section(stock_lines="公司拥有境内上市证券 600519")
            ),
            "MISSING_STOCK_CODE",
            "无法识别股票代码",
        ),
        (
            "ambiguous_stock_code",
            supported_annual_report_pages(
                profile_text=company_profile_section(stock_lines="股票代码：600519、000858")
            ),
            "AMBIGUOUS_STOCK_CODE",
            "股票代码不唯一",
        ),
        (
            "missing_report_year",
            supported_annual_report_pages(first_page_text="贵州茅台酒股份有限公司\n年度报告"),
            "MISSING_REPORT_YEAR",
            "无法识别报告年度",
        ),
        (
            "missing_company_full_name",
            supported_annual_report_pages(
                profile_text="\n".join(
                    [
                        "第二节 公司简介和主要财务指标",
                        "公司简称：贵州茅台",
                        "股票代码：600519",
                        "主要会计数据日期：2024年12月31日",
                    ]
                )
            ),
            "MISSING_COMPANY_FULL_NAME",
            "无法识别公司全称",
        ),
    ]

    for name, pages, error_code, message in cases:
        client = make_client(tmp_path / name, pages)
        response = upload(client, filename=f"{name}-600519.pdf")
        assert_upload_error(response, 422, error_code, message)
        assert client.get("/api/annual-reports").json() == {"items": []}


def test_rejects_company_name_and_report_year_consistency_failures(tmp_path: Path) -> None:
    mismatch_client = make_client(
        tmp_path / "company",
        supported_annual_report_pages(first_page_text=first_page(company_name="贵州茅台股份有限公司")),
    )
    mismatch_response = upload(mismatch_client)
    assert_upload_error(
        mismatch_response,
        422,
        "COMPANY_FULL_NAME_MISMATCH",
        "首页公司名与公司全称不匹配",
    )

    year_client = make_client(
        tmp_path / "year",
        supported_annual_report_pages(
            profile_text=company_profile_section(date_line="主要会计数据日期：2023年12月31日")
        ),
    )
    year_response = upload(year_client)
    assert_upload_error(year_response, 422, "REPORT_YEAR_MISMATCH", "报告年度不一致")


def test_rejects_when_financial_data_dates_cannot_be_extracted(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        supported_annual_report_pages(
            profile_text=company_profile_section(date_line="主要会计数据：营业收入、净利润")
        ),
    )

    response = upload(client)

    assert_upload_error(response, 422, "TABLE_DATE_EXTRACTION_FAILED", "表格提取日期失败")


def test_accepts_supported_pdf_using_toc_located_profile_section(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        supported_annual_report_pages(),
    )

    response = upload(client, filename="moutai-2024.pdf")

    assert response.status_code == 201
    body = response.json()
    assert body["annual_report_already_exists"] is False
    assert body["annual_report"]["normalized_stock_code"] == "A:600519"
    assert body["annual_report"]["stock_code"] == "600519"
    assert body["annual_report"]["report_year"] == 2024
    assert body["annual_report"]["company_full_name"] == "贵州茅台酒股份有限公司"
    assert body["annual_report"]["company_short_name"] == "贵州茅台"
    assert body["file_version"]["original_filename"] == "moutai-2024.pdf"

    listed = client.get("/api/annual-reports").json()
    assert len(listed["items"]) == 1
    assert listed["items"][0]["file_versions"][0]["original_filename"] == "moutai-2024.pdf"
    assert len(source_pdf_files(tmp_path)) == 1


def test_heading_search_fallback_and_toc_precedence(tmp_path: Path) -> None:
    toc_client = make_client(
        tmp_path / "toc",
        [
            first_page(),
            "目录\n公司简介和主要财务指标 4",
            company_profile_section(stock_lines="股票代码：000858"),
            company_profile_section(stock_lines="股票代码：600519"),
        ],
    )
    toc_response = upload(toc_client)
    assert toc_response.status_code == 201
    assert toc_response.json()["annual_report"]["normalized_stock_code"] == "A:600519"

    fallback_client = make_client(
        tmp_path / "fallback",
        [
            first_page(),
            "目录\n第三节 管理层讨论与分析 8",
            company_profile_section(stock_lines="股票代码：600519"),
        ],
    )
    fallback_response = upload(fallback_client)
    assert fallback_response.status_code == 201
    assert fallback_response.json()["annual_report"]["normalized_stock_code"] == "A:600519"


def test_prefers_a_share_code_when_multiple_supported_markets_are_present(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        supported_annual_report_pages(
            profile_text=company_profile_section(
                stock_lines="A股股票代码：600519\nH股股票代码：00700"
            )
        ),
    )

    response = upload(client)

    assert response.status_code == 201
    assert response.json()["annual_report"]["normalized_stock_code"] == "A:600519"


def test_accepts_minimal_company_name_normalization_without_fuzzy_matching(tmp_path: Path) -> None:
    normalized_client = make_client(
        tmp_path / "normalized",
        supported_annual_report_pages(
            first_page_text=first_page(company_name="贵 州 茅 台 酒 股 份 有 限 公 司")
        ),
    )
    normalized_response = upload(normalized_client)
    assert normalized_response.status_code == 201

    fuzzy_client = make_client(
        tmp_path / "fuzzy",
        supported_annual_report_pages(first_page_text=first_page(company_name="贵州茅台股份有限公司")),
    )
    fuzzy_response = upload(fuzzy_client)
    assert_upload_error(
        fuzzy_response,
        422,
        "COMPANY_FULL_NAME_MISMATCH",
        "首页公司名与公司全称不匹配",
    )


def test_rejected_candidates_do_not_create_visible_records_source_pdf_or_active_hash(tmp_path: Path) -> None:
    client = make_client(tmp_path, supported_annual_report_pages())
    accepted = upload(client, content=b"%PDF-1.7\nfirst")
    assert accepted.status_code == 201

    client.app.state.admission.extractor.pages = supported_annual_report_pages(
        first_page_text=first_page(company_name="其他股份有限公司"),
        profile_text=company_profile_section(company_full_name="其他股份有限公司"),
    )
    rejected = upload(client, filename="conflict.pdf", content=b"%PDF-1.7\nsecond")

    assert_upload_error(
        rejected,
        422,
        "ANNUAL_REPORT_IDENTITY_CONFLICT",
        "该股票代码和年度已存在年报，但公司全称不一致",
    )
    listed = client.get("/api/annual-reports").json()
    assert len(listed["items"]) == 1
    assert len(listed["items"][0]["file_versions"]) == 1
    assert len(source_pdf_files(tmp_path)) == 1
    assert active_content_hash_count(tmp_path) == 1
