from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.pdf_extraction import PdfTextDocument


PDF_BYTES = b"%PDF-1.7\nlibrary deletion bytes"


class FakeExtractor:
    def __init__(self, pages: list[str]):
        self.pages = pages

    def extract_text(self, _content: bytes) -> PdfTextDocument:
        return PdfTextDocument(self.pages)


class RecordingCleaner:
    def __init__(self):
        self.cleaned_ids: list[str] = []

    def cleanup_run(self, implementation_id: str) -> None:
        self.cleaned_ids.append(implementation_id)


class FailingCleaner:
    def cleanup_run(self, implementation_id: str) -> None:
        raise RuntimeError(f"cleanup failed for {implementation_id}")


def annual_report_pages() -> list[str]:
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
            ]
        ),
        "第四节 公司治理\n本节内容不应进入分析证据。",
    ]


def make_client(
    tmp_path: Path,
    *,
    source_pdf_dir: Path | None = None,
    report_asset_dir: Path | None = None,
    analysis_artifact_dir: Path | None = None,
    cleaner=None,
) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        source_pdf_dir=source_pdf_dir or tmp_path / "source_pdfs",
        report_asset_dir=report_asset_dir or tmp_path / "report_assets",
        analysis_artifact_dir=analysis_artifact_dir or tmp_path / "analysis_artifacts",
        extractor=FakeExtractor(annual_report_pages()),
    )
    if cleaner is not None:
        app.state.mda_analysis.resource_cleaner = cleaner
        app.state.library_lifecycle.resource_cleaner = cleaner
    return TestClient(app)


def upload(client: TestClient, *, filename: str = "moutai-2024.pdf", content: bytes = PDF_BYTES):
    return client.post(
        "/api/uploads/annual-reports",
        files={"file": (filename, content, "application/pdf")},
    )


def mark_run_parsing(tmp_path: Path, file_version_id: int) -> None:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute(
            """
            insert into analysis_runs
                (file_version_id, implementation_id, status, stage, stage_history, created_at)
            values (?, ?, 'parsing', 'locating_section', '["locating_section"]', '2026-05-07 00:00:00.000000')
            """,
            (file_version_id, f"manual_active_{file_version_id}"),
        )


def source_pdf_path(tmp_path: Path, file_version_id: int) -> Path:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        row = connection.execute(
            "select storage_path from file_versions where id = ?",
            (file_version_id,),
        ).fetchone()
    assert row is not None
    return Path(str(row[0]))


def active_file_version_ids(tmp_path: Path) -> list[int]:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        rows = connection.execute(
            "select id from file_versions where is_deleted = 0 order by id"
        ).fetchall()
    return [int(row[0]) for row in rows]


def latest_run_status(tmp_path: Path, file_version_id: int) -> str:
    with sqlite3.connect(tmp_path / "test.db") as connection:
        row = connection.execute(
            """
            select status
            from analysis_runs
            where file_version_id = ?
            order by id desc
            limit 1
            """,
            (file_version_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_file_version_delete_confirmation_lists_affected_state(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201

    confirmation = client.get(f"/api/file-versions/{file_version_id}/delete-confirmation")

    assert confirmation.status_code == 200
    assert confirmation.json() == {
        "file_version_id": file_version_id,
        "annual_report_id": uploaded.json()["annual_report"]["id"],
        "original_filename": "moutai-2024.pdf",
        "analysis_result_count": 1,
        "will_delete_annual_report": True,
    }


def test_delete_file_version_cleans_pdf_current_result_and_empty_annual_report(
    tmp_path: Path,
) -> None:
    cleaner = RecordingCleaner()
    client = make_client(tmp_path, cleaner=cleaner)
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201
    implementation_id = started.json()["implementation_id"]
    pdf_path = source_pdf_path(tmp_path, file_version_id)
    assert pdf_path.exists()

    deleted = client.delete(f"/api/file-versions/{file_version_id}?confirm=true")

    assert deleted.status_code == 200
    assert deleted.json() == {
        "file_version_id": file_version_id,
        "annual_report_id": uploaded.json()["annual_report"]["id"],
        "deleted_analysis_result_count": 1,
        "deleted_annual_report_id": uploaded.json()["annual_report"]["id"],
    }
    assert cleaner.cleaned_ids == [implementation_id]
    assert not pdf_path.exists()
    assert client.get("/api/annual-reports").json()["items"] == []
    assert active_file_version_ids(tmp_path) == []
    assert latest_run_status(tmp_path, file_version_id) == "result_deleted"
    report = client.get(f"/api/file-versions/{file_version_id}/analysis-result")
    assert report.status_code == 404
    assert report.json() == {
        "error_code": "FILE_VERSION_NOT_FOUND",
        "message": "文件版本不存在",
    }


def test_delete_file_version_blocks_when_analysis_is_in_progress(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    mark_run_parsing(tmp_path, file_version_id)

    blocked = client.delete(f"/api/file-versions/{file_version_id}?confirm=true")

    assert blocked.status_code == 409
    assert blocked.json() == {
        "error_code": "ANALYSIS_ALREADY_IN_PROGRESS",
        "message": "该文件版本已有分析正在进行",
    }


def test_delete_annual_report_confirmation_lists_file_versions_and_result_counts(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    first = upload(client, filename="moutai-v1.pdf", content=b"%PDF-1.7\nv1")
    second = upload(client, filename="moutai-v2.pdf", content=b"%PDF-1.7\nv2")
    assert first.status_code == 201
    assert second.status_code == 201
    started = client.post(f"/api/file-versions/{first.json()['file_version']['id']}/analysis-runs")
    assert started.status_code == 201

    confirmation = client.get(
        f"/api/annual-reports/{first.json()['annual_report']['id']}/delete-confirmation"
    )

    assert confirmation.status_code == 200
    assert confirmation.json() == {
        "annual_report_id": first.json()["annual_report"]["id"],
        "file_version_count": 2,
        "analysis_result_count": 1,
        "file_versions": [
            {
                "file_version_id": first.json()["file_version"]["id"],
                "original_filename": "moutai-v1.pdf",
                "has_current_analysis_result": True,
            },
            {
                "file_version_id": second.json()["file_version"]["id"],
                "original_filename": "moutai-v2.pdf",
                "has_current_analysis_result": False,
            },
        ],
    }


def test_delete_annual_report_deletes_all_file_versions_and_resources(tmp_path: Path) -> None:
    cleaner = RecordingCleaner()
    client = make_client(tmp_path, cleaner=cleaner)
    first = upload(client, filename="moutai-v1.pdf", content=b"%PDF-1.7\nv1")
    second = upload(client, filename="moutai-v2.pdf", content=b"%PDF-1.7\nv2")
    assert first.status_code == 201
    assert second.status_code == 201
    started = client.post(f"/api/file-versions/{first.json()['file_version']['id']}/analysis-runs")
    assert started.status_code == 201
    implementation_id = started.json()["implementation_id"]
    first_pdf = source_pdf_path(tmp_path, first.json()["file_version"]["id"])
    second_pdf = source_pdf_path(tmp_path, second.json()["file_version"]["id"])

    deleted = client.delete(
        f"/api/annual-reports/{first.json()['annual_report']['id']}?confirm=true"
    )

    assert deleted.status_code == 200
    assert deleted.json() == {
        "annual_report_id": first.json()["annual_report"]["id"],
        "deleted_file_version_count": 2,
        "deleted_analysis_result_count": 1,
    }
    assert cleaner.cleaned_ids == [implementation_id]
    assert not first_pdf.exists()
    assert not second_pdf.exists()
    assert client.get("/api/annual-reports").json()["items"] == []
    assert active_file_version_ids(tmp_path) == []


def test_delete_annual_report_blocks_when_any_file_version_is_analyzing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    uploaded = upload(client)
    assert uploaded.status_code == 201
    mark_run_parsing(tmp_path, uploaded.json()["file_version"]["id"])

    blocked = client.delete(
        f"/api/annual-reports/{uploaded.json()['annual_report']['id']}?confirm=true"
    )

    assert blocked.status_code == 409
    assert blocked.json() == {
        "error_code": "ANNUAL_REPORT_HAS_ANALYSIS_IN_PROGRESS",
        "message": "该年报下有文件版本正在分析，请先停止分析",
    }


def test_file_version_delete_returns_source_pdf_failed_when_unlink_errors(tmp_path: Path) -> None:
    source_dir = tmp_path / "source_pdfs"
    source_dir.mkdir(parents=True, exist_ok=True)
    blocker = source_dir / "readonly_blocker.txt"
    blocker.write_text("x", encoding="utf-8")
    client = make_client(tmp_path, source_pdf_dir=source_dir)
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    pdf_path = source_pdf_path(tmp_path, file_version_id)

    # Make the storage path non-unlinkable in a portable way.
    # On Windows/WSL mounts, chmod-based readonly behavior is unreliable.
    assert pdf_path.exists()
    pdf_path.unlink()
    pdf_path.mkdir()
    try:
        failed = client.delete(f"/api/file-versions/{file_version_id}?confirm=true")
    finally:
        if pdf_path.exists() and pdf_path.is_dir():
            pdf_path.rmdir()

    assert failed.status_code == 500
    assert failed.json() == {
        "error_code": "DELETE_SOURCE_PDF_FAILED",
        "message": "删除源 PDF 失败",
    }


def test_file_version_delete_returns_artifact_error_when_cleanup_fails(tmp_path: Path) -> None:
    client = make_client(tmp_path, cleaner=FailingCleaner())
    uploaded = upload(client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201

    failed = client.delete(f"/api/file-versions/{file_version_id}?confirm=true")

    assert failed.status_code == 500
    assert failed.json() == {
        "error_code": "DELETE_ANALYSIS_ARTIFACTS_FAILED",
        "message": "删除分析产物失败",
    }


def test_startup_cleanup_removes_missing_source_file_versions_and_orphan_assets(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source_pdfs"
    report_asset_dir = tmp_path / "report_assets"
    analysis_artifact_dir = tmp_path / "analysis_artifacts"

    first_client = make_client(
        tmp_path,
        source_pdf_dir=source_dir,
        report_asset_dir=report_asset_dir,
        analysis_artifact_dir=analysis_artifact_dir,
    )
    uploaded = upload(first_client)
    assert uploaded.status_code == 201
    file_version_id = uploaded.json()["file_version"]["id"]
    started = first_client.post(f"/api/file-versions/{file_version_id}/analysis-runs")
    assert started.status_code == 201
    implementation_id = started.json()["implementation_id"]
    first_client.close()

    missing_pdf = source_pdf_path(tmp_path, file_version_id)
    missing_pdf.unlink()
    orphan_dir = report_asset_dir / "orphan_run_001"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "thumb.png").write_bytes(b"orphan")
    orphan_analysis_dir = analysis_artifact_dir / "pages" / implementation_id
    orphan_analysis_dir.mkdir(parents=True, exist_ok=True)
    (orphan_analysis_dir / "page.md").write_text("x", encoding="utf-8")

    repaired_client = make_client(
        tmp_path,
        source_pdf_dir=source_dir,
        report_asset_dir=report_asset_dir,
        analysis_artifact_dir=analysis_artifact_dir,
    )

    assert repaired_client.get("/api/annual-reports").json()["items"] == []
    assert active_file_version_ids(tmp_path) == []
    assert latest_run_status(tmp_path, file_version_id) == "result_deleted"
    assert not orphan_dir.exists()
    assert not orphan_analysis_dir.exists()
