from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import BusinessError
from backend.app.models import AnalysisResult, AnalysisRun, AnnualReport, FileVersion


ANALYSIS_STATUS_PARSING = "parsing"
ANALYSIS_STATUS_GENERATING = "generating"
ANALYSIS_STATUS_READY = "ready"
ANALYSIS_STATUS_FAILED = "failed"
ANALYSIS_STATUS_STOPPED = "stopped"
ANALYSIS_STATUS_RESULT_DELETED = "result_deleted"

ACTIVE_ANALYSIS_STATUSES = frozenset(
    {
        ANALYSIS_STATUS_PARSING,
        ANALYSIS_STATUS_GENERATING,
    }
)

DISPLAY_STATUS_NOT_ANALYZED = "not_analyzed"
DISPLAY_STATUS_ANALYZING = "analyzing"
DISPLAY_STATUS_ANALYZED = "analyzed"
DISPLAY_STATUS_ANALYSIS_FAILED = "analysis_failed"
DISPLAY_STATUS_STOPPED = "stopped"

READY_WITHOUT_RESULT_MESSAGE = "分析结果缺失"

ANALYSIS_STAGES = [
    "locating_section",
    "extracting_content",
    "analyzing_figures",
    "generating_report",
    "building_qa_index",
    "completed",
]


class AnalysisResourceCleaner(Protocol):
    def cleanup_run(self, implementation_id: str) -> None:
        """Remove run-scoped intermediate artifacts and generated resources."""


class FigureAssetStore(Protocol):
    root: Path

    def cleanup_run(self, implementation_id: str) -> None:
        """Remove temporary and official assets for one run."""


@dataclass(frozen=True)
class FileVersionState:
    display_status: str
    display_status_message: str | None = None
    has_current_analysis_result: bool = False
    latest_analysis_run_status: str | None = None

    @property
    def is_analyzing(self) -> bool:
        return self.display_status == DISPLAY_STATUS_ANALYZING

    @property
    def can_start_analysis(self) -> bool:
        return self.display_status in {
            DISPLAY_STATUS_NOT_ANALYZED,
            DISPLAY_STATUS_ANALYSIS_FAILED,
            DISPLAY_STATUS_STOPPED,
        }


class AnalysisRunLifecycle:
    def __init__(
        self,
        *,
        resource_cleaner: AnalysisResourceCleaner,
        figure_asset_store: FigureAssetStore,
    ):
        self.resource_cleaner = resource_cleaner
        self.figure_asset_store = figure_asset_store

    def infer_file_version_state(self, file_version: FileVersion) -> FileVersionState:
        if self._has_current_analysis_result(file_version):
            return FileVersionState(
                display_status=DISPLAY_STATUS_ANALYZED,
                has_current_analysis_result=True,
            )

        latest_run = latest_analysis_run(file_version)
        if latest_run is None:
            return FileVersionState(display_status=DISPLAY_STATUS_NOT_ANALYZED)

        if is_active_analysis_status(latest_run.status):
            return FileVersionState(
                display_status=DISPLAY_STATUS_ANALYZING,
                latest_analysis_run_status=latest_run.status,
            )
        if latest_run.status == ANALYSIS_STATUS_READY:
            return FileVersionState(
                display_status=DISPLAY_STATUS_ANALYSIS_FAILED,
                display_status_message=READY_WITHOUT_RESULT_MESSAGE,
                latest_analysis_run_status=latest_run.status,
            )
        if latest_run.status == ANALYSIS_STATUS_FAILED:
            return FileVersionState(
                display_status=DISPLAY_STATUS_ANALYSIS_FAILED,
                display_status_message=latest_run.error_message,
                latest_analysis_run_status=latest_run.status,
            )
        if latest_run.status == ANALYSIS_STATUS_STOPPED:
            return FileVersionState(
                display_status=DISPLAY_STATUS_STOPPED,
                latest_analysis_run_status=latest_run.status,
            )
        return FileVersionState(
            display_status=DISPLAY_STATUS_NOT_ANALYZED,
            latest_analysis_run_status=latest_run.status,
        )

    def current_analysis_result_exists(self, session: Session, file_version_id: int) -> bool:
        return (
            session.scalar(
                select(AnalysisResult.id).where(
                    AnalysisResult.file_version_id == file_version_id,
                    AnalysisResult.is_current.is_(True),
                )
            )
            is not None
        )

    def has_active_analysis_run(self, session: Session, file_version_id: int) -> bool:
        return (
            session.scalar(
                select(AnalysisRun.id).where(
                    AnalysisRun.file_version_id == file_version_id,
                    AnalysisRun.status.in_(ACTIVE_ANALYSIS_STATUSES),
                )
            )
            is not None
        )

    def latest_active_analysis_run(self, session: Session, file_version_id: int) -> AnalysisRun | None:
        return session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.file_version_id == file_version_id,
                AnalysisRun.status.in_(ACTIVE_ANALYSIS_STATUSES),
            )
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        )

    def require_file_version_can_start_analysis(
        self,
        session: Session,
        *,
        file_version_id: int,
    ) -> FileVersion:
        file_version = self.require_visible_file_version(session, file_version_id=file_version_id)
        if self.current_analysis_result_exists(session, file_version_id):
            raise BusinessError("ANALYSIS_RESULT_ALREADY_EXISTS")
        if self.has_active_analysis_run(session, file_version_id):
            raise BusinessError("ANALYSIS_ALREADY_IN_PROGRESS")
        return file_version

    def require_no_active_analysis_run(self, session: Session, file_version_id: int) -> None:
        if self.has_active_analysis_run(session, file_version_id):
            raise BusinessError("ANALYSIS_ALREADY_IN_PROGRESS")

    def begin_analysis(
        self,
        session: Session,
        *,
        file_version_id: int,
        concurrency_limit: int,
    ) -> tuple[FileVersion, AnalysisRun]:
        file_version = self.require_file_version_can_start_analysis(
            session,
            file_version_id=file_version_id,
        )

        active_count = session.scalar(
            select(func.count(AnalysisRun.id)).where(
                AnalysisRun.status.in_(ACTIVE_ANALYSIS_STATUSES)
            )
        )
        if int(active_count or 0) >= concurrency_limit:
            raise BusinessError("ANALYSIS_CONCURRENCY_LIMIT_REACHED")

        run = self.create_analysis_run(session, file_version_id=file_version_id)
        return file_version, run

    def create_analysis_run(self, session: Session, *, file_version_id: int) -> AnalysisRun:
        run = AnalysisRun(
            file_version_id=file_version_id,
            implementation_id=f"analysis_run_{uuid4().hex}",
            status=ANALYSIS_STATUS_PARSING,
            stage="locating_section",
            stage_history=["locating_section"],
        )
        session.add(run)
        session.flush()
        session.commit()
        return run

    def advance_run(
        self,
        session: Session,
        run: AnalysisRun,
        *,
        stage: str,
        status: str | None = None,
    ) -> AnalysisRun:
        if status is not None:
            run.status = status
        run.stage = stage
        history = list(run.stage_history or [])
        if not history or history[-1] != stage:
            history.append(stage)
        run.stage_history = history
        session.commit()
        return run

    def mark_run_ready(self, session: Session, run: AnalysisRun) -> AnalysisRun:
        run.status = ANALYSIS_STATUS_READY
        run.error_code = None
        run.error_message = None
        run.stage = "completed"
        history = list(run.stage_history or [])
        if not history or history[-1] != "completed":
            history.append("completed")
        run.stage_history = history
        return run

    def mark_run_failed(
        self,
        session: Session,
        run: AnalysisRun,
        *,
        error_code: str,
        error_message: str,
    ) -> AnalysisRun:
        run.status = ANALYSIS_STATUS_FAILED
        run.error_code = error_code
        run.error_message = error_message
        session.commit()
        return run

    def persist_completed_result(
        self,
        session: Session,
        *,
        run: AnalysisRun,
        result: AnalysisResult,
    ) -> AnalysisResult:
        self.mark_run_ready(session, run)
        session.add(result)
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            self.cleanup_run_resources(run.implementation_id)
            persisted_run = session.get(AnalysisRun, run.id)
            if persisted_run is not None:
                self.mark_run_failed(
                    session,
                    persisted_run,
                    error_code="ANALYSIS_RESULT_SAVE_FAILED",
                    error_message="分析报告保存失败",
                )
            raise BusinessError("ANALYSIS_RESULT_SAVE_FAILED") from exc
        return result

    def resolve_start_stopped(self, session: Session, run: AnalysisRun) -> None:
        self.figure_asset_store.cleanup_run(run.implementation_id)
        session.commit()

    def resolve_start_business_error(
        self,
        session: Session,
        *,
        run: AnalysisRun,
        error: BusinessError,
    ) -> bool:
        session.refresh(run)
        if is_stopped_analysis_run(run):
            self.resolve_start_stopped(session, run)
            return True
        self.figure_asset_store.cleanup_run(run.implementation_id)
        self.mark_run_failed(
            session,
            run,
            error_code=error.spec.error_code,
            error_message=error.spec.message,
        )
        return False

    def stop_analysis(self, session: Session, *, file_version_id: int) -> AnalysisRun:
        self.require_visible_file_version(session, file_version_id=file_version_id)
        run = self.latest_active_analysis_run(session, file_version_id)
        if run is None:
            raise BusinessError("STOP_ANALYSIS_FAILED")

        mark_analysis_run_stopped(run)
        session.commit()

        try:
            self.cleanup_run_resources(run.implementation_id)
        except Exception as exc:
            self.mark_run_failed(
                session,
                run,
                error_code="STOP_ANALYSIS_CLEANUP_FAILED",
                error_message="停止分析时清理中间结果失败",
            )
            raise BusinessError("STOP_ANALYSIS_CLEANUP_FAILED") from exc

        return run

    def delete_current_result(
        self,
        session: Session,
        *,
        file_version_id: int,
        missing_ok: bool = False,
        suppress_cleanup_errors: bool = False,
    ) -> AnalysisRun | None:
        self.require_visible_file_version(session, file_version_id=file_version_id)
        result = self.current_analysis_result(session, file_version_id)
        if result is None:
            if missing_ok:
                return None
            raise BusinessError("ANALYSIS_RESULT_NOT_FOUND")

        run = result.analysis_run
        try:
            self.cleanup_run_resources(run.implementation_id)
        except Exception as exc:
            if not suppress_cleanup_errors:
                raise BusinessError("DELETE_ANALYSIS_ARTIFACTS_FAILED") from exc
        mark_analysis_result_deleted(run)
        session.delete(result)
        return run

    def cleanup_missing_source_file_version(self, session: Session, file_version: FileVersion) -> None:
        self.delete_current_result(
            session,
            file_version_id=file_version.id,
            missing_ok=True,
            suppress_cleanup_errors=True,
        )
        if file_version.active_content_hash is not None:
            session.delete(file_version.active_content_hash)
        file_version.is_deleted = True

    def cleanup_orphan_report_asset_dirs(self, session: Session) -> None:
        root = getattr(self.figure_asset_store, "root", None)
        if not isinstance(root, Path) or not root.exists():
            return

        valid_implementation_ids = set(
            session.scalars(
                select(AnalysisRun.implementation_id)
                .join(AnalysisResult, AnalysisResult.analysis_run_id == AnalysisRun.id)
                .join(FileVersion, FileVersion.id == AnalysisResult.file_version_id)
                .join(AnnualReport, AnnualReport.id == FileVersion.annual_report_id)
                .where(
                    AnalysisResult.is_current.is_(True),
                    FileVersion.is_deleted.is_(False),
                    AnnualReport.is_deleted.is_(False),
                )
            )
        )

        for entry in root.iterdir():
            if not entry.is_dir() or entry.name == "_tmp":
                continue
            if entry.name in valid_implementation_ids:
                continue
            try:
                self.figure_asset_store.cleanup_run(entry.name)
            except Exception:
                pass

        tmp_root = root / "_tmp"
        if not tmp_root.exists():
            return
        for entry in tmp_root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in valid_implementation_ids:
                continue
            try:
                self.figure_asset_store.cleanup_run(entry.name)
            except Exception:
                pass

    def cleanup_run_resources(self, implementation_id: str) -> None:
        self.resource_cleaner.cleanup_run(implementation_id)
        self.figure_asset_store.cleanup_run(implementation_id)

    def require_visible_file_version(
        self,
        session: Session,
        *,
        file_version_id: int,
    ) -> FileVersion:
        file_version = session.get(FileVersion, file_version_id)
        if (
            file_version is None
            or file_version.is_deleted
            or file_version.annual_report.is_deleted
        ):
            raise BusinessError("FILE_VERSION_NOT_FOUND")
        return file_version

    def current_analysis_result(self, session: Session, file_version_id: int) -> AnalysisResult | None:
        return session.scalar(
            select(AnalysisResult).where(
                AnalysisResult.file_version_id == file_version_id,
                AnalysisResult.is_current.is_(True),
            )
        )

    def _has_current_analysis_result(self, file_version: FileVersion) -> bool:
        return any(result.is_current for result in file_version.analysis_results)


def infer_file_version_state(file_version: FileVersion) -> FileVersionState:
    return AnalysisRunLifecycle(
        resource_cleaner=_NoopResourceCleaner(),
        figure_asset_store=_NoopFigureAssetStore(),
    ).infer_file_version_state(file_version)


def infer_annual_report_summary_status(display_statuses: Iterable[str]) -> str:
    statuses = set(display_statuses)
    if DISPLAY_STATUS_ANALYZING in statuses:
        return "分析中"
    if DISPLAY_STATUS_ANALYZED in statuses:
        return "有报告"
    if DISPLAY_STATUS_ANALYSIS_FAILED in statuses:
        return "有失败"
    if DISPLAY_STATUS_STOPPED in statuses:
        return "已停止"
    return "未分析"


def latest_analysis_run(file_version: FileVersion) -> AnalysisRun | None:
    return max(
        file_version.analysis_runs,
        key=lambda run: (run.created_at, run.id),
        default=None,
    )


def is_active_analysis_status(status: str) -> bool:
    return status in ACTIVE_ANALYSIS_STATUSES


def is_stopped_analysis_run(run: AnalysisRun) -> bool:
    return run.status == ANALYSIS_STATUS_STOPPED


def mark_analysis_run_stopped(run: AnalysisRun) -> None:
    run.status = ANALYSIS_STATUS_STOPPED
    run.error_code = None
    run.error_message = None


def mark_analysis_result_deleted(run: AnalysisRun) -> None:
    run.status = ANALYSIS_STATUS_RESULT_DELETED
    run.error_code = None
    run.error_message = None


class _NoopResourceCleaner:
    def cleanup_run(self, implementation_id: str) -> None:
        del implementation_id


class _NoopFigureAssetStore:
    root = Path(".")

    def cleanup_run(self, implementation_id: str) -> None:
        del implementation_id
