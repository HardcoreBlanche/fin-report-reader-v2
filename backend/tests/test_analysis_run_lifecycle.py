from datetime import datetime, timezone

import pytest

from backend.app.analysis_run_lifecycle import READY_WITHOUT_RESULT_MESSAGE
from backend.app.analysis_run_lifecycle import FileVersionState
from backend.app.analysis_run_lifecycle import AnalysisRunLifecycle
from backend.app.analysis_run_lifecycle import infer_annual_report_summary_status
from backend.app.analysis_run_lifecycle import latest_analysis_run
from backend.app.analysis_run_lifecycle import mark_analysis_result_deleted
from backend.app.analysis_run_lifecycle import mark_analysis_run_stopped
from backend.app.errors import BusinessError
from backend.app.models import AnalysisResult, AnalysisRun, AnnualReport, FileVersion
from backend.app.persistence import create_session_factory


CREATED_AT = datetime(2026, 5, 7, tzinfo=timezone.utc)


def test_current_analysis_result_wins_without_exposing_the_result() -> None:
    file_version = file_version_with(
        runs=[
            analysis_run(1, status="ready"),
            analysis_run(2, status="failed", error_message="后续失败不覆盖当前报告"),
        ],
        results=[analysis_result(1, analysis_run_id=1)],
    )

    state = LIFECYCLE.infer_file_version_state(file_version)

    assert state == FileVersionState(
        display_status="analyzed",
        display_status_message=None,
        has_current_analysis_result=True,
        latest_analysis_run_status=None,
    )
    assert state.can_start_analysis is False
    assert not hasattr(state, "current_result")


@pytest.mark.parametrize(
    ("status", "display_status", "message", "can_start"),
    [
        ("parsing", "analyzing", None, False),
        ("generating", "analyzing", None, False),
        ("ready", "analysis_failed", READY_WITHOUT_RESULT_MESSAGE, True),
        ("failed", "analysis_failed", "模型调用失败", True),
        ("stopped", "stopped", None, True),
        ("result_deleted", "not_analyzed", None, True),
    ],
)
def test_latest_analysis_run_maps_to_file_version_state(
    status: str,
    display_status: str,
    message: str | None,
    can_start: bool,
) -> None:
    run = analysis_run(1, status=status, error_message="模型调用失败")
    file_version = file_version_with(runs=[run])

    state = LIFECYCLE.infer_file_version_state(file_version)

    assert state.display_status == display_status
    assert state.display_status_message == message
    assert state.latest_analysis_run_status == status
    assert state.can_start_analysis is can_start


def test_no_analysis_run_is_not_analyzed() -> None:
    state = LIFECYCLE.infer_file_version_state(file_version_with())

    assert state.display_status == "not_analyzed"
    assert state.display_status_message is None
    assert state.can_start_analysis is True


def test_latest_analysis_run_uses_created_at_then_id() -> None:
    older = analysis_run(1, status="failed", created_at=datetime(2026, 5, 6, tzinfo=timezone.utc))
    lower_id = analysis_run(2, status="stopped")
    higher_id = analysis_run(3, status="result_deleted")
    file_version = file_version_with(runs=[higher_id, older, lower_id])

    assert latest_analysis_run(file_version) is higher_id


def test_annual_report_summary_status_priority() -> None:
    assert infer_annual_report_summary_status(["stopped", "analysis_failed"]) == "有失败"
    assert infer_annual_report_summary_status(["analysis_failed", "analyzed"]) == "有报告"
    assert infer_annual_report_summary_status(["analyzed", "analyzing"]) == "分析中"
    assert infer_annual_report_summary_status(["not_analyzed", "stopped"]) == "已停止"
    assert infer_annual_report_summary_status(["not_analyzed"]) == "未分析"


def test_transition_markers_clear_errors() -> None:
    stopped_run = analysis_run(1, status="generating", error_code="OLD", error_message="旧错误")
    deleted_run = analysis_run(2, status="ready", error_code="OLD", error_message="旧错误")

    mark_analysis_run_stopped(stopped_run)
    mark_analysis_result_deleted(deleted_run)

    assert stopped_run.status == "stopped"
    assert stopped_run.error_code is None
    assert stopped_run.error_message is None
    assert deleted_run.status == "result_deleted"
    assert deleted_run.error_code is None
    assert deleted_run.error_message is None


def test_require_file_version_can_start_analysis_blocks_current_result_and_active_run(
    tmp_path,
) -> None:
    session_factory = create_session_factory(f"sqlite:///{tmp_path / 'test.db'}")
    session = session_factory()
    try:
        file_version = persisted_file_version(session)

        assert (
            LIFECYCLE.require_file_version_can_start_analysis(
                session,
                file_version_id=file_version.id,
            ).id
            == file_version.id
        )

        active_run = analysis_run(1, file_version_id=file_version.id, status="parsing")
        session.add(active_run)
        session.commit()
        with pytest.raises(BusinessError) as active_error:
            LIFECYCLE.require_file_version_can_start_analysis(
                session,
                file_version_id=file_version.id,
            )
        assert active_error.value.spec.error_code == "ANALYSIS_ALREADY_IN_PROGRESS"

        active_run.status = "failed"
        session.commit()
        assert (
            LIFECYCLE.require_file_version_can_start_analysis(
                session,
                file_version_id=file_version.id,
            ).id
            == file_version.id
        )

        ready_run = analysis_run(2, file_version_id=file_version.id, status="ready")
        session.add(ready_run)
        session.flush()
        session.add(analysis_result(1, file_version_id=file_version.id, analysis_run_id=ready_run.id))
        session.commit()

        with pytest.raises(BusinessError) as result_error:
            LIFECYCLE.require_file_version_can_start_analysis(
                session,
                file_version_id=file_version.id,
            )
        assert result_error.value.spec.error_code == "ANALYSIS_RESULT_ALREADY_EXISTS"
    finally:
        session.close()


def file_version_with(
    *,
    runs: list[AnalysisRun] | None = None,
    results: list[AnalysisResult] | None = None,
) -> FileVersion:
    return FileVersion(
        id=1,
        annual_report_id=1,
        original_filename="annual-report.pdf",
        content_hash="hash",
        storage_path="/tmp/annual-report.pdf",
        analysis_runs=runs or [],
        analysis_results=results or [],
        uploaded_at=CREATED_AT,
    )


def persisted_file_version(session) -> FileVersion:
    report = AnnualReport(
        stock_code="600519",
        normalized_stock_code="A:600519",
        exchange="SSE",
        report_year=2024,
        company_full_name="贵州茅台酒股份有限公司",
        company_short_name="贵州茅台",
    )
    session.add(report)
    session.flush()
    file_version = FileVersion(
        annual_report_id=report.id,
        original_filename="annual-report.pdf",
        content_hash="hash",
        storage_path="/tmp/annual-report.pdf",
    )
    session.add(file_version)
    session.commit()
    return file_version


def analysis_run(
    run_id: int,
    *,
    status: str,
    file_version_id: int = 1,
    created_at: datetime = CREATED_AT,
    error_code: str | None = None,
    error_message: str | None = None,
) -> AnalysisRun:
    return AnalysisRun(
        id=run_id,
        file_version_id=file_version_id,
        implementation_id=f"analysis_run_{run_id}",
        status=status,
        stage=None,
        stage_history=[],
        error_code=error_code,
        error_message=error_message,
        created_at=created_at,
    )


def analysis_result(
    result_id: int,
    *,
    file_version_id: int = 1,
    analysis_run_id: int,
) -> AnalysisResult:
    return AnalysisResult(
        id=result_id,
        file_version_id=file_version_id,
        analysis_run_id=analysis_run_id,
        is_current=True,
        prompt_version="mda_outline_v1",
        evidence_package={},
        structured_outline={},
        qa_available=True,
        created_at=CREATED_AT,
    )


class NoopCleaner:
    def cleanup_run(self, implementation_id: str) -> None:
        del implementation_id


class NoopFigureAssetStore:
    root = None

    def cleanup_run(self, implementation_id: str) -> None:
        del implementation_id


LIFECYCLE = AnalysisRunLifecycle(
    resource_cleaner=NoopCleaner(),
    figure_asset_store=NoopFigureAssetStore(),
)
